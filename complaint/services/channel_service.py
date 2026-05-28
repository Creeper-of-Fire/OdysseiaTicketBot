from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from complaint.ComplaintCog import ComplaintCog
    from complaint.config.models import ComplaintConfig, ComplaintTypeConfig

logger = logging.getLogger(__name__)

_TICKET_NAME_RE = re.compile(r"^ticket-(\d+)")


def parse_ticket_from_name(channel_name: str) -> int | None:
    m = _TICKET_NAME_RE.match(channel_name)
    return int(m.group(1)) if m else None


def sanitize_channel_name(name: str) -> str:
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
    ticket_number: int | None = None,
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

    if ticket_number is not None:
        channel_name = sanitize_channel_name(f"ticket-{ticket_number}")
    else:
        channel_name = sanitize_channel_name(f"投诉-{type_config.label}-{complainant.display_name}")

    channel = await guild.create_text_channel(
        name=channel_name,
        category=category,
        overwrites=overwrites,
        reason=f"创建投诉频道：{type_config.label}（{complainant}）",
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

    manage_view = ManagePanelView(cog)
    await channel.send(embed=_manage_panel_embed(), view=manage_view)
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
    ticket_number: int | None = None,
) -> str:
    from complaint.config.models import TemplateConfig  # noqa

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
        timestamp=timestamp,
        form_section=form_section,
        ticket_number=ticket_number or "",
    )


def _manage_panel_embed() -> discord.Embed:
    return discord.Embed(
        title="🛠️ 频道管理面板",
        description="管理员可使用下方按钮管理本投诉频道。",
        color=0x5865F2,
    )
