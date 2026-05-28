from __future__ import annotations

from pydantic import BaseModel, Field

from utility.base_data_manager import AsyncGuildDataManager


class ComplaintChannelMeta(BaseModel):
    """投诉频道的元数据，关联频道与投诉人和类型。"""

    complainant_id: int
    type_id: str


class GuildComplaintData(BaseModel):
    """单个服务器的投诉频道注册表。"""

    channels: dict[str, ComplaintChannelMeta] = Field(default_factory=dict)


class ComplaintChannelManager(AsyncGuildDataManager[GuildComplaintData]):
    """管理投诉频道的注册、查询和移除。"""
    DATA_FILENAME = "complaint_channels"
    GUILD_MODEL = GuildComplaintData

    def register_channel(
        self, guild_id: int, channel_id: int, meta: ComplaintChannelMeta,
    ) -> None:
        """注册一个新的投诉频道及其元数据。"""
        guild = self.ensure_guild(guild_id)
        guild.channels[str(channel_id)] = meta

    def get_channel_meta(
        self, guild_id: int, channel_id: int,
    ) -> ComplaintChannelMeta | None:
        """获取指定频道的元数据，不存在则返回 None。"""
        guild = self.get_guild(guild_id)
        if guild is None:
            return None
        return guild.channels.get(str(channel_id))

    def remove_channel(self, guild_id: int, channel_id: int) -> None:
        """移除指定频道的注册记录。"""
        guild = self.get_guild(guild_id)
        if guild is not None:
            guild.channels.pop(str(channel_id), None)
