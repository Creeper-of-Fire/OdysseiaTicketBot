from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


async def send_message(
    target,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    file: discord.File | None = None,
    files: list[discord.File] | None = None,
    view: discord.ui.View | None = None,
    allowed_mentions: discord.AllowedMentions | None = None,
    suppress_embeds: bool = False,
    silent: bool = False,
) -> discord.Message:
    """统一消息发送入口。duck-type 转发到 ``target.send()``。

    不做目标类型判断，由 caller 决定向哪里发。``allowed_mentions`` 不设默认值，
    调用方需显式传入以匹配各场景的语义（``AllowedMentions.none()`` / 仅 users /
    roles+users 等）。

    失败时记录 ``logger.error`` 后**重抛原异常**——caller 自行决定如何响应。
    """
    try:
        return await target.send(
            content=content,
            embed=embed,
            embeds=embeds,
            file=file,
            files=files,
            view=view,
            allowed_mentions=allowed_mentions,
            suppress_embeds=suppress_embeds,
            silent=silent,
        )
    except discord.HTTPException:
        logger.error("发送到 %s 失败", target, exc_info=True)
        raise


async def resolve_sendable(
    bot: discord.Client | None,
    guild: discord.Guild,
    channel_id: int,
):
    """先 ``bot.get_channel`` 再 ``guild.fetch_channel``，取一个能 send 的对象。

    不做类型判断（thread / TextChannel / 论坛帖等都返回原对象）。取不到时返回 None，
    caller 据此决定提示文本。

    ``bot`` 可为 None——仅当调用方只想用 guild API（无 bot 句柄）时传 None，
    此时跳过 ``bot.get_channel``，直接走 ``guild.fetch_channel``。
    """
    if bot is not None:
        target = bot.get_channel(channel_id)
        if target is not None:
            return target
    try:
        return await guild.fetch_channel(channel_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
