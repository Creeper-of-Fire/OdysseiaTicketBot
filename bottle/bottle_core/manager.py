from pydantic import BaseModel, Field

from .models import AnyBottle
from utility.base_data_manager import AsyncGuildDataManager


class GuildBottleData(BaseModel):
    bottles: dict[str, AnyBottle] = Field(default_factory=dict)


class BottleDataManager(AsyncGuildDataManager[GuildBottleData]):
    DATA_FILENAME = "bottle_wish_system"
    GUILD_MODEL = GuildBottleData
