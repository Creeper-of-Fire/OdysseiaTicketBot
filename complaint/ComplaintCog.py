from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

import config
from utility.feature_cog import FeatureCog
from utility.helpers import try_get_member
from utility.message import resolve_sendable, send_message
from utility.permison import is_admin

from .config.loader import load_config, read_raw_config, save_config, validate_and_save
from .config.models import ComplaintConfig, ComplaintTypeConfig
from .services.archive_service import ComplaintArchiveService
from .services.channel_meta import ComplaintChannelManager
from .services.channel_service import create_complaint_channel, render_notify_message, ticket_display
from .services.counter_service import TicketCounterService
from .ui.embeds import (
    build_archive_confirm_embed,
    build_confirm_embed,
    build_entry_embed,
    build_error_embed,
    build_manage_panel_embed,
    build_notify_embed,
    build_success_embed,
)
from .ui.modals import ComplaintFormModal
from .ui.views import ArchiveConfirmView, ConfirmProceedView, DeleteChannelView, EntryView, ManagePanelView

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
        self._counter_service = TicketCounterService()
        self.channel_manager = ComplaintChannelManager.get_instance()
        bot.add_view(EntryView(self))
        bot.add_view(ArchiveConfirmView(self))
        bot.add_view(DeleteChannelView(self))
        bot.add_view(ManagePanelView(self))
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
        """按 guild_id 获取归档服务实例（依赖配置缓存）。"""
        self.get_config(guild_id)
        return self._archive_services[guild_id]

    # ================= 斜杠命令 =================

    complaint_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨投诉管理",
        description="投诉系统管理命令",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_roles=True),
    )

    @complaint_group.command(name="发布入口面板", description="在当前频道发布投诉入口面板")
    @is_admin()
    async def cmd_post_entry(self, interaction: discord.Interaction):
        target = interaction.channel
        if target is None:
            await interaction.response.send_message("无法定位当前频道。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await send_message(target, embed=build_entry_embed(), view=EntryView(self))
        except discord.Forbidden:
            await interaction.edit_original_response(
                content="没有权限在当前频道发送消息。"
            )
            return
        except Exception as e:
            await interaction.edit_original_response(content=f"发布失败：{e}")
            return

        mention = target.mention if hasattr(target, "mention") else target.name
        await interaction.edit_original_response(
            content=f"已在 {mention} 发布投诉入口面板。"
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
            cfg = self.get_config(guild_id)
            save_config(cfg, guild_id)
            raw = read_raw_config(guild_id)

        manual_path = Path(__file__).resolve().parent.parent / "docs" / "投诉系统使用手册.md"
        files = [
            discord.File(
                fp=__import__("io").BytesIO(raw),
                filename=f"complaint_{guild_id}.toml",
            ),
        ]
        if manual_path.is_file():
            files.append(discord.File(fp=manual_path, filename=manual_path.name))

        await interaction.response.send_message(
            "📎 当前服务器的投诉配置文件（附使用手册）：",
            files=files,
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

        from .config.loader import config_path
        path = config_path(interaction.guild.id)
        if path.exists() and len(path.read_text("utf-8")) > 4000:
            await interaction.response.send_message(
                "⚠️ 配置文件超过 4000 字符，无法在弹窗中编辑。\n"
                "请使用 **下载配置** 导出文件，本地编辑后再通过 **上传配置** 提交。",
                ephemeral=True,
            )
            return

        from .ui.modals import AdminEditTemplateModal
        modal = AdminEditTemplateModal(self, interaction.guild.id)
        await interaction.response.send_modal(modal)

    @complaint_group.command(name="重发管理面板", description="在当前投诉频道重新发送管理面板")
    @is_admin()
    async def cmd_resend_panel(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在服务器频道内使用。", ephemeral=True)
            return

        meta = self.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        if meta is None:
            await interaction.response.send_message("当前频道不是投诉频道。", ephemeral=True)
            return

        manage_view = ManagePanelView(self)
        await send_message(
            interaction.channel,
            embed=build_manage_panel_embed(),
            view=manage_view,
        )
        self.bot.add_view(manage_view)
        await interaction.response.send_message("✅ 管理面板已重新发送。", ephemeral=True)

    @complaint_group.command(name="强制归档", description="在当前投诉频道发起归档")
    @is_admin()
    async def cmd_force_archive(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在服务器频道内使用。", ephemeral=True)
            return

        channel = interaction.channel
        cfg = self.get_config(interaction.guild.id)
        if channel.category_id not in cfg.get_all_category_ids():
            await interaction.response.send_message("该频道不在投诉分类下，无法归档。", ephemeral=True)
            return

        await interaction.response.send_message(
            embed=build_archive_confirm_embed(
                operator_mention=interaction.user.mention,
            ),
            view=ArchiveConfirmView(self),
        )

    @complaint_group.command(name="召唤", description="通过用户ID或@提及召唤用户到当前投诉频道")
    @app_commands.rename(用户="用户标识")
    @app_commands.describe(用户="用户ID、@提及，或逗号分隔的多个标识")
    @is_admin()
    async def cmd_summon(self, interaction: discord.Interaction, 用户: str):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在服务器频道内使用。", ephemeral=True)
            return

        meta = self.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        if meta is None:
            await interaction.response.send_message("当前频道不是投诉频道。", ephemeral=True)
            return

        raw_parts = [s.strip() for s in 用户.replace("，", ",").split(",") if s.strip()]
        parsed_ids: list[int] = []
        invalid: list[str] = []

        for raw in raw_parts:
            m = re.match(r"^<@!?(\d+)>$", raw)
            if m:
                parsed_ids.append(int(m.group(1)))
            elif raw.isdigit():
                parsed_ids.append(int(raw))
            else:
                invalid.append(raw)

        if not parsed_ids:
            msg = f"未识别到有效的用户ID。无法解析：{', '.join(invalid)}" if invalid else "未提供任何用户标识。"
            await interaction.response.send_message(msg, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = interaction.channel
        guild = interaction.guild
        added: list[str] = []
        skipped: list[str] = []

        for uid in parsed_ids:
            member = await try_get_member(guild, uid)
            if not member:
                skipped.append(f"`{uid}`（未找到）")
                continue

            try:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason=f"召唤用户：{member}（by {interaction.user}）",
                )
                added.append(member.mention)
            except discord.Forbidden:
                skipped.append(f"{member.mention}（权限不足）")

        if added:
            await send_message(
                channel,
                content=f"👤 已召唤用户：{' '.join(added)}",
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False),
            )

        parts: list[str] = []
        if added:
            parts.append(f"✅ 已成功召唤 {len(added)} 位用户。")
        if skipped:
            parts.append(f"⚠️ {len(skipped)} 位处理失败：{', '.join(skipped)}")
        if invalid:
            parts.append(f"❌ 无法解析：{', '.join(invalid)}")

        text = "\n".join(parts)
        await interaction.edit_original_response(
            embed=build_success_embed(text) if added else build_error_embed(text),
        )

    # ================= 表单 & 频道创建 =================

    async def handle_form_submit(
        self,
        interaction: discord.Interaction,
        *,
        type_config: ComplaintTypeConfig | None,
        form_data: dict[str, str],
    ) -> None:
        """处理表单提交：需要确认的类型走确认流程，否则直接创建频道。"""
        if type_config is None:
            await interaction.response.send_message("内部错误：投诉类型丢失。", ephemeral=True)
            return

        if type_config.requires_confirm:
            self._pending_forms[(interaction.user.id, type_config.id)] = form_data
            embed = build_confirm_embed(type_config)
            view = ConfirmProceedView(self, type_config.id, interaction.user.id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        else:
            await self._do_create_channel(interaction, type_config, form_data)

    async def _do_create_channel(
        self,
        interaction: discord.Interaction,
        type_config: ComplaintTypeConfig,
        form_data: dict[str, str],
    ) -> None:
        """执行投诉频道创建：分配工单编号、创建频道、发送初始消息。"""
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

        # --- 获取 ticket 编号 ---
        archive_channel_id = cfg.guild.archive_channel_id
        if not archive_channel_id:
            await followup.send("未配置归档频道，请先使用 /投诉管理 配置服务器。", ephemeral=True)
            return

        archive_channel = await resolve_sendable(
            self.bot, interaction.guild, archive_channel_id,
        )
        if archive_channel is None:
            await followup.send("归档频道不可用，请检查配置。", ephemeral=True)
            return

        try:
            ticket_number = await self._counter_service.get_next_number(
                interaction.guild.id, archive_channel,
            )
        except RuntimeError as e:
            await followup.send(str(e), ephemeral=True)
            return

        # --- 创建频道 ---
        try:
            channel = await create_complaint_channel(
                cog=self,
                guild=interaction.guild,
                complainant=interaction.user,
                type_config=type_config,
                form_data=form_data,
                full_config=cfg,
                ticket_number=ticket_number,
            )
        except Exception as e:
            self.logger.error("创建投诉频道失败: %s", e, exc_info=True)
            try:
                await followup.send(f"创建频道失败：{e}", ephemeral=True)
            except Exception:
                pass
            return

        # --- 发送通知 ---
        if type_config.notify_channel_id and type_config.notify_message:
            try:
                await self._send_creation_notify(
                    guild=interaction.guild,
                    type_config=type_config,
                    full_config=cfg,
                    ticket_number=ticket_number,
                    complainant=interaction.user,
                    channel=channel,
                )
            except Exception:
                self.logger.warning("工单 %s 通知发送失败", ticket_number, exc_info=True)

        try:
            await followup.send(
                f"✅ 投诉频道已创建：{channel.mention}（{ticket_display(ticket_number)}）",
                ephemeral=True,
            )
        except Exception:
            self.logger.warning("投诉频道 %s 已创建，但通知用户失败", channel.id)

    async def _send_creation_notify(
        self,
        *,
        guild: discord.Guild,
        type_config: ComplaintTypeConfig,
        full_config: ComplaintConfig,
        ticket_number: int,
        complainant: discord.Member,
        channel: discord.TextChannel,
    ) -> None:
        """工单创建后向配置的频道/帖子发送通知。"""
        target = self.bot.get_channel(type_config.notify_channel_id)
        if target is None:
            try:
                target = await guild.fetch_channel(type_config.notify_channel_id)
            except Exception:
                target = None
        if not isinstance(target, (discord.TextChannel, discord.Thread)):
            self.logger.warning("通知目标频道 %s 不存在或类型不符", type_config.notify_channel_id)
            return

        rendered = render_notify_message(
            notify_message=type_config.notify_message,
            full_config=full_config,
            guild=guild,
            type_config=type_config,
            ticket_number=ticket_number,
            complainant=complainant,
            channel=channel,
        )
        embed = build_notify_embed(
            type_label=type_config.label,
            type_emoji=type_config.emoji,
            ticket_number=ticket_number,
            channel_mention=channel.mention,
            complainant_name=complainant.display_name,
        )
        await send_message(
            target,
            content=rendered,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
        )


async def setup(bot):
    await bot.add_cog(ComplaintCog(bot))
