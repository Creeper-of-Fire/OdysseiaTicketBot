from __future__ import annotations

import discord

from complaint.config.models import ComplaintTypeConfig


def build_entry_embed() -> discord.Embed:
    return discord.Embed(
        title="📋 投诉中心",
        description=(
            "如果你需要提交投诉或反馈，请选择下方的方式：\n\n"
            "🔒 **私密投诉** — 仅你和对应管理可见\n"
            "🌐 **公开投诉** — 所有成员可见\n"
        ),
        color=0x5865F2,
    )


def build_type_select_embed(visibility: str) -> discord.Embed:
    vis_label = "私密" if visibility == "private" else "公开"
    return discord.Embed(
        title=f"选择投诉类型（{vis_label}）",
        description="请从下方选择你要提交的投诉类型。",
        color=0x5865F2,
    )


def build_confirm_embed(type_config: ComplaintTypeConfig) -> discord.Embed:
    return discord.Embed(
        title="⚠️ 确认提交",
        description=(
            f"你即将提交一份 **{type_config.emoji} {type_config.label}**。\n"
            f"此操作将创建一个投诉频道，相关管理将被通知。\n\n"
            "确定要继续吗？"
        ),
        color=0xFEE75C,
    )


def build_close_confirm_embed(confirmation_text: str) -> discord.Embed:
    return discord.Embed(
        title="⚠️ 确认关闭",
        description=confirmation_text,
        color=0xED4245,
    )


def build_summon_embed() -> discord.Embed:
    return discord.Embed(
        title="📢 召唤身份组",
        description="选择要召唤到本频道的身份组。对应成员将被添加到频道权限并收到通知。",
        color=0x5865F2,
    )


def build_success_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="✅ 操作成功",
        description=message,
        color=0x57F287,
    )


def build_error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title="❌ 操作失败",
        description=message,
        color=0xED4245,
    )
