from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

import discord

from complaint.ui.embeds import build_manage_panel_embed

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog
    from complaint.config.models import ComplaintConfig, ComplaintTypeConfig

logger = logging.getLogger(__name__)

TICKET_PREFIX = "工单"
"""工单编号前缀，用于频道名和显示文本。"""


def ticket_display(number: int) -> str:
    """将编号格式化为显示用的工单标识（如 "工单-1"）。"""
    return f"{TICKET_PREFIX}-{number}"


def parse_ticket_from_name(channel_name: str) -> int | None:
    """从频道名中解析工单编号，解析失败返回 None。"""
    prefix = f"{TICKET_PREFIX}-"
    if channel_name.startswith(prefix):
        try:
            return int(channel_name[len(prefix):])
        except ValueError:
            return None
    return None


def sanitize_channel_name(name: str) -> str:
    """清理字符串使其符合 Discord 频道名要求。"""
    name = re.sub(r"[^a-zA-Z0-9一-鿿_-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name[:90]


async def create_complaint_channel(
    cog: ComplaintCog,
    guild: discord.Guild,
    complainant: discord.Member,
    type_config: ComplaintTypeConfig,
    form_data: dict[str, str],
    full_config: ComplaintConfig,
    ticket_number: int,
) -> discord.TextChannel:
    """创建投诉频道、设置权限、发送初始消息和管理面板。"""
    from complaint.services.channel_meta import ComplaintChannelMeta
    from complaint.ui.views import ManagePanelView

    category_id = full_config.guild.category_id
    if not category_id:
        raise RuntimeError("未配置投诉分类，请先使用 /投诉管理 配置服务器")

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise RuntimeError("投诉分类频道不可用")

    target_role_ids = full_config.get_all_role_ids_for_groups(type_config.target_role_groups)

    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=False,
            send_messages=False,
            read_message_history=False,
        ),
    }

    bot_member = guild.me
    overwrites[bot_member] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        manage_channels=True,
        read_message_history=True,
        attach_files=True,
    )

    overwrites[complainant] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
    )

    for role_id in target_role_ids:
        role = guild.get_role(role_id)
        if role:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            )
        else:
            logger.warning("角色 %s 在服务器 %s 中不存在，跳过权限设置", role_id, guild.id)

    channel_name = sanitize_channel_name(ticket_display(ticket_number))

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"创建投诉频道 {ticket_display(ticket_number)}",
    )

    meta = ComplaintChannelMeta(
        complainant_id=complainant.id,
        type_id=type_config.id,
    )
    cog.channel_manager.register_channel(guild.id, channel.id, meta)
    await cog.channel_manager.save_data()

    header_content = _render_header(
        type_config=type_config,
        complainant=complainant,
        form_data=form_data,
        templates=full_config.templates,
        ticket_number=ticket_number,
        full_config=full_config,
        guild=guild,
    )
    await channel.send(
        content=header_content,
        allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
    )

    manage_view = ManagePanelView(cog)
    await channel.send(embed=build_manage_panel_embed(), view=manage_view)
    cog.bot.add_view(manage_view)

    logger.info(
        "已创建投诉频道 %s (类型: %s, 投诉人: %s)",
        channel.name, type_config.id, complainant.id,
    )

    return channel


def _render_header(
    *,
    type_config: ComplaintTypeConfig,
    complainant: discord.Member,
    form_data: dict[str, str],
    templates: "TemplateConfig",
    ticket_number: int,
    full_config: ComplaintConfig,
    guild: discord.Guild,
) -> str:
    """根据模板渲染频道头部消息。"""
    from complaint.config.models import TemplateConfig  # noqa

    timestamp = f"<t:{int(datetime.now().timestamp())}:f>"

    form_section = ""
    if form_data:
        lines = []
        for field in type_config.form_fields:
            value = form_data.get(field.key, "")
            if value:
                lines.append(templates.form_field_format.format(label=field.label, value=value))
        form_section = "\n".join(lines)

    custom_section = _render_header_blocks(
        header_blocks=type_config.header_blocks,
        full_config=full_config,
        guild=guild,
        type_config=type_config,
        ticket_number=ticket_number,
    )

    return templates.channel_header.format(
        complainant_mention=complainant.mention,
        type_label=type_config.label,
        type_emoji=type_config.emoji,
        timestamp=timestamp,
        form_section=form_section,
        ticket_number=ticket_number,
        custom_section=custom_section,
    )


# header_blocks 支持的宏：{@group_id} → 角色组 mention，
# {type_label} → 类型名，{type_emoji} → 类型 emoji，{ticket_number} → 工单编号。
_MACRO_PATTERN = re.compile(r"\{([^}]+)\}")


def _render_header_blocks(
    *,
    header_blocks: list[str],
    full_config: ComplaintConfig,
    guild: discord.Guild,
    type_config: ComplaintTypeConfig,
    ticket_number: int,
) -> str:
    """将 header_blocks 中的宏替换为实际内容，返回拼接后的文本。"""
    if not header_blocks:
        return ""

    # 纯文本宏，直接查表替换
    static_macros: dict[str, str] = {
        "type_label": type_config.label,
        "type_emoji": type_config.emoji,
        "ticket_number": str(ticket_number),
    }

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        # {@group_id} → 解析角色组并拼接角色 mention
        if key.startswith("@"):
            group_id = key[1:]
            group = full_config.role_groups.get(group_id)
            if not group:
                return ""
            mentions: list[str] = []
            for rid in group.role_ids:
                role = guild.get_role(rid)
                if role:
                    mentions.append(role.mention)
            return " ".join(mentions)
        # 纯文本宏
        return static_macros.get(key, "")

    rendered = []
    for block in header_blocks:
        rendered.append(_MACRO_PATTERN.sub(_replace, block))
    return "\n".join(rendered)

