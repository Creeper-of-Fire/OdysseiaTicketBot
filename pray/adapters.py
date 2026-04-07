
import discord
from typing import List, Optional, Any
from pydantic import BaseModel, Field

from config_data import GuildWishConfig
from pray.pray_core.models import Wish
from pray.pray_core.ports import IWishRepository, IWishExternalAdapter
from utility.base_data_manager import AsyncGuildDataManager


class AsyncJsonWishRepository(IWishRepository):
    """对接您的 AsyncGuildDataManager"""

    def __init__(self, manager:AsyncGuildDataManager[Any], guild_id: int):
        self.manager = manager
        self.guild_id = guild_id

    async def save(self, wish: Wish):
        guild_data = self.manager.ensure_guild(self.guild_id)
        guild_data.wishes[wish.id] = wish
        # 触发异步保存
        await self.manager.save_data()

    async def get(self, wish_id: str) -> Optional[Wish]:
        guild_data = self.manager.ensure_guild(self.guild_id)
        return guild_data.wishes.get(wish_id)

    async def get_all(self) -> List[Wish]:
        guild_data = self.manager.ensure_guild(self.guild_id)
        return list(guild_data.wishes.values())


class DiscordWishAdapter(IWishExternalAdapter):
    """处理与 Discord API 的副作用交互"""

    def __init__(self, bot: discord.Client, config: GuildWishConfig):
        self.bot = bot
        self.config = config

    async def create_discussion_thread(self, wish: Wish) -> str:
        channel = self.bot.get_channel(self.config.discussion_parent_id)
        if not channel or not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            return ""

        thread_name = f"讨论｜{wish.title[:20]}"
        # 如果是普通文本频道，创建公共线程
        if isinstance(channel, discord.TextChannel):
            thread = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread, reason=f"愿望进入讨论: {wish.id}"
            )
            await thread.send(f"💡 **愿望详情**\n作者: <@{wish.author_id}>\n内容: {wish.content}")
            return str(thread.id)
        # 如果是论坛频道(ForumChannel)
        elif isinstance(channel, discord.ForumChannel):
            thread, _ = await channel.create_thread(
                name=thread_name, content=f"💡 **愿望详情**\n作者: <@{wish.author_id}>\n内容: {wish.content}"
            )
            return str(thread.id)
        return ""

    async def lock_discussion_thread(self, thread_id: str):
        thread = self.bot.get_channel(int(thread_id))
        if isinstance(thread, discord.Thread):
            await thread.edit(archived=True, locked=True)

    async def unlock_discussion_thread(self, thread_id: str):
        thread = self.bot.get_channel(int(thread_id))
        if isinstance(thread, discord.Thread):
            await thread.edit(archived=False, locked=False)

    async def broadcast_event(self, message: str):
        if self.config.broadcast_channel_id:
            channel = self.bot.get_channel(self.config.broadcast_channel_id)
            if channel:
                await channel.send(message)

    async def send_notification(self, target_user_id: str, message: str):
        user = await self.bot.fetch_user(int(target_user_id))
        if user:
            try:
                await user.send(message)
            except discord.Forbidden:
                pass