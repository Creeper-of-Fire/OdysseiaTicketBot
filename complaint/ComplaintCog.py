from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

import config
from utility.feature_cog import FeatureCog
from utility.permison import is_admin, is_admin_check

from .config.loader import load_config, read_raw_config, validate_and_save
from .config.models import ComplaintConfig
from .services.archive_service import ComplaintArchiveService
from .services.channel_service import create_complaint_channel, parse_topic
from .ui.embeds import (
    build_close_confirm_embed,
    build_confirm_embed,
    build_entry_embed,
    build_error_embed,
    build_success_embed,
    build_summon_embed,
    build_type_select_embed,
)
from .ui.modals import ComplaintFormModal
from .ui.views import (
    CloseConfirmView,
    EntryView,
    build_confirm_proceed_view,
    build_summon_select_view,
    build_type_select_view,
)

if TYPE_CHECKING:
    from main import TicketBot

logger = logging.getLogger(__name__)


class ComplaintCog(FeatureCog):
    """投诉系统 Cog。"""

    def __init__(self, bot: TicketBot):
        super().__init__(bot)
        self._configs: dict[int, ComplaintConfig] = {}
        self._archive_services: dict[int, ComplaintArchiveService] = {}
        self._pending_forms: dict[tuple[int, str], dict[str, str]] = {}
        bot.add_view(EntryView())
        self.logger.info("投诉系统 Cog 已加载")

    def get_config(self, guild_id: int) -> ComplaintConfig:
        """按 guild_id 获取配置（延迟加载 + 缓存）。"""
        if guild_id not in self._configs:
            self._configs[guild_id] = load_config(guild_id)
            self._archive_services[guild_id] = ComplaintArchiveService(self._configs[guild_id])
        return self._configs[guild_id]

    def _invalidate_config(self, guild_id: int) -> None:
        """清除缓存，下次访问时重新加载。"""
        self._configs.pop(guild_id, None)
        self._archive_services.pop(guild_id, None)

    def _get_archive_service(self, guild_id: int) -> ComplaintArchiveService:
        self.get_config(guild_id)
        return self._archive_services[guild_id]

    # ================= 斜杠命令 =================

    complaint_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨投诉管理",
        description="投诉系统管理命令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @complaint_group.command(name="发布入口面板", description="在当前或指定频道发布投诉入口面板")
    @app_commands.rename(channel="频道")
    @app_commands.describe(channel="发布入口面板的目标频道（不填则使用当前频道）")
    @is_admin()
    async def cmd_post_entry(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ):
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            await interaction.response.send_message("无法定位目标频道。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await target.send(embed=build_entry_embed(), view=EntryView())
        except discord.Forbidden:
            await interaction.edit_original_response(
                content=f"没有权限在 {target.mention} 发送消息。"
            )
            return
        except Exception as e:
            await interaction.edit_original_response(content=f"发布失败：{e}")
            return

        await interaction.edit_original_response(
            content=f"已在 {target.mention} 发布投诉入口面板。"
        )

    @complaint_group.command(name="重载配置", description="从 TOML 文件重新加载投诉配置")
    @is_admin()
    async def cmd_reload(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        guild_id = interaction.guild.id
        self._invalidate_config(guild_id)
        try:
            cfg = self.get_config(guild_id)
        except Exception as e:
            await interaction.response.send_message(f"重载失败：{e}", ephemeral=True)
            return

        await interaction.response.send_message(
            f"✅ 配置已重新加载。{len(cfg.types)} 个投诉类型，"
            f"{len(cfg.role_groups)} 个身份组。",
            ephemeral=True,
        )

    @complaint_group.command(name="下载配置", description="下载当前服务器的投诉系统 TOML 配置文件")
    @is_admin()
    async def cmd_download_config(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        guild_id = interaction.guild.id
        raw = read_raw_config(guild_id)
        if raw is None:
            # 生成默认配置并保存
            cfg = self.get_config(guild_id)
            save_config(cfg, guild_id)
            raw = read_raw_config(guild_id)

        await interaction.response.send_message(
            "📎 当前服务器的投诉配置文件：",
            file=discord.File(
                fp=__import__("io").BytesIO(raw),
                filename=f"complaint_{guild_id}.toml",
            ),
            ephemeral=True,
        )

    @complaint_group.command(name="上传配置", description="上传新的 TOML 配置文件覆盖当前配置")
    @app_commands.rename(config_file="配置文件")
    @app_commands.describe(config_file="上传编辑后的 TOML 配置文件")
    @is_admin()
    async def cmd_upload_config(
        self,
        interaction: discord.Interaction,
        config_file: discord.Attachment,
    ):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        guild_id = interaction.guild.id
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            raw_bytes = await config_file.read()
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"读取文件失败：{e}")
            )
            return

        try:
            cfg = validate_and_save(raw_bytes, guild_id)
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"配置验证失败：\n{e}")
            )
            return

        self._invalidate_config(guild_id)
        await interaction.edit_original_response(
            content=f"✅ 配置已更新并生效。{len(cfg.types)} 个投诉类型，"
                    f"{len(cfg.role_groups)} 个身份组。"
        )

    @complaint_group.command(name="编辑模板", description="编辑投诉频道的初始消息模板")
    @is_admin()
    async def cmd_edit_template(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        from .ui.modals import AdminEditTemplateModal
        modal = AdminEditTemplateModal(self, interaction.guild.id)
        await interaction.response.send_modal(modal)

    @complaint_group.command(name="强制归档", description="手动归档指定的投诉频道")
    @app_commands.rename(channel="频道")
    @app_commands.describe(channel="要归档的投诉频道")
    @is_admin()
    async def cmd_force_archive(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        meta = parse_topic(channel.topic)
        if not meta:
            await interaction.response.send_message(
                "该频道不是投诉频道（无法从 topic 解析投诉元数据）。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = channel.guild.id
        cfg = self.get_config(guild_id)
        type_config = cfg.get_complaint_type(meta.get("type", ""))
        type_label = type_config.label if type_config else meta.get("type", "未知")
        type_emoji = type_config.emoji if type_config else "📋"
        visibility = "公开" if meta.get("visibility") == "public" else "私密"

        try:
            await self._get_archive_service(guild_id).archive_channel(
                channel,
                type_label=type_label,
                type_emoji=type_emoji,
                complainant_id=meta["complainant"],
                visibility=visibility,
                form_data={},
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"归档失败：{e}")
            )
            return

        await interaction.edit_original_response(
            embed=build_success_embed(f"频道 {channel.mention} 已归档并删除。")
        )

    # ================= on_interaction 路由 =================

    @commands.Cog.listener("on_interaction")
    async def on_interaction(self, interaction: discord.Interaction):
        cid = ""
        if interaction.data and isinstance(interaction.data, dict):
            cid = interaction.data.get("custom_id", "")
        if not cid.startswith("complaint:"):
            return

        parts = cid.split(":")
        if len(parts) < 3:
            return
        _, action, *rest = parts

        try:
            if action == "entry":
                await self._handle_entry(interaction, rest[0] if rest else "")
            elif action == "type_select":
                await self._handle_type_select(interaction)
            elif action == "confirm_proceed":
                await self._handle_confirm_proceed(interaction, rest)
            elif action == "confirm_cancel":
                await self._handle_confirm_cancel(interaction)
            elif action == "manage_summon":
                await self._handle_manage_summon(interaction)
            elif action == "manage_close":
                await self._handle_manage_close(interaction)
            elif action == "summon_select":
                await self._handle_summon_select(interaction)
            elif action == "close_confirm":
                await self._handle_close_confirm(interaction)
            elif action == "close_cancel":
                await self._handle_close_cancel(interaction)
        except Exception as e:
            self.logger.error("处理交互 %s 失败: %s", cid, e, exc_info=True)
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        f"操作失败：{e}", ephemeral=True
                    )
                else:
                    await interaction.edit_original_response(content=f"操作失败：{e}")
            except Exception:
                pass

    # ================= 交互处理器 =================

    async def _handle_entry(self, interaction: discord.Interaction, visibility: str):
        if visibility not in ("private", "public") or not interaction.guild:
            return
        cfg = self.get_config(interaction.guild.id)
        if not cfg.types:
            await interaction.response.send_message("暂无可用的投诉类型。", ephemeral=True)
            return

        view = build_type_select_view(cfg, visibility)
        embed = build_type_select_embed(visibility)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def _handle_type_select(self, interaction: discord.Interaction):
        if not interaction.data or not isinstance(interaction.data, dict) or not interaction.guild:
            return
        values = interaction.data.get("values", [])
        if not values:
            return

        type_id = values[0]
        cfg = self.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在。", ephemeral=True)
            return

        cid = interaction.data.get("custom_id", "")
        visibility = cid.split(":")[-1] if cid else "private"

        modal = ComplaintFormModal(self, type_config, visibility)
        await interaction.response.send_modal(modal)

    async def handle_form_submit(
        self,
        interaction: discord.Interaction,
        *,
        type_config: ComplaintTypeConfig | None,
        visibility: str,
        form_data: dict[str, str],
    ):
        if type_config is None:
            await interaction.response.send_message("内部错误：投诉类型丢失。", ephemeral=True)
            return

        if type_config.requires_confirm:
            self._pending_forms[(interaction.user.id, type_config.id)] = form_data
            embed = build_confirm_embed(type_config)
            view = build_confirm_proceed_view(type_config.id, visibility)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await self._do_create_channel(interaction, type_config, visibility, form_data)

    async def _handle_confirm_proceed(
        self, interaction: discord.Interaction, rest: list[str]
    ):
        if len(rest) < 2 or not interaction.guild:
            await interaction.response.send_message("确认信息格式错误。", ephemeral=True)
            return

        type_id, visibility = rest[0], rest[1]
        cfg = self.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在，请重新提交。", ephemeral=True)
            return

        form_data = self._pending_forms.pop((interaction.user.id, type_id), {})
        await self._do_create_channel(interaction, type_config, visibility, form_data)

    async def _handle_confirm_cancel(self, interaction: discord.Interaction):
        await interaction.response.update_message(
            embed=build_success_embed("已取消提交。"), view=None,
        )

    async def _do_create_channel(
        self,
        interaction: discord.Interaction,
        type_config: ComplaintTypeConfig,
        visibility: str,
        form_data: dict[str, str],
    ):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("无法读取成员信息。", ephemeral=True)
            return

        if interaction.response.is_done():
            await interaction.edit_original_response(content="正在创建投诉频道...")
            followup = interaction.followup
        else:
            await interaction.response.defer(ephemeral=True, thinking=True)
            followup = interaction.followup

        cfg = self.get_config(interaction.guild.id)
        try:
            channel = await create_complaint_channel(
                bot=self.bot,
                guild=interaction.guild,
                complainant=interaction.user,
                type_config=type_config,
                visibility=visibility,
                form_data=form_data,
                full_config=cfg,
            )
        except Exception as e:
            self.logger.error("创建投诉频道失败: %s", e, exc_info=True)
            try:
                await followup.send(f"创建频道失败：{e}", ephemeral=True)
            except Exception:
                pass
            return

        try:
            await followup.send(f"✅ 投诉频道已创建：{channel.mention}", ephemeral=True)
        except Exception:
            pass

    async def _handle_manage_summon(self, interaction: discord.Interaction):
        if not is_admin_check(interaction) or not interaction.guild:
            await interaction.response.send_message("仅管理员可使用此功能。", ephemeral=True)
            return

        cfg = self.get_config(interaction.guild.id)
        view = build_summon_select_view(cfg)
        await interaction.response.send_message(embed=build_summon_embed(), view=view, ephemeral=True)

    async def _handle_manage_close(self, interaction: discord.Interaction):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            return

        meta = parse_topic(interaction.channel.topic)
        if not meta:
            await interaction.response.send_message("该频道不是投诉频道。", ephemeral=True)
            return

        is_admin_user = is_admin_check(interaction)
        is_complainant = interaction.user.id == meta.get("complainant")

        if not is_admin_user and not is_complainant:
            await interaction.response.send_message(
                "仅投诉人或管理员可关闭此频道。", ephemeral=True
            )
            return

        cfg = self.get_config(interaction.guild.id) if interaction.guild else self.get_config(0)
        embed = build_close_confirm_embed(cfg.templates.confirmation_text)
        await interaction.response.send_message(embed=embed, view=CloseConfirmView(), ephemeral=True)

    async def _handle_summon_select(self, interaction: discord.Interaction):
        if not interaction.data or not isinstance(interaction.data, dict):
            return
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        values = interaction.data.get("values", [])
        if not values or values[0] == "none":
            return

        group_id = values[0]
        cfg = self.get_config(interaction.guild.id)
        group = cfg.role_groups.get(group_id)
        if not group:
            await interaction.response.send_message("身份组不存在。", ephemeral=True)
            return

        channel = interaction.channel
        added = []
        for role_id in group.role_ids:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await channel.set_permissions(
                        role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        attach_files=True,
                        reason=f"召唤身份组：{group.label}",
                    )
                    added.append(role.mention)
                except discord.Forbidden:
                    pass

        if added:
            await channel.send(
                f"📢 已召唤 **{group.label}**：{' '.join(added)}",
                allowed_mentions=discord.AllowedMentions(roles=True, everyone=False),
            )

        await interaction.response.edit_message(
            embed=build_success_embed(f"已召唤 {group.label}。"), view=None,
        )

    async def _handle_close_confirm(self, interaction: discord.Interaction):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            return
        if not interaction.guild:
            return

        channel = interaction.channel
        meta = parse_topic(channel.topic)
        if not meta:
            await interaction.response.send_message("该频道不是投诉频道。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id)
        type_config = cfg.get_complaint_type(meta.get("type", ""))
        type_label = type_config.label if type_config else meta.get("type", "未知")
        type_emoji = type_config.emoji if type_config else "📋"
        visibility = "公开" if meta.get("visibility") == "public" else "私密"

        try:
            await self._get_archive_service(guild_id).archive_channel(
                channel,
                type_label=type_label,
                type_emoji=type_emoji,
                complainant_id=meta["complainant"],
                visibility=visibility,
                form_data={},
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"归档失败：{e}")
            )
            return

        try:
            await interaction.edit_original_response(
                embed=build_success_embed("投诉频道已归档并删除。")
            )
        except Exception:
            pass

    async def _handle_close_cancel(self, interaction: discord.Interaction):
        await interaction.response.update_message(
            embed=build_success_embed("已取消关闭操作。"), view=None,
        )


async def setup(bot):
    await bot.add_cog(ComplaintCog(bot))
