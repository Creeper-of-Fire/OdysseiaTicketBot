from __future__ import annotations

import discord

from complaint.config.models import ComplaintTypeConfig


def build_entry_embed() -> discord.Embed:
    """构建投诉入口面板的 Embed。"""
    return discord.Embed(
        title="📋 投诉中心",
        description=(
            "如果你需要提交投诉或反馈，请点击下方按钮。\n\n"
            "🔒 仅你和对应管理可见\n"
        ),
        color=0x5865F2,
    )


def build_type_select_embed() -> discord.Embed:
    """构建投诉类型选择面板的 Embed。"""
    return discord.Embed(
        title="选择投诉类型",
        description="请从下方选择你要提交的投诉类型。",
        color=0x5865F2,
    )


def build_confirm_embed(type_config: ComplaintTypeConfig) -> discord.Embed:
    """构建提交前二次确认的 Embed。"""
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
    """构建关闭频道确认的 Embed。"""
    return discord.Embed(
        title="⚠️ 确认关闭",
        description=confirmation_text,
        color=0xED4245,
    )


def build_archive_confirm_embed(
    confirmation_text: str,
    *,
    operator_mention: str | None = None,
) -> discord.Embed:
    """构建归档确认的 Embed，可选标注操作人。"""
    description = confirmation_text
    if operator_mention:
        description = f"由 {operator_mention} 发起\n\n{description}"
    return discord.Embed(
        title="⚠️ 确认归档",
        description=description,
        color=0xED4245,
    )


def build_archive_success_embed(archive_url: str) -> discord.Embed:
    """构建归档成功的 Embed，包含跳转链接。"""
    return discord.Embed(
        title="✅ 归档完成",
        description=f"归档文件已发送到归档频道。[查看归档]({archive_url})\n\n点击下方按钮可删除此频道。",
        color=0x57F287,
    )


def build_summon_embed() -> discord.Embed:
    """构建召唤身份组面板的 Embed。"""
    return discord.Embed(
        title="📢 召唤身份组",
        description="选择要召唤到本频道的身份组。对应成员将被添加到频道权限并收到通知。",
        color=0x5865F2,
    )


def build_summon_user_embed() -> discord.Embed:
    """构建召唤用户面板的 Embed。"""
    return discord.Embed(
        title="👤 召唤用户",
        description="选择要召唤到本频道的用户。被选中的用户将被添加到频道权限并收到通知。",
        color=0x5865F2,
    )


def build_success_embed(message: str) -> discord.Embed:
    """构建通用成功提示的 Embed。"""
    return discord.Embed(
        title="✅ 操作成功",
        description=message,
        color=0x57F287,
    )


def build_error_embed(message: str) -> discord.Embed:
    """构建通用错误提示的 Embed。"""
    return discord.Embed(
        title="❌ 操作失败",
        description=message,
        color=0xED4245,
    )
