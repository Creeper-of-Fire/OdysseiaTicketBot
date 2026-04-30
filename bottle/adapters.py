from typing import List, Optional, Any

import discord

from config_data import GuildBottleConfig
from .bottle_core.models import AnyBottle
from .bottle_core.ports import IBottleRepository, IBottleExternalAdapter
from .bottle_core.manager import BottleDataManager
from utility.base_data_manager import AsyncGuildDataManager


class AsyncJsonBottleRepository(IBottleRepository):

    def __init__(self, manager: AsyncGuildDataManager[Any], guild_id: int):
        self.manager = manager
        self.guild_id = guild_id

    async def save(self, bottle: AnyBottle):
        guild_data = self.manager.ensure_guild(self.guild_id)
        guild_data.bottles[bottle.id] = bottle
        await self.manager.save_data()

    async def get(self, bottle_id: str) -> Optional[AnyBottle]:
        guild_data = self.manager.ensure_guild(self.guild_id)
        return guild_data.bottles.get(bottle_id)

    async def get_all(self) -> List[AnyBottle]:
        guild_data = self.manager.ensure_guild(self.guild_id)
        return list(guild_data.bottles.values())


class DiscordBottleAdapter(IBottleExternalAdapter):

    def __init__(self, bot: discord.Client, config: GuildBottleConfig):
        self.bot = bot
        self.config = config

    async def send_notification(self, target_user_id: str, message: str):
        user = await self.bot.fetch_user(int(target_user_id))
        if user:
            try:
                await user.send(message)
            except discord.Forbidden:
                pass

    async def broadcast_event(self, message: str):
        if self.config.broadcast_channel_id:
            channel = self.bot.get_channel(self.config.broadcast_channel_id)
            if channel:
                await channel.send(message)
