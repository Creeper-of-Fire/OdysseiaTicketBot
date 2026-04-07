from enum import Enum
from typing import Set, Optional
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
import uuid


# --- 枚举定义 ---

class WishState(str, Enum):
    ACTIVE = "活跃"
    IN_DISCUSSION = "讨论中"
    IN_PROGRESS = "实现中"
    FROZEN = "已冻结"
    CLOSED = "已关闭"
    FULFILLED = "已实现"


class UserRole(int, Enum):
    NORMAL = 1  # 普通用户
    BUILDER = 2  # 社区建设者
    ADMIN = 3  # 管理组


class WishCategory(str, Enum):
    BOT_FEATURE = "Bot功能"
    COMMUNITY = "社区建设"
    SYSTEM = "制度改进"
    ADMIN_HELP = "管理组求助"  # 特殊分区


# --- 数据模型 ---

class UserContext(BaseModel):
    """用于传递当前操作用户的上下文信息"""
    user_id: str
    role: UserRole


class Wish(BaseModel):
    """许愿核心实体"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    category: WishCategory
    title: str
    content: str

    # 状态与时间
    state: WishState = WishState.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 交互数据
    supporters: Set[str] = Field(default_factory=set)  # 使用Set保证支持者不重复
    thread_id: Optional[str] = None  # 关联的Discord讨论区ID

    # 提案与流转数据
    claimer_id: Optional[str] = None  # 认领人ID
    proposal_link: Optional[str] = None  # 关联的提案链接
    close_reason: Optional[str] = None  # 关闭原因
    merged_into_id: Optional[str] = None  # 被合并到的目标愿望ID

    def update_timestamp(self):
        self.updated_at = datetime.utcnow()