from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum
from typing import Set, Optional, Literal, Union, Annotated

from pydantic import BaseModel, Field, ConfigDict


class UserRole(int, Enum):
    NORMAL = 1
    ADMIN = 3


class UserContext(BaseModel):
    user_id: str
    role: UserRole


class BaseBottle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    author_id: str
    title: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def update_timestamp(self):
        self.updated_at = datetime.utcnow()

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = set()
        if user.role >= UserRole.ADMIN or user.user_id == self.author_id:
            actions.add("MANAGE")
        return actions


class AvailableBottle(BaseBottle):
    state: Literal["AVAILABLE"] = "AVAILABLE"
    claimer_ids: Set[str] = Field(default_factory=set)

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = super().get_allowed_actions(user)
        if user.user_id != self.author_id:
            actions.add("CLAIM")
        return actions


class ClaimedBottle(BaseBottle):
    state: Literal["CLAIMED"] = "CLAIMED"
    claimer_ids: Set[str]

    def get_allowed_actions(self, user: UserContext) -> Set[str]:
        actions = super().get_allowed_actions(user)
        if user.user_id in self.claimer_ids:
            actions.add("UNCLAIM")
        if user.user_id == self.author_id or user.role >= UserRole.ADMIN:
            actions.add("COMPLETE")
        return actions


class CompletedBottle(BaseBottle):
    state: Literal["COMPLETED"] = "COMPLETED"
    claimer_ids: Set[str]
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class ExpiredBottle(BaseBottle):
    state: Literal["EXPIRED"] = "EXPIRED"
    claimer_ids: Set[str] = Field(default_factory=set)


AnyBottle = Annotated[
    Union[AvailableBottle, ClaimedBottle, CompletedBottle, ExpiredBottle],
    Field(discriminator="state")
]
