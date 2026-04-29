from __future__ import annotations
import json
import os
from datetime import datetime
from typing import List, Optional

from utility.base_data_manager import AsyncGuildDataManager
from .models import Bottle, BottleGuild

class BottleRepository(AsyncGuildDataManager[BottleGuild]):
    """基于 AsyncGuildDataManager 的漂流瓶存储库"""
    DATA_FILENAME = "bottles"
    GUILD_MODEL = BottleGuild

    async def save_bottle(self, guild_id: int, bottle: Bottle):
        """保存漂流瓶"""
        guild_data = self.ensure_guild(guild_id)
        # 检查是否已存在
        existing_index = next((i for i, b in enumerate(guild_data.bottles) if b.id == bottle.id), -1)
        if existing_index >= 0:
            guild_data.bottles[existing_index] = bottle
        else:
            guild_data.bottles.append(bottle)
        await self.save_data()

    async def update_bottle(self, guild_id: int, bottle: Bottle):
        """更新漂流瓶"""
        await self.save_bottle(guild_id, bottle)

    async def get_bottle(self, guild_id: int, bottle_id: str) -> Optional[Bottle]:
        """根据ID获取漂流瓶"""
        guild_data = self.get_guild(guild_id)
        if not guild_data:
            return None
        return next((b for b in guild_data.bottles if b.id == bottle_id), None)

    async def get_user_bottles(self, guild_id: int, user_id: str) -> List[Bottle]:
        """获取用户创建的漂流瓶"""
        guild_data = self.get_guild(guild_id)
        if not guild_data:
            return []
        return [b for b in guild_data.bottles if b.creator_id == user_id]

    async def get_available_bottles(self, guild_id: int, exclude_user_id: str) -> List[Bottle]:
        """获取可用的漂流瓶（未被找到且不是用户自己创建的）"""
        guild_data = self.get_guild(guild_id)
        if not guild_data:
            return []
        return [b for b in guild_data.bottles if b.found_by is None and b.creator_id != exclude_user_id]

    async def delete_expired_bottles(self, guild_id: int, cutoff_date: datetime) -> int:
        """删除过期的漂流瓶"""
        guild_data = self.get_guild(guild_id)
        if not guild_data:
            return 0
        expired_count = 0
        valid_bottles = []
        for b in guild_data.bottles:
            if b.created_at < cutoff_date:
                expired_count += 1
            else:
                valid_bottles.append(b)
        guild_data.bottles = valid_bottles
        await self.save_data()
        return expired_count