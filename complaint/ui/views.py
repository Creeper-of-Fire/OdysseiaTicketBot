from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

from complaint.config.models import ComplaintConfig
from complaint.services.channel_service import (
    get_type_target_role_ids,
    parse_ticket_from_name,
    transfer_complaint_channel,
)
from complaint.ui.embeds import (
    build_archive_confirm_embed,
    build_archive_success_embed,
    build_error_embed,
    build_success_embed,
    build_summon_embed,
    build_summon_user_embed,
    build_type_select_embed,
)
from complaint.ui.modals import ComplaintFormModal
from utility.permison import is_admin_check

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog

logger = logging.getLogger(__name__)


def _format_type_name(type_config) -> str:
    """格式化投诉类型显示名。"""
    if type_config is None:
        return "未知类型"
    prefix = f"{type_config.emoji} " if type_config.emoji else ""
    return f"{prefix}{type_config.label}"


def _is_current_handler(interaction: discord.Interaction, cog: "ComplaintCog") -> bool:
    """检查用户是否属于当前工单类型的处理组。"""
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    if not isinstance(interaction.channel, discord.TextChannel):
        return False

    meta = cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
    if meta is None:
        return False

    cfg = cog.get_config(interaction.guild.id)
    current_type = cfg.get_complaint_type(meta.type_id)
    current_role_ids = set(get_type_target_role_ids(cfg, current_type))
    if not current_role_ids:
        return False

    user_role_ids = {role.id for role in interaction.user.roles}
    return not user_role_ids.isdisjoint(current_role_ids)


# ===== 入口面板 =====

class EntryView(discord.ui.View):
    """入口面板的持久化 View。"""

    def __init__(self, cog: ComplaintCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🔒 提交投诉",
        style=discord.ButtonStyle.primary,
        custom_id="complaint:entry",
        row=0,
    )
    async def _btn_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return
        cfg = self.cog.get_config(interaction.guild.id)
        if not cfg.types:
            await interaction.response.send_message("暂无可用的投诉类型。", ephemeral=True)
            return

        view = TypeSelectView(self.cog, cfg)
        await interaction.response.send_message(
            embed=build_type_select_embed(cfg), view=view, ephemeral=True,
        )


# ===== 类型选择 =====

class TypeSelectView(discord.ui.View):
    """投诉类型选择面板，选完后需确认才弹出表单。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig):
        super().__init__(timeout=120)
        self.cog = cog
        self._config = config

        options = [
            discord.SelectOption(
                label=ct.label,
                description=ct.description[:100] if ct.description else None,
                value=ct.id,
                emoji=ct.emoji or None,
            )
            for ct in config.types
        ]

        self._select = discord.ui.Select(
            placeholder="选择投诉类型...",
            options=options,
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        type_id = self._select.values[0]

        self._select.placeholder = "重新选择"
        for opt in self._select.options:
            opt.default = (opt.value == type_id)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.style == discord.ButtonStyle.success:
                child.disabled = False
                break

        cfg = self.cog.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在。", ephemeral=True)
            return

        group_labels = []
        for gid in type_config.target_role_groups:
            group = cfg.role_groups.get(gid)
            if group:
                group_labels.append(group.label)
        groups_text = "、".join(group_labels) if group_labels else "无"

        detail = type_config.description
        if type_config.detail_description:
            detail += f"\n\n{type_config.detail_description}"

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"{type_config.emoji} {type_config.label}",
                description=(
                    f"{detail}\n\n"
                    f"**可见管理组**：{groups_text}\n\n"
                    "点击 **确认** 开始填写投诉表单。"
                ),
                color=0xFEE75C,
            ),
            view=self,
        )

    @discord.ui.button(label="✅ 确认", style=discord.ButtonStyle.success, row=1, disabled=True)
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return
        type_id = self._select.values[0] if self._select.values else None
        if not type_id:
            await interaction.response.edit_message(view=None)
            return

        cfg = self.cog.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在，请重新选择。", ephemeral=True)
            return

        modal = ComplaintFormModal(self.cog, type_config)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary, row=1)
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消选择。"), view=None,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger.error("TypeSelectView 交互错误 (item=%s): %s", item, error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("操作出错，请重试。", ephemeral=True)
            else:
                await interaction.edit_original_response(
                    embed=build_error_embed(f"操作出错：{error}"), view=None,
                )
        except Exception:
            logger.error("TypeSelectView 无法回复交互", exc_info=True)


# ===== 管理面板 =====

class ManagePanelView(discord.ui.View):
    """频道管理面板的持久化 View。"""

    def __init__(self, cog: ComplaintCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="📢 召唤身份组",
        style=discord.ButtonStyle.primary,
        custom_id="complaint:manage_summon",
        row=0,
    )
    async def _btn_summon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_check(interaction) or not interaction.guild:
            await interaction.response.send_message("仅管理员可使用此功能。", ephemeral=True)
            return

        cfg = self.cog.get_config(interaction.guild.id)
        view = SummonSelectView(self.cog, cfg, interaction.guild)
        await interaction.response.send_message(
            embed=build_summon_embed(), view=view, ephemeral=True,
        )

    @discord.ui.button(
        label="👤 召唤用户",
        style=discord.ButtonStyle.primary,
        custom_id="complaint:manage_summon_user",
        row=0,
    )
    async def _btn_summon_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin_check(interaction) or not interaction.guild:
            await interaction.response.send_message("仅管理员可使用此功能。", ephemeral=True)
            return

        view = SummonUserSelectView(self.cog)
        await interaction.response.send_message(
            embed=build_summon_user_embed(), view=view, ephemeral=True,
        )

    @discord.ui.button(
        label="🔀 转接工单",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:manage_transfer",
        row=0,
    )
    async def _btn_transfer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在投诉频道中使用。", ephemeral=True)
            return

        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        if meta is None:
            await interaction.response.send_message("当前频道不是投诉频道。", ephemeral=True)
            return

        if not is_admin_check(interaction) and not _is_current_handler(interaction, self.cog):
            await interaction.response.send_message(
                "仅当前处理组成员或管理组可转接工单。",
                ephemeral=True,
            )
            return

        cfg = self.cog.get_config(interaction.guild.id)
        current_type = cfg.get_complaint_type(meta.type_id)
        view = TransferTypeSelectView(self.cog, cfg, meta.type_id)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔀 转接工单",
                description=(
                    f"当前工单类型：**{_format_type_name(current_type)}**\n\n"
                    "请选择要转接到的投诉类型。\n"
                    "转接后将移除旧处理组权限，并授予新处理组权限。"
                ),
                color=0xFEE75C,
            ),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(
        label="🗑️ 关闭频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:manage_close",
        row=0,
    )
    async def _btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在文本频道内使用。", ephemeral=True)
            return

        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        is_admin_user = is_admin_check(interaction)
        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        is_complainant = meta is not None and interaction.user.id == meta.complainant_id

        if not is_admin_user and not is_complainant:
            await interaction.response.send_message(
                "仅投诉人或管理员可关闭此频道。", ephemeral=True,
            )
            return
        cfg = self.cog.get_config(interaction.guild.id)
        await interaction.response.send_message(
            embed=build_archive_confirm_embed(
                operator_mention=interaction.user.mention,
            ),
            view=ArchiveConfirmView(self.cog),
            ephemeral=False,
        )


# ===== 召唤选择 =====

class SummonSelectView(discord.ui.View):
    """召唤身份组的两步确认面板。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig, guild: discord.Guild):
        super().__init__(timeout=60)
        self.cog = cog

        options = []
        for group_id, rg in config.role_groups.items():
            if not rg.role_ids:
                continue
            role_names = []
            for rid in rg.role_ids:
                role = guild.get_role(rid)
                role_names.append(role.name if role else f"（未知角色 {rid}）")
            desc = "、".join(role_names)
            options.append(discord.SelectOption(
                label=rg.label,
                value=group_id,
                description=desc[:100],
            ))

        self._select = discord.ui.Select(
            placeholder="选择要召唤的身份组...",
            options=options or [discord.SelectOption(label="（无可用身份组）", value="none")],
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.edit_message(view=None)
            return

        values = self._select.values
        if not values or values[0] == "none":
            await interaction.response.edit_message(view=None)
            return

        group_id = values[0]
        cfg = self.cog.get_config(interaction.guild.id)
        group = cfg.role_groups.get(group_id)
        if not group:
            await interaction.response.send_message("身份组不存在。", ephemeral=True)
            return

        role_lines = []
        for rid in group.role_ids:
            role = interaction.guild.get_role(rid)
            role_lines.append(f"- {role.mention}" if role else f"- ~~未知角色 <@&{rid}>~~")
        roles_text = "\n".join(role_lines)

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"📢 召唤 **{group.label}**",
                description=(
                    f"以下角色将被添加到频道并发送通知：\n\n"
                    f"{roles_text}\n\n"
                    "点击 **确认召唤** 完成操作。"
                ),
                color=0xFEE75C,
            ),
            view=self,
        )

    @discord.ui.button(label="✅ 确认召唤", style=discord.ButtonStyle.success, row=1)
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.edit_message(view=None)
            return

        values = self._select.values
        if not values or values[0] == "none":
            await interaction.response.edit_message(view=None)
            return

        group_id = values[0]
        cfg = self.cog.get_config(interaction.guild.id)
        group = cfg.role_groups.get(group_id)
        if not group:
            await interaction.response.send_message("身份组不存在。", ephemeral=True)
            return

        await interaction.response.defer()

        channel = interaction.channel
        added = []
        skipped_missing = []
        skipped_forbidden = []
        for role_id in group.role_ids:
            role = interaction.guild.get_role(role_id)
            if not role:
                skipped_missing.append(f"<@&{role_id}>")
                continue
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
                skipped_forbidden.append(role.mention)

        if skipped_missing:
            logger.warning("召唤身份组 %s 时以下角色不存在: %s", group.label, skipped_missing)
        if skipped_forbidden:
            logger.warning("召唤身份组 %s 时以下角色权限不足: %s", group.label, skipped_forbidden)

        if added:
            role_names = []
            for role_id in group.role_ids:
                role = interaction.guild.get_role(role_id)
                if role:
                    role_names.append(role.name)
            await channel.send(
                f"📢 **{group.label}** 已获权访问本频道（{', '.join(role_names)}）",
                allowed_mentions=discord.AllowedMentions.none(),
            )

        parts = []
        if added:
            parts.append(f"已成功召唤 {len(added)} 个角色。")
        if skipped_missing:
            parts.append(f"{len(skipped_missing)} 个角色已不存在。")
        if skipped_forbidden:
            parts.append(f"{len(skipped_forbidden)} 个角色因权限不足跳过。")

        if not parts:
            parts.append("身份组中没有可用的角色。")

        await interaction.edit_original_response(
            embed=build_success_embed("".join(parts)) if added else build_error_embed("".join(parts)),
            view=None,
        )

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary, row=1)
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消召唤身份组。"), view=None,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger.error("SummonSelectView 交互错误 (item=%s): %s", item, error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("操作出错，请重试。", ephemeral=True)
            else:
                await interaction.edit_original_response(
                    embed=build_error_embed(f"操作出错：{error}"), view=None,
                )
        except Exception:
            logger.error("SummonSelectView 无法回复交互", exc_info=True)


# ===== 召唤用户 =====

class SummonUserSelectView(discord.ui.View):
    """召唤用户的两步确认面板：先选人，再点确认。"""

    def __init__(self, cog: ComplaintCog):
        super().__init__(timeout=60)
        self.cog = cog

        self._select = discord.ui.UserSelect(
            placeholder="选择要召唤的用户...",
            max_values=10,
            row=0,
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        lines = [f"{u.mention} ({u.name})" for u in self._select.values]
        names = "\n".join(lines)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="👤 召唤用户",
                description=f"已选择：{names}\n\n点击 **确认召唤** 完成操作。",
                color=0x5865F2,
            ),
            view=self,
        )

    @discord.ui.button(
        label="✅ 确认召唤",
        style=discord.ButtonStyle.success,
        row=1,
    )
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.edit_message(view=None)
            return

        await interaction.response.defer()

        channel = interaction.channel
        added = []
        skipped = []

        for user in self._select.values:
            member = interaction.guild.get_member(user.id)
            if not member:
                skipped.append(f"<@{user.id}>")
                continue

            try:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    reason=f"召唤用户：{member}",
                )
                added.append(member.mention)
            except discord.Forbidden:
                skipped.append(member.mention)

        if skipped:
            logger.warning("召唤用户时以下用户处理失败: %s", skipped)

        if added:
            await channel.send(
                f"👤 已召唤用户：{' '.join(added)}",
                allowed_mentions=discord.AllowedMentions(users=True, everyone=False),
            )

        parts = []
        if added:
            parts.append(f"已成功召唤 {len(added)} 位用户。")
        if skipped:
            parts.append(f"{len(skipped)} 位用户处理失败。")
        if not parts:
            parts.append("未选择任何用户。")

        await interaction.edit_original_response(
            embed=build_success_embed("".join(parts)) if added else build_error_embed("".join(parts)),
            view=None,
        )

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消召唤用户。"), view=None,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger.error("SummonUserSelectView 交互错误 (item=%s): %s", item, error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("操作出错，请重试。", ephemeral=True)
            else:
                await interaction.edit_original_response(
                    embed=build_error_embed(f"操作出错：{error}"), view=None,
                )
        except Exception:
            logger.error("SummonUserSelectView 无法回复交互", exc_info=True)


# ===== 转接工单 =====

class TransferTypeSelectView(discord.ui.View):
    """将当前投诉频道转接到其他投诉类型。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig, current_type_id: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.current_type_id = current_type_id

        options = [
            discord.SelectOption(
                label=ct.label,
                value=ct.id,
                description=ct.description[:100] if ct.description else None,
                emoji=ct.emoji or None,
            )
            for ct in config.types
            if ct.id != current_type_id
        ]
        self._select = discord.ui.Select(
            placeholder="选择转接目标类型...",
            options=options or [discord.SelectOption(label="（无可转接类型）", value="none")],
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.edit_message(view=None)
            return

        selected = self._select.values[0] if self._select.values else None
        if not selected or selected == "none":
            await interaction.response.edit_message(view=None)
            return

        cfg = self.cog.get_config(interaction.guild.id)
        target_type = cfg.get_complaint_type(selected)
        if target_type is None:
            await interaction.response.send_message("目标投诉类型不存在。", ephemeral=True)
            return

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="🔀 确认转接工单",
                description=(
                    f"将当前工单转接到：**{_format_type_name(target_type)}**\n\n"
                    "确认后会移除旧处理组权限，并将新处理组加入当前频道。"
                ),
                color=0xFEE75C,
            ),
            view=self,
        )

    @discord.ui.button(label="✅ 确认转接", style=discord.ButtonStyle.success, row=1)
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.edit_message(view=None)
            return

        selected = self._select.values[0] if self._select.values else None
        if not selected or selected == "none":
            await interaction.response.edit_message(view=None)
            return

        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        if meta is None:
            await interaction.response.send_message("当前频道不是投诉频道。", ephemeral=True)
            return

        if not is_admin_check(interaction) and not _is_current_handler(interaction, self.cog):
            await interaction.response.send_message(
                "仅当前处理组成员或管理组可转接工单。",
                ephemeral=True,
            )
            return

        cfg = self.cog.get_config(interaction.guild.id)
        current_type = cfg.get_complaint_type(meta.type_id)

        await interaction.response.defer()
        try:
            old_type, new_type = await transfer_complaint_channel(
                cog=self.cog,
                guild=interaction.guild,
                channel=interaction.channel,
                operator=interaction.user,
                full_config=cfg,
                new_type_id=selected,
            )
        except RuntimeError as error:
            await interaction.edit_original_response(
                embed=build_error_embed(str(error)),
                view=None,
            )
            return
        except discord.Forbidden:
            await interaction.edit_original_response(
                embed=build_error_embed("机器人权限不足，无法调整频道权限。"),
                view=None,
            )
            return
        except Exception as error:
            logger.error("转接工单失败: %s", error, exc_info=error)
            await interaction.edit_original_response(
                embed=build_error_embed(f"转接失败：{error}"),
                view=None,
            )
            return

        operator_name = getattr(interaction.user, "display_name", interaction.user.name)
        await interaction.channel.send(
            f"🔀 工单已由 **{operator_name}** 从 **{_format_type_name(old_type or current_type)}** "
            f"转接为 **{_format_type_name(new_type)}**。",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.edit_original_response(
            embed=build_success_embed(
                f"已将工单从 **{_format_type_name(old_type or current_type)}** "
                f"转接为 **{_format_type_name(new_type)}**。"
            ),
            view=None,
        )

    @discord.ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary, row=1)
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消转接工单。"),
            view=None,
        )

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item,
    ) -> None:
        logger.error("TransferTypeSelectView 交互错误 (item=%s): %s", item, error, exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("操作出错，请重试。", ephemeral=True)
            else:
                await interaction.edit_original_response(
                    embed=build_error_embed(f"操作出错：{error}"),
                    view=None,
                )
        except Exception:
            logger.error("TransferTypeSelectView 无法回复交互", exc_info=True)


# ===== 二次确认（表单提交前）=====

class ConfirmProceedView(discord.ui.View):
    """表单提交前的二次确认面板。"""

    def __init__(self, cog: ComplaintCog, type_id: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.type_id = type_id

    @discord.ui.button(
        label="✅ 确认提交",
        style=discord.ButtonStyle.success,
        custom_id="complaint:confirm_proceed",
        row=0,
    )
    async def _btn_proceed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            await interaction.response.send_message("请在服务器内使用。", ephemeral=True)
            return

        cfg = self.cog.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(self.type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在，请重新提交。", ephemeral=True)
            return

        form_data = self.cog._pending_forms.pop((interaction.user.id, self.type_id), {})
        await self.cog._do_create_channel(interaction, type_config, form_data)

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:confirm_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消提交。"), view=None,
        )


# ===== 归档确认 =====

class ArchiveConfirmView(discord.ui.View):
    """归档确认的持久化 View。"""

    def __init__(self, cog: ComplaintCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="📦 归档频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:archive_confirm",
        row=0,
    )
    async def _btn_archive(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在服务器文本频道内使用。", ephemeral=True)
            return

        channel = interaction.channel
        is_admin_user = is_admin_check(interaction)
        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, channel.id)
        is_complainant = meta is not None and interaction.user.id == meta.complainant_id

        if not is_admin_user and not is_complainant:
            await interaction.response.send_message("仅投诉人或管理员可执行此操作。", ephemeral=True)
            return

        await interaction.response.defer()

        guild_id = interaction.guild.id
        cfg = self.cog.get_config(guild_id)
        tmpl = cfg.templates

        type_config = cfg.get_complaint_type(meta.type_id) if meta else None
        type_label = type_config.label if type_config else tmpl.unknown_type_label
        type_emoji = type_config.emoji if type_config else tmpl.fallback_emoji
        complainant_id = meta.complainant_id if meta else 0
        ticket_number = parse_ticket_from_name(channel.name)

        try:
            archive_url = await self.cog._get_archive_service(guild_id).generate_and_send_archive(
                channel,
                type_label=type_label,
                type_emoji=type_emoji,
                complainant_id=complainant_id,
                form_data={},
                ticket_number=ticket_number,
                operator=interaction.user,
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"归档失败：{e}"),
            )
            return

        try:
            await interaction.edit_original_response(
                embed=build_archive_success_embed(archive_url),
                view=DeleteChannelView(self.cog),
            )
        except Exception:
            logger.warning("归档成功 (%s)，但更新交互消息失败", archive_url)

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:archive_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消归档操作。"), view=None,
        )


# ===== 删除频道（持久化）=====

class DeleteChannelView(discord.ui.View):
    """归档后删除频道的持久化 View。"""

    def __init__(self, cog: ComplaintCog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="🗑️ 删除频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:archive_delete",
        row=0,
    )
    async def _btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("请在服务器文本频道内使用。", ephemeral=True)
            return

        is_admin_user = is_admin_check(interaction)
        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        is_complainant = meta is not None and interaction.user.id == meta.complainant_id

        if not is_admin_user and not is_complainant:
            await interaction.response.send_message(
                "仅投诉人或管理员可删除此频道。", ephemeral=True,
            )
            return

        await interaction.response.edit_message(
            view=DeleteConfirmView(self.cog, interaction.channel),
        )

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:archive_delete_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            embed=build_success_embed("已取消删除操作。"), view=None,
        )


# ===== 删除确认 =====

class DeleteConfirmView(discord.ui.View):
    """删除频道的倒计时确认面板，5 秒后自动执行删除。"""

    def __init__(self, cog: ComplaintCog, channel: discord.TextChannel):
        super().__init__(timeout=60)
        self.cog = cog
        self.channel = channel
        self._cancelled = asyncio.Event()

    @discord.ui.button(
        label="✅ 确认删除频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:delete_confirm",
        row=0,
    )
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.remove_item(button)
        countdown = 5
        await interaction.response.edit_message(
            embed=build_success_embed(f"频道将在 {countdown} 秒后删除..."),
            view=self,
        )

        for i in range(countdown - 1, 0, -1):
            await asyncio.sleep(1)
            if self._cancelled.is_set():
                return
            try:
                await interaction.edit_original_response(
                    embed=build_success_embed(f"频道将在 {i} 秒后删除..."),
                )
            except Exception:
                logger.warning("删除倒计时更新消息失败 (channel=%s)", self.channel.id)
                return

        await asyncio.sleep(1)
        if self._cancelled.is_set():
            return
        try:
            guild_id = self.channel.guild.id
            channel_id = self.channel.id
            await self.channel.delete(reason="投诉频道已归档 - 手动删除")
            self.cog.channel_manager.remove_channel(guild_id, channel_id)
            await self.cog.channel_manager.save_data()
        except Exception as e:
            logger.error("删除频道 %s 失败: %s", self.channel.id, e, exc_info=True)
            try:
                await interaction.edit_original_response(
                    embed=build_error_embed(f"删除频道失败：{e}"),
                )
            except Exception:
                logger.warning("删除频道失败且无法通知用户 (channel=%s)", self.channel.id)

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:delete_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._cancelled.set()
        await interaction.response.edit_message(
            embed=build_success_embed("已取消删除操作。"),
            view=DeleteChannelView(self.cog),
        )
