"""bottle 系统 toml 配置 schema。

每个 guild 一份 `data/bottle_{guild_id}.toml`,所有字段必填、无 default。
缺字段 → pydantic ValidationError 抛到 cog setup → 该 guild 功能禁用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BottleConfig(BaseModel):
    """单 guild bottle 配置。

    面板位置不配置:bot 通过 `interaction.channel_id` 自动知道交互来自哪个面板,
    因此允许在任意频道发任意数量的 panel。
    """

    # 单人同时持有的瓶子上限(claimed 池子里)。
    # bot 不猜这个值,admin 必须主动配置。
    max_held_per_user: int = Field(..., ge=1, description="单人同时持有的瓶子上限")

    # 发布 modal 的默认值:海里漂多久 / 认领后多久不完成回海里。
    # 用户在 modal 里可以临时覆盖(下面 panel.py 实现)。
    bottle_lifetime_days_default: int = Field(..., ge=1, description="海里默认过期天数")
    claim_deadline_days_default: int = Field(..., ge=1, description="认领后默认完成时限(天)")