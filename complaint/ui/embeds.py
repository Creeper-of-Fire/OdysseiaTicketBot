from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from complaint.config.models import ComplaintTypeConfig, ComplaintConfig


def build_entry_embed() -> discord.Embed:
    """构建投诉入口面板的 Embed。"""
    return discord.Embed(
        title="📋 投诉中心",
        description=(
            "如果你在社区中遇到了问题，或对管理团队的工作有意见，可以通过本系统提交投诉或反馈。\n\n"
            "📌 **提交流程**\n"
            "1. 点击下方「提交投诉」按钮\n"
            "2. 选择投诉类型\n"
            "3. 填写投诉表单\n"
            "4. 系统将为你创建一个私密频道\n\n"
            "🔒 **隐私保护**\n"
            "仅你本人和对应管理组成员可见，其他用户无法查看你的投诉内容。"
        ),
        color=0x5865F2,
    )


def build_type_select_embed(config: ComplaintConfig) -> discord.Embed:
    """构建投诉类型选择面板的 Embed，列出所有可选类型。"""
    lines = ["请根据你的需求选择最匹配的投诉类型。\n"]
    for ct in config.types:
        lines.append(f"{ct.emoji} **{ct.label}** — {ct.description}")
    return discord.Embed(
        title="📋 选择投诉类型",
        description="\n".join(lines),
        color=0x5865F2,
    )


def build_confirm_embed(type_config: ComplaintTypeConfig) -> discord.Embed:
    """构建提交前二次确认的 Embed。"""
    return discord.Embed(
        title="⚠️ 确认提交",
        description=(
            f"你即将提交一份 **{type_config.emoji} {type_config.label}**。\n\n"
            "提交后系统将：\n"
            "• 创建一个仅你和对应管理可见的私密频道\n"
            "• 通知相关管理组成员加入处理\n"
            "• 你可以在频道中与管理组直接沟通\n\n"
            "确定要继续吗？"
        ),
        color=0xFEE75C,
    )


def build_manage_panel_embed() -> discord.Embed:
    """构建频道管理面板的 Embed。"""
    return discord.Embed(
        title="🛠️ 频道管理面板",
        description=(
            "本面板用于管理投诉频道的各项操作。\n\n"
            "• 📢 **召唤身份组**（仅管理组可用） — 邀请管理组身份组加入本频道\n"
            "• 👤 **召唤用户**（仅管理组可用） — 邀请特定用户加入本频道\n"
            "• 🗑️ **关闭频道** — 如果处理完毕，可以归档并关闭本投诉频道"
        ),
        color=0x5865F2,
    )


def build_archive_confirm_embed(
        operator_mention: str,
) -> discord.Embed:
    """构建归档确认的 Embed，可选标注操作人。"""
    return discord.Embed(
        title="⚠️ 确认归档",
        description=(
            f"由 {operator_mention} 发起\n\n"
            "此操作将对本投诉频道执行归档：\n"
            "• 导出频道内所有消息为归档文件并保存\n"
            "• 归档文件将发送至归档频道永久保存\n"
            "• 归档完成后，可选择删除本频道\n\n"
            "⚠️ 归档后频道内容将无法恢复，请确认所有问题已处理完毕。\n\n"
            "确定要继续吗？"
        ),
        color=0xED4245,
    )


def build_archive_success_embed(archive_url: str) -> discord.Embed:
    """构建归档成功的 Embed，包含跳转链接。"""
    return discord.Embed(
        title="✅ 归档完成",
        description=(
            f"本频道的所有消息已成功导出为归档文件，并发送至归档频道保存。\n\n"
            f"📎 [查看归档]({archive_url})\n\n"
            "你可以点击下方按钮删除本频道，或保留以备后续参考。"
        ),
        color=0x57F287,
    )


def build_summon_embed() -> discord.Embed:
    """构建召唤身份组面板的 Embed。"""
    return discord.Embed(
        title="📢 召唤身份组",
        description=(
            "选择要邀请到本频道的身份组。\n\n"
            "被选中的身份组的所有成员将被：\n"
            "• 添加到频道权限，可以查看和发送消息\n\n"
            "⚠️ 为避免骚扰大量成员，不会发送 @mention 通知。\n"
            "如有需要，请手动 @ 相关人员。"
        ),
        color=0x5865F2,
    )


def build_summon_user_embed() -> discord.Embed:
    """构建召唤用户面板的 Embed。"""
    return discord.Embed(
        title="👤 召唤用户",
        description=(
            "选择要邀请到本频道的用户，最多可选择 10 位。\n\n"
            "被选中的用户将被：\n"
            "• 添加到频道权限，可以查看和发送消息\n"
            "• 收到加入通知"
        ),
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


def build_notify_embed(
    *,
    type_label: str,
    type_emoji: str,
    ticket_number: int,
    channel_mention: str,
    complainant_name: str,
) -> discord.Embed:
    """构建工单创建通知 Embed。"""
    return discord.Embed(
        title="🔔 新工单通知",
        color=0x5865F2,
    ).add_field(name="类型", value=f"{type_emoji} {type_label}", inline=True
    ).add_field(name="工单编号", value=str(ticket_number), inline=True
    ).add_field(name="投诉人", value=complainant_name, inline=True
    ).add_field(name="频道", value=channel_mention, inline=False)
