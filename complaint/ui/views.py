from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import discord

from complaint.config.models import ComplaintConfig
from complaint.services.channel_service import (
    parse_ticket_from_name,
    render_notify_message,
    transfer_complaint_channel,
)
from complaint.ui.embeds import (
    build_archive_confirm_embed,
    build_archive_success_embed,
    build_error_embed,
    build_notify_embed,
    build_success_embed,
    build_summon_embed,
    build_summon_user_embed,
    build_type_select_embed,
)
from complaint.ui.modals import ComplaintFormModal
from utility.helpers import try_get_member
from utility.message import send_message
from utility.paginated_view import PaginatedView
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
    current_role_ids = set(cfg.get_type_target_role_ids(current_type))
    if not current_role_ids:
        return False

    user_role_ids = {role.id for role in interaction.user.roles}
    return not user_role_ids.isdisjoint(current_role_ids)


def _can_create_type(interaction: discord.Interaction, type_config) -> bool:
    """【PR1新增】检查用户是否可创建该类型工单（creator_role_ids 限制）。"""
    if not type_config or not type_config.creator_role_ids:
        return True  # 未配置限制 = 所有人可创建
    if not isinstance(interaction.user, discord.Member):
        return False
    user_role_ids = {role.id for role in interaction.user.roles}
    return not user_role_ids.isdisjoint(set(type_config.creator_role_ids))


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
        await view.start(interaction, ephemeral=True)


# ===== 类型选择 =====

class TypeSelectView(PaginatedView):
    """投诉类型选择面板，选完后需确认才弹出表单。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig):
        super().__init__(
            all_items_provider=lambda: config.types,
            items_per_page=25,
            timeout=120,
        )
        self.cog = cog
        self._config = config
        self._selected_type_id: str | None = None
        # 【PR1新增】当前用户可用的身份组集合，start 时记录，用于 creator_role_ids 过滤
        self._creation_allowed_ids: set[int] | None = None

    async def start(self, interaction: discord.Interaction, **kwargs):
        """【PR1新增】重写 start 以捕获创建者角色集合。"""
        if (
            isinstance(interaction.user, discord.Member)
            and interaction.guild is not None
        ):
            self._creation_allowed_ids = {role.id for role in interaction.user.roles}
        else:
            self._creation_allowed_ids = None
        await super().start(interaction, **kwargs)

    async def _rebuild_view(self):
        self.clear_items()
        # 【PR1新增】creator_role_ids 过滤：仅显示当前用户可创建的类型
        allowed_ids = self._creation_allowed_ids
        page_items = [
            ct for ct in self.get_page_items()
            if not getattr(ct, "creator_role_ids", None)
            or allowed_ids is None
            or not allowed_ids.isdisjoint(set(ct.creator_role_ids))
        ]

        # 类型选择下拉框
        if page_items:
            options = [
                discord.SelectOption(
                    label=ct.label,
                    description=ct.description[:100] if ct.description else None,
                    value=ct.id,
                    emoji=ct.emoji or None,
                    default=(ct.id == self._selected_type_id),
                )
                for ct in page_items
            ]
            self._select = discord.ui.Select(
                placeholder="重新选择" if self._selected_type_id else "选择投诉类型...",
                options=options,
            )
            self._select.callback = self._on_select
            self.add_item(self._select)

        # 确认按钮
        confirm_btn = discord.ui.Button(
            label="✅ 确认", style=discord.ButtonStyle.success, row=1,
            disabled=not self._selected_type_id,
        )
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        # 取消按钮
        cancel_btn = discord.ui.Button(
            label="❌ 取消", style=discord.ButtonStyle.secondary, row=1,
        )
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

        self._add_pagination_buttons(row=2)

        # Embed
        if self._selected_type_id:
            type_config = self._config.get_complaint_type(self._selected_type_id)
            if type_config:
                group_labels = []
                for gid in type_config.target_role_groups:
                    group = self._config.role_groups.get(gid)
                    if group:
                        group_labels.append(group.label)
                groups_text = "、".join(group_labels) if group_labels else "无"
                detail = type_config.description
                if type_config.detail_description:
                    detail += f"\n\n{type_config.detail_description}"
                self.embed = discord.Embed(
                    title=f"{type_config.emoji} {type_config.label}",
                    description=(
                        f"{detail}\n\n"
                        f"**可见管理组**：{groups_text}\n\n"
                        "点击 **确认** 开始填写投诉表单。"
                    ),
                    color=0xFEE75C,
                )
                return
        self.embed = build_type_select_embed(self._config)

    async def _on_select(self, interaction: discord.Interaction):
        if self._select.values:
            self._selected_type_id = self._select.values[0]
        await self.update_view(interaction)

    async def _on_confirm(self, interaction: discord.Interaction):
        if not interaction.guild:
            return
        if not self._selected_type_id:
            await interaction.response.edit_message(view=None)
            return
        cfg = self.cog.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(self._selected_type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在，请重新选择。", ephemeral=True)
            return
        # 【PR1新增】creator_role_ids 二次校验（防止下拉选项过期后越权提交）
        if not _can_create_type(interaction, type_config):
            await interaction.response.send_message(
                "你没有权限创建该类型的工单。", ephemeral=True,
            )
            return
        modal = ComplaintFormModal(self.cog, type_config)
        await interaction.response.send_modal(modal)

    async def _on_cancel(self, interaction: discord.Interaction):
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
        await view.start(interaction, ephemeral=True)

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
        view = TransferTypeSelectView(self.cog, cfg, meta.type_id, interaction.guild)
        await view.start(interaction, ephemeral=True)

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

        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, interaction.channel.id)
        if meta is None:
            await interaction.response.send_message("当前频道不是投诉频道。", ephemeral=True)
            return

        if not is_admin_check(interaction):
            await interaction.response.send_message(
                "仅管理员可关闭此频道。", ephemeral=True,
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

class SummonSelectView(PaginatedView):
    """召唤身份组的两步确认面板。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig, guild: discord.Guild):
        super().__init__(
            all_items_provider=lambda: [
                (gid, rg) for gid, rg in config.role_groups.items() if rg.role_ids
            ],
            items_per_page=25,
            timeout=60,
        )
        self.cog = cog
        self._config = config
        self._guild = guild
        self._selected_group_id: str | None = None

    async def _rebuild_view(self):
        self.clear_items()
        page_items = self.get_page_items()

        if page_items:
            options = []
            for group_id, rg in page_items:
                role_names = []
                for rid in rg.role_ids:
                    role = self._guild.get_role(rid)
                    role_names.append(role.name if role else f"（未知角色 {rid}）")
                desc = "、".join(role_names)
                options.append(discord.SelectOption(
                    label=rg.label,
                    value=group_id,
                    description=desc[:100],
                    default=(group_id == self._selected_group_id),
                ))
            self._select = discord.ui.Select(
                placeholder="重新选择" if self._selected_group_id else "选择要召唤的身份组...",
                options=options,
            )
            self._select.callback = self._on_select
            self.add_item(self._select)

        confirm_btn = discord.ui.Button(
            label="✅ 确认召唤", style=discord.ButtonStyle.success, row=1,
            disabled=not self._selected_group_id,
        )
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(
            label="❌ 取消", style=discord.ButtonStyle.secondary, row=1,
        )
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

        self._add_pagination_buttons(row=2)

        # Embed
        if self._selected_group_id:
            group = self._config.role_groups.get(self._selected_group_id)
            if group:
                role_lines = []
                for rid in group.role_ids:
                    role = self._guild.get_role(rid)
                    role_lines.append(f"- {role.mention}" if role else f"- ~~未知角色 <@&{rid}>~~")
                roles_text = "\n".join(role_lines)
                self.embed = discord.Embed(
                    title=f"📢 召唤 **{group.label}**",
                    description=(
                        f"以下角色将被添加到频道并发送通知：\n\n"
                        f"{roles_text}\n\n"
                        "点击 **确认召唤** 完成操作。"
                    ),
                    color=0xFEE75C,
                )
                return
        self.embed = build_summon_embed()

    async def _on_select(self, interaction: discord.Interaction):
        if self._select.values and self._select.values[0] != "none":
            self._selected_group_id = self._select.values[0]
        await self.update_view(interaction)

    async def _on_confirm(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.edit_message(view=None)
            return
        if not self._selected_group_id:
            await interaction.response.edit_message(view=None)
            return

        cfg = self.cog.get_config(interaction.guild.id)
        group = cfg.role_groups.get(self._selected_group_id)
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
            await send_message(
                channel,
                content=f"📢 **{group.label}** 已获权访问本频道（{', '.join(role_names)}）",
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

    async def _on_cancel(self, interaction: discord.Interaction):
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
            await send_message(
                channel,
                content=f"👤 已召唤用户：{' '.join(added)}",
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

class TransferTypeSelectView(PaginatedView):
    """将当前投诉频道转接到其他投诉类型。"""

    def __init__(self, cog: ComplaintCog, config: ComplaintConfig, current_type_id: str, guild: discord.Guild):
        super().__init__(
            all_items_provider=lambda: [
                ct for ct in config.types if ct.id != current_type_id
            ],
            items_per_page=25,
            timeout=60,
        )
        self.cog = cog
        self._config = config
        self.current_type_id = current_type_id
        self._guild = guild
        self._selected_type_id: str | None = None
        self._confirmed = False

    async def _rebuild_view(self):
        self.clear_items()
        page_items = self.get_page_items()

        if page_items:
            options = [
                discord.SelectOption(
                    label=ct.label,
                    value=ct.id,
                    description=ct.description[:100] if ct.description else None,
                    emoji=ct.emoji or None,
                    default=(ct.id == self._selected_type_id),
                )
                for ct in page_items
            ]
            self._select = discord.ui.Select(
                placeholder="重新选择" if self._selected_type_id else "选择转接目标类型...",
                options=options,
            )
            self._select.callback = self._on_select
            self.add_item(self._select)

        confirm_btn = discord.ui.Button(
            label="✅ 确认转接", style=discord.ButtonStyle.success, row=1,
            disabled=not self._selected_type_id,
        )
        confirm_btn.callback = self._on_confirm
        self.add_item(confirm_btn)

        cancel_btn = discord.ui.Button(
            label="❌ 取消", style=discord.ButtonStyle.secondary, row=1,
        )
        cancel_btn.callback = self._on_cancel
        self.add_item(cancel_btn)

        self._add_pagination_buttons(row=2)

        # Embed
        if self._selected_type_id:
            target_type = self._config.get_complaint_type(self._selected_type_id)
            if target_type:
                current_type = self._config.get_complaint_type(self.current_type_id)
                old_role_ids = set(self._config.get_type_target_role_ids(current_type))
                new_role_ids = set(self._config.get_type_target_role_ids(target_type))
                added = new_role_ids - old_role_ids
                removed = old_role_ids - new_role_ids

                desc_parts = [f"将当前工单转接到：**{_format_type_name(target_type)}**\n"]
                if added:
                    lines = []
                    for rid in sorted(added):
                        role = self._guild.get_role(rid)
                        lines.append(role.mention if role else f"<@&{rid}>")
                    desc_parts.append(f"**新增处理组**：{' '.join(lines)}\n")
                if removed:
                    lines = []
                    for rid in sorted(removed):
                        role = self._guild.get_role(rid)
                        lines.append(role.mention if role else f"<@&{rid}>")
                    desc_parts.append(f"**移除处理组**：{' '.join(lines)}\n")
                desc_parts.append("\n确认后会移除旧处理组权限，并将新处理组加入当前频道。")
                self.embed = discord.Embed(
                    title="🔀 确认转接工单",
                    description="".join(desc_parts),
                    color=0xFEE75C,
                )
                return

        current_type = self._config.get_complaint_type(self.current_type_id)
        self.embed = discord.Embed(
            title="🔀 转接工单",
            description=(
                f"当前工单类型：**{_format_type_name(current_type)}**\n\n"
                "请选择要转接到的投诉类型。\n"
                "转接后将移除旧处理组权限，并授予新处理组权限。"
            ),
            color=0xFEE75C,
        )

    async def _on_select(self, interaction: discord.Interaction):
        if self._select.values:
            self._selected_type_id = self._select.values[0]
        await self.update_view(interaction)

    async def _on_confirm(self, interaction: discord.Interaction):
        if self._confirmed:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            return
        self._confirmed = True

        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.edit_message(view=None)
            return

        if not self._selected_type_id:
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
                new_type_id=self._selected_type_id,
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

        await interaction.channel.send(
            embed=discord.Embed(
                title="🔀 工单转接通知",
                description=(
                    f"工单已由 **{interaction.user.display_name}** 转接。\n"
                    f"**原类型**：{_format_type_name(old_type or current_type)}\n"
                    f"**新类型**：{_format_type_name(new_type)}"
                ),
                color=0xFEE75C,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

        # 向新类型的通知频道发送转接通知
        if new_type.notify_channel_id and new_type.notify_message:
            try:
                ticket_number = parse_ticket_from_name(interaction.channel.name)
                complainant = await try_get_member(interaction.guild, meta.complainant_id)
                if complainant and ticket_number is not None:
                    notify_content = render_notify_message(
                        notify_message=new_type.notify_message,
                        full_config=cfg,
                        guild=interaction.guild,
                        type_config=new_type,
                        ticket_number=ticket_number,
                        complainant=complainant,
                        channel=interaction.channel,
                    )
                    notify_target = interaction.guild.get_channel(new_type.notify_channel_id)
                    if notify_target is None:
                        notify_target = await interaction.guild.fetch_channel(new_type.notify_channel_id)
                    if isinstance(notify_target, (discord.TextChannel, discord.Thread)):
                        await send_message(
                            notify_target,
                            content=notify_content,
                            embed=build_notify_embed(
                                type_label=new_type.label,
                                type_emoji=new_type.emoji,
                                ticket_number=ticket_number,
                                channel_mention=interaction.channel.mention,
                                complainant_name=complainant.display_name,
                            ),
                            allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
                        )
            except Exception:
                logger.warning("转接工单 %s 通知发送失败", self._selected_type_id, exc_info=True)

        await interaction.edit_original_response(
            embed=build_success_embed(
                f"已将工单从 **{_format_type_name(old_type or current_type)}** "
                f"转接为 **{_format_type_name(new_type)}**。"
            ),
            view=None,
        )

    async def _on_cancel(self, interaction: discord.Interaction):
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

    def __init__(self, cog: ComplaintCog, type_id: str, user_id: int):
        super().__init__(timeout=120)
        self.cog = cog
        self.type_id = type_id
        self._user_id = user_id

    async def on_timeout(self):
        self.cog._pending_forms.pop((self._user_id, self.type_id), None)

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
        self.cog._pending_forms.pop((self._user_id, self.type_id), None)
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

        if not is_admin_check(interaction):
            await interaction.response.send_message("仅管理员可执行此操作。", ephemeral=True)
            return

        channel = interaction.channel
        meta = self.cog.channel_manager.get_channel_meta(interaction.guild.id, channel.id)

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
                type_id=meta.type_id if meta else None,
                type_label=type_label,
                type_emoji=type_emoji,
                complainant_id=complainant_id,
                form_data=meta.form_data if meta else {},
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

        if not is_admin_check(interaction):
            await interaction.response.send_message(
                "仅管理员可删除此频道。", ephemeral=True,
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
        if not is_admin_check(interaction):
            await interaction.response.send_message("仅管理员可执行此操作。", ephemeral=True)
            return

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
