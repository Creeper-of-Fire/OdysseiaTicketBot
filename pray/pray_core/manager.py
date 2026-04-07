import json
import os
from typing import List, Optional

from pydantic import BaseModel, Field

from .models import Wish
from .ports import IWishRepository
from utility.base_data_manager import AsyncJsonDataManager, AsyncGuildDataManager


class GuildWishData(BaseModel):
    """
    每个服务器独立的愿望数据容器
    """
    wishes: dict[str, Wish] = Field(default_factory=dict)

class WishDataManager(AsyncGuildDataManager[GuildWishData]):
    DATA_FILENAME = "wish_system"
    GUILD_MODEL = GuildWishData

    # 获取特定愿望的快捷方法
    def get_wish(self, guild_id: int, wish_id: str) -> Optional[Wish]:
        guild_data = self.ensure_guild(guild_id)
        return guild_data.wishes.get(wish_id)