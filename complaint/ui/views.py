from __future__ import annotations

import discord

from complaint.config.models import ComplaintConfig


# ===== 入口面板 =====

class EntryView(discord.ui.View):
    """入口面板的持久化 View。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔒 提交投诉",
        style=discord.ButtonStyle.primary,
        custom_id="complaint:entry",
        row=0,
    )
    async def _btn_submit(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass  # 由 on_interaction 处理


# ===== 类型选择 =====

def build_type_select_view(config: ComplaintConfig) -> discord.ui.View:
    """构建投诉类型选择的 SelectMenu View。"""
    view = discord.ui.View(timeout=120)

    options = []
    for ct in config.types:
        options.append(discord.SelectOption(
            label=ct.label,
            description=ct.description[:100] if ct.description else None,
            value=ct.id,
            emoji=ct.emoji or None,
        ))

    select = discord.ui.Select(
        custom_id="complaint:type_select",
        placeholder="选择投诉类型...",
        options=options,
    )
    view.add_item(select)
    return view


# ===== 管理面板 =====

class ManagePanelView(discord.ui.View):
    """频道管理面板的持久化 View。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="📢 召唤身份组",
        style=discord.ButtonStyle.primary,
        custom_id="complaint:manage_summon",
        row=0,
    )
    async def _btn_summon(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(
        label="🗑️ 关闭频道",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:manage_close",
        row=0,
    )
    async def _btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass


# ===== 召唤选择 =====

def build_summon_select_view(config: ComplaintConfig) -> discord.ui.View:
    """构建身份组选择下拉菜单。"""
    view = discord.ui.View(timeout=60)

    options = []
    for group_id, rg in config.role_groups.items():
        if rg.role_ids:
            options.append(discord.SelectOption(
                label=rg.label,
                value=group_id,
            ))

    select = discord.ui.Select(
        custom_id="complaint:summon_select",
        placeholder="选择要召唤的身份组...",
        options=options or [discord.SelectOption(label="（无可用身份组）", value="none")],
    )
    view.add_item(select)
    return view


# ===== 二次确认（表单提交前）=====

def build_confirm_proceed_view(
    type_id: str,
) -> discord.ui.View:
    """构建表单提交前的确认视图。type_id 编码到 custom_id 中。"""
    view = discord.ui.View(timeout=120)

    view.add_item(discord.ui.Button(
        label="✅ 确认提交",
        style=discord.ButtonStyle.success,
        custom_id=f"complaint:confirm_proceed:{type_id}",
        row=0,
    ))
    view.add_item(discord.ui.Button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:confirm_cancel",
        row=0,
    ))
    return view


# ===== 关闭确认 =====

class CloseConfirmView(discord.ui.View):
    """关闭频道的二次确认视图。"""

    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(
        label="✅ 确认关闭并归档",
        style=discord.ButtonStyle.danger,
        custom_id="complaint:close_confirm",
        row=0,
    )
    async def _btn_confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(
        label="❌ 取消",
        style=discord.ButtonStyle.secondary,
        custom_id="complaint:close_cancel",
        row=0,
    )
    async def _btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass
