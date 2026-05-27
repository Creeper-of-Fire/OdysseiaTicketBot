from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from complaint.config.models import ComplaintConfig
from complaint.services.channel_service import parse_topic
from complaint.ui.embeds import (
    build_close_confirm_embed,
    build_error_embed,
    build_success_embed,
    build_summon_embed,
    build_type_select_embed,
)
from complaint.ui.modals import ComplaintFormModal
from utility.permison import is_admin_check

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog


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
            return
        cfg = self.cog.get_config(interaction.guild.id)
        if not cfg.types:
            await interaction.response.send_message("暂无可用的投诉类型。", ephemeral=True)
            return

        view = TypeSelectView(self.cog, cfg)
        await interaction.response.send_message(
            embed=build_type_select_embed(), view=view, ephemeral=True,
        )


# ===== 类型选择 =====

class TypeSelectView(discord.ui.View):
    def __init__(self, cog: ComplaintCog, config: ComplaintConfig):
        super().__init__(timeout=120)
        self.cog = cog

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
        cfg = self.cog.get_config(interaction.guild.id)
        type_config = cfg.get_complaint_type(type_id)
        if not type_config:
            await interaction.response.send_message("投诉类型不存在。", ephemeral=True)
            return

        modal = ComplaintFormModal(self.cog, type_config)
        await interaction.response.send_modal(modal)


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
        view = SummonSelectView(self.cog, cfg)
        await interaction.response.send_message(
            embed=build_summon_embed(), view=view, ephemeral=True,
        )

    @discord.ui.button(
        label="🗑️ 关闭频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:manage_close",
        row=0,
    )
    async def _btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
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
                "仅投诉人或管理员可关闭此频道。", ephemeral=True,
            )
            return

        cfg = self.cog.get_config(interaction.guild.id) if interaction.guild else self.cog.get_config(0)
        await interaction.response.send_message(
            embed=build_close_confirm_embed(cfg.templates.confirmation_text),
            view=CloseConfirmView(self.cog, interaction.channel),
            ephemeral=True,
        )


# ===== 召唤选择 =====

class SummonSelectView(discord.ui.View):
    def __init__(self, cog: ComplaintCog, config: ComplaintConfig):
        super().__init__(timeout=60)
        self.cog = cog

        options = [
            discord.SelectOption(label=rg.label, value=group_id)
            for group_id, rg in config.role_groups.items()
            if rg.role_ids
        ]

        self._select = discord.ui.Select(
            placeholder="选择要召唤的身份组...",
            options=options or [discord.SelectOption(label="（无可用身份组）", value="none")],
        )
        self._select.callback = self._on_select
        self.add_item(self._select)

    async def _on_select(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return

        values = self._select.values
        if not values or values[0] == "none":
            return

        group_id = values[0]
        cfg = self.cog.get_config(interaction.guild.id)
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


# ===== 二次确认（表单提交前）=====

class ConfirmProceedView(discord.ui.View):
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
        await interaction.response.update_message(
            embed=build_success_embed("已取消提交。"), view=None,
        )


# ===== 关闭确认 =====

class CloseConfirmView(discord.ui.View):
    def __init__(self, cog: ComplaintCog, channel: discord.TextChannel):
        super().__init__(timeout=120)
        self.cog = cog
        self.channel = channel

    @discord.ui.button(
        label="✅ 确认关闭并归档",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:close_confirm",
        row=0,
    )
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return

        meta = parse_topic(self.channel.topic)
        if not meta:
            await interaction.response.send_message("该频道不是投诉频道。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        guild_id = interaction.guild.id
        cfg = self.cog.get_config(guild_id)
        type_config = cfg.get_complaint_type(meta.get("type", ""))
        type_label = type_config.label if type_config else meta.get("type", "未知")
        type_emoji = type_config.emoji if type_config else "📋"

        try:
            await self.cog._get_archive_service(guild_id).archive_channel(
                self.channel,
                type_label=type_label,
                type_emoji=type_emoji,
                complainant_id=meta["complainant"],
                form_data={},
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=build_error_embed(f"归档失败：{e}"),
            )
            return

        try:
            await interaction.edit_original_response(
                embed=build_success_embed("投诉频道已归档并删除。"),
            )
        except Exception:
            pass

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:close_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.update_message(
            embed=build_success_embed("已取消关闭操作。"), view=None,
        )
