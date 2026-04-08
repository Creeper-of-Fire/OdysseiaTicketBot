import uuid
from datetime import datetime
from enum import Enum
from typing import Set, Optional, Literal, Union, Annotated

from pydantic import BaseModel, Field, ConfigDict


class UserRole(int, Enum):
    NORMAL = 1  # 普通用户
    BUILDER = 2  # 社区建设者
    ADMIN = 3  # 管理组


class WishCategory(str, Enum):
    BOT_FEATURE = "Bot功能"
    COMMUNITY = "社区建设"
    SYSTEM = "制度改进"
    ADMIN_HELP = "管理组求助"  # 特殊分区


class UserContext(BaseModel):
    """用于传递当前操作用户的上下文信息"""
    user_id: str
    role: UserRole


# ================= 状态模式基类 =================
class BaseWish(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    category: WishCategory
    title: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # 抽取通用能力：告诉外部当前状态允许该用户做什么（UI 的真正桥接点）
    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = set()
        if user.role >= UserRole.ADMIN or user.user_id == self.author_id:
            actions.add("MANAGE")
        return actions

    def update_timestamp(self):
        self.updated_at = datetime.utcnow()


# ================= 具体状态类 =================
class ActiveWish(BaseWish):
    state: Literal["ACTIVE"] = "ACTIVE"
    supporters: Set[str] = Field(default_factory=set)

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = super().get_allowed_actions(user)
        if user.user_id not in self.supporters:
            actions.add("SUPPORT")
        return actions

    # 业务逻辑内聚：支持动作可能导致状态变更（返回新类实例）
    def support(self, user_id: str, threshold: int) -> Union['ActiveWish', 'DiscussionWish']:
        self.supporters.add(user_id)
        if len(self.supporters) >= threshold:
            # 发生状态转移：保留共有数据，生成新状态实例
            return DiscussionWish(**self.model_dump(exclude={"state"}))
        return self


class DiscussionWish(BaseWish):
    state: Literal["IN_DISCUSSION"] = "IN_DISCUSSION"
    supporters: Set[str] = Field(default_factory=set)
    thread_id: Optional[str] = None

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = super().get_allowed_actions(user)
        actions.add("CLAIM")
        return actions

    def claim(self, claimer_id: str, link: str) -> 'InProgressWish':
        return InProgressWish(
            claimer_id=claimer_id,
            proposal_link=link,
            **self.model_dump(exclude={"state"})
        )


class InProgressWish(BaseWish):
    state: Literal["IN_PROGRESS"] = "IN_PROGRESS"
    supporters: Set[str] = Field(default_factory=set)
    thread_id: Optional[str] = None
    claimer_id: str
    proposal_link: str

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        return super().get_allowed_actions(user)


class ClosedWish(BaseWish):
    state: Literal["CLOSED"] = "CLOSED"
    close_reason: str
    thread_id: Optional[str] = None
    merged_into_id: Optional[str] = None


class FulfilledWish(BaseWish):
    state: Literal["FULFILLED"] = "FULFILLED"
    thread_id: Optional[str] = None
    claimer_id: str
    proposal_link: str


# ================= 多态序列化类型 =================
# 任何地方使用 AnyWish，Pydantic 会自动根据 "state" 字段实例化为正确的子类
AnyWish = Annotated[
    Union[ActiveWish, DiscussionWish, InProgressWish, ClosedWish, FulfilledWish],
    Field(discriminator="state")
]
