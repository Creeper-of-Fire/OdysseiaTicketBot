from __future__ import annotations

from pydantic import BaseModel, Field

from utility.base_data_manager import AsyncGuildDataManager


class ComplaintChannelMeta(BaseModel):
    complainant_id: int
    type_id: str
    ticket_number: int | None = None


class GuildComplaintData(BaseModel):
    channels: dict[str, ComplaintChannelMeta] = Field(default_factory=dict)


class ComplaintChannelManager(AsyncGuildDataManager[GuildComplaintData]):
    DATA_FILENAME = "complaint_channels"
    GUILD_MODEL = GuildComplaintData

    def register_channel(
        self, guild_id: int, channel_id: int, meta: ComplaintChannelMeta,
    ) -> None:
        guild = self.ensure_guild(guild_id)
        guild.channels[str(channel_id)] = meta

    def get_channel_meta(
        self, guild_id: int, channel_id: int,
    ) -> ComplaintChannelMeta | None:
        guild = self.get_guild(guild_id)
        if guild is None:
            return None
        return guild.channels.get(str(channel_id))

    def remove_channel(self, guild_id: int, channel_id: int) -> None:
        guild = self.get_guild(guild_id)
        if guild is not None:
            guild.channels.pop(str(channel_id), None)
