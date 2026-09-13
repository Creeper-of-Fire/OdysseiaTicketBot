"""bottle 数据模型。

设计原则:
- 状态不是字段,是位置(物理位置 = 当前所在的池子)。
- 4 个池子:available(海里) / claimed(被捞走) / completed / expired。
- 不引入 state pattern / discriminated union,纯 list-of-bottle。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Bottle(BaseModel):
    """单条瓶子记录。

    时间戳:
    - created_at / bottle_expires_at: 由 release() 写入,前者创建时间,后者海里过期时间。
    - claimed_at / claim_expires_at: 由 claim() 写入,前者认领时间,后者认领超时回海里的时间。
    - completed_at: 由 complete() 写入。

    竞态检查靠 claim() 内部"读 → 校验 → 写"在 AsyncGuildDataManager 的 asyncio.Lock 内完成。
    """

    id: str = Field(default_factory=_new_id)
    author_id: str
    title: str
    content: str

    claimer_id: str | None = None
    created_at: datetime = Field(default_factory=_now)
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    bottle_expires_at: datetime
    claim_expires_at: datetime | None = None


class GuildBottlePool(BaseModel):
    """单 guild 的 4 个池子。"""

    available: list[Bottle] = Field(default_factory=list)
    claimed: list[Bottle] = Field(default_factory=list)
    completed: list[Bottle] = Field(default_factory=list)
    expired: list[Bottle] = Field(default_factory=list)