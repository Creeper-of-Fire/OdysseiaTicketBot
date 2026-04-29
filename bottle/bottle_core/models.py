from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


@dataclass
class UserContext:
    """用户上下文，包含用户ID和角色信息"""
    user_id: str
    role: UserRole


@dataclass
class UserRole:
    """用户角色"""
    NORMAL = "normal"
    ADMIN = "admin"


@dataclass
class Bottle:
    """漂流瓶实体"""
    id: str
    content: str
    creator_id: str
    created_at: datetime
    found_by: Optional[str] = None
    found_at: Optional[datetime] = None
    is_opened: bool = False
    replies: List[str] = field(default_factory=list)


class BottleGuild(BaseModel):
    """服务器漂流瓶数据"""
    bottles: List[Bottle] = []


@dataclass
class BottleConfig:
    """漂流瓶配置"""
    max_bottles_per_user: int = 3
    cooldown_seconds: int = 3600
    bottle_lifetime_days: int = 7