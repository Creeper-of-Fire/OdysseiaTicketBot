from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)

COUNT_PATTERN = re.compile(r"\[投诉计数\]已发布(\d+)")
SCAN_LIMIT = 100


class TicketCounterService:
    """基于归档频道消息的并发安全 ticket 计数器。

    通过 asyncio.Lock（per guild）保证并发安全。
    计数状态存储在 Discord 消息中（[投诉计数]已发布{num}），重启后自动恢复。
    """

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    async def get_next_number(
        self,
        guild_id: int,
        archive_channel: discord.TextChannel,
    ) -> int:
        """获取下一个 ticket 编号。

        1. 获取 guild 级锁
        2. 扫描归档频道最近 N 条消息，找最新计数
        3. 如果没找到 → 报错
        4. 计算 next = max + 1
        5. 发新计数消息到归档频道（原子占号）
        6. 返回 next
        """
        async with self._get_lock(guild_id):
            latest = await self._scan_for_latest(archive_channel)
            if latest is None:
                raise RuntimeError(
                    f"在归档频道 <#{archive_channel.id}> 中未找到计数消息"
                    f"（最近 {SCAN_LIMIT} 条）。\n"
                    f"请管理员在归档频道中手动发送 [投诉计数]已发布0 以初始化计数。"
                )
            next_number = latest + 1
            await archive_channel.send(f"[投诉计数]已发布{next_number}")
            logger.info(
                "Ticket counter: %d → %d (guild %s)",
                latest, next_number, guild_id,
            )
            return next_number

    def _get_lock(self, guild_id: int) -> asyncio.Lock:
        """获取指定服务器的异步锁（按需创建）。"""
        if guild_id not in self._locks:
            self._locks[guild_id] = asyncio.Lock()
        return self._locks[guild_id]

    async def _scan_for_latest(
        self,
        channel: discord.TextChannel,
    ) -> int | None:
        """扫描频道最近消息，返回最大的计数值。"""
        latest: int | None = None
        async for message in channel.history(limit=SCAN_LIMIT):
            match = COUNT_PATTERN.search(message.content)
            if match:
                num = int(match.group(1))
                if latest is None or num > latest:
                    latest = num
        return latest
