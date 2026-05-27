from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from complaint.config.models import ComplaintConfig, ComplaintTypeConfig

logger = logging.getLogger(__name__)

TOPIC_PREFIX = "complaint"


def encode_topic(
    *,
    complainant_id: int,
    type_id: str,
    visibility: str,
) -> str:
    return f"{TOPIC_PREFIX}|complainant:{complainant_id}|type:{type_id}|visibility:{visibility}"


def parse_topic(topic: str | None) -> dict | None:
    if not topic or not topic.startswith(TOPIC_PREFIX):
        return None
    parts = topic.split("|")
    result: dict = {}
    for part in parts[1:]:
        if ":" in part:
            key, value = part.split(":", 1)
            result[key] = value
    if "complainant" not in result:
        return None
    try:
        result["complainant"] = int(result["complainant"])
    except (ValueError, TypeError):
        return None
    return result


def sanitize_channel_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9一-鿿_-]", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name[:90]


async def create_complaint_channel(
    bot: discord.Client,
    guild: discord.Guild,
    complainant: discord.Member,
    type_config: ComplaintTypeConfig,
    visibility: str,
    form_data: dict[str, str],
    full_config: ComplaintConfig,
) -> discord.TextChannel:
    """创建投诉频道、设置权限、发送初始消息和管理面板。"""
    from complaint.ui.views import ManagePanelView  # noqa: avoid circular import

    category_id = full_config.guild.category_id
    if not category_id:
        raise RuntimeError("未配置投诉分类，请先使用 /投诉管理 配置服务器")

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        raise RuntimeError("投诉分类频道不可用")

    target_role_ids = full_config.get_all_role_ids_for_groups(type_config.target_role_groups)

    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=(visibility == "public"),
            send_messages=False,
            read_message_history=(visibility == "public"),
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

    channel_name = sanitize_channel_name(f"投诉-{type_config.label}-{complainant.display_name}")
    topic = encode_topic(
        complainant_id=complainant.id,
        type_id=type_config.id,
        visibility=visibility,
    )

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        topic=topic,
        overwrites=overwrites,
        reason=f"创建投诉频道：{type_config.label}（{complainant}）",
    )

    header_content = _render_header(
        type_config=type_config,
        visibility=visibility,
        complainant=complainant,
        form_data=form_data,
        templates=full_config.templates,
    )
    await channel.send(content=header_content, allowed_mentions=discord.AllowedMentions.none())

    mentions: list[str] = [complainant.mention]
    for role_id in target_role_ids:
        mentions.append(f"<@&{role_id}>")
    if mentions:
        await channel.send(
            content=" ".join(mentions),
            allowed_mentions=discord.AllowedMentions(roles=True, users=True, everyone=False),
        )

    manage_view = ManagePanelView()
    await channel.send(embed=_manage_panel_embed(), view=manage_view)
    bot.add_view(manage_view)

    logger.info(
        "已创建投诉频道 %s (类型: %s, 可见性: %s, 投诉人: %s)",
        channel.name, type_config.id, visibility, complainant.id,
    )

    return channel


def _render_header(
    *,
    type_config: ComplaintTypeConfig,
    visibility: str,
    complainant: discord.Member,
    form_data: dict[str, str],
    templates: "TemplateConfig",
) -> str:
    from complaint.config.models import TemplateConfig  # noqa

    vis_label = "公开" if visibility == "public" else "私密"
    timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M UTC")

    form_section = ""
    if form_data:
        lines = []
        for field in type_config.form_fields:
            value = form_data.get(field.key, "")
            if value:
                lines.append(templates.form_field_format.format(label=field.label, value=value))
        form_section = "\n".join(lines)

    return templates.channel_header.format(
        complainant_mention=complainant.mention,
        type_label=type_config.label,
        type_emoji=type_config.emoji,
        visibility=vis_label,
        timestamp=timestamp,
        form_section=form_section,
    )


def _manage_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🛠️ 频道管理面板",
        description="管理员可使用下方按钮管理本投诉频道。",
        color=0x5865F2,
    )
