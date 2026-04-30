from __future__ import annotations
from datetime import datetime, timedelta
from typing import List

from .models import (
    AnyBottle, UserContext, UserRole,
    AvailableBottle, ClaimedBottle, CompletedBottle, ExpiredBottle
)
from .ports import IBottleRepository, IBottleExternalAdapter


class PermissionError(Exception): pass


class StateTransitionError(Exception): pass


class BottleEngine:

    def __init__(self, repo: IBottleRepository, adapter: IBottleExternalAdapter):
        self.repo = repo
        self.adapter = adapter

    async def _save_and_notify(self, bottle: AnyBottle):
        bottle.update_timestamp()
        await self.repo.save(bottle)

    async def create_bottle(self, user: UserContext, title: str, content: str) -> AvailableBottle:
        bottle = AvailableBottle(
            author_id=user.user_id,
            title=title,
            content=content
        )
        await self._save_and_notify(bottle)
        return bottle

    async def claim_bottle(self, user: UserContext, bottle_id: str) -> AnyBottle:
        bottle = await self.repo.get(bottle_id)

        if not isinstance(bottle, AvailableBottle):
            raise StateTransitionError("当前状态无法认领。")
        if user.user_id == bottle.author_id:
            raise StateTransitionError("不能认领自己的心愿。")
        if user.user_id in bottle.claimer_ids:
            raise StateTransitionError("你已经认领过这个心愿了。")

        bottle.claimer_ids.add(user.user_id)
        new_bottle = ClaimedBottle(
            claimer_ids=bottle.claimer_ids,
            **bottle.model_dump(exclude={"state", "claimer_ids"})
        )

        await self.adapter.send_notification(
            bottle.author_id,
            f"你的心愿「{bottle.title}」已被 <@{user.user_id}> 认领！"
        )

        await self._save_and_notify(new_bottle)
        return new_bottle

    async def unclaim_bottle(self, user: UserContext, bottle_id: str) -> AnyBottle:
        bottle = await self.repo.get(bottle_id)

        if not isinstance(bottle, ClaimedBottle):
            raise StateTransitionError("当前状态无法取消认领。")
        if user.user_id not in bottle.claimer_ids:
            raise PermissionError("你没有认领这个心愿。")

        bottle.claimer_ids.discard(user.user_id)

        if len(bottle.claimer_ids) == 0:
            new_bottle = AvailableBottle(
                **bottle.model_dump(exclude={"state", "claimer_ids"})
            )
        else:
            new_bottle = bottle

        await self._save_and_notify(new_bottle)
        return new_bottle

    async def complete_bottle(self, user: UserContext, bottle_id: str) -> CompletedBottle:
        bottle = await self.repo.get(bottle_id)

        if not isinstance(bottle, ClaimedBottle):
            raise StateTransitionError("只有已认领的心愿可以完成。")
        if user.user_id != bottle.author_id and user.role < UserRole.ADMIN:
            raise PermissionError("只有发布者才能确认完成。")

        new_bottle = CompletedBottle(
            completed_at=datetime.utcnow(),
            **bottle.model_dump(exclude={"state", "completed_at"})
        )

        for claimer_id in bottle.claimer_ids:
            await self.adapter.send_notification(
                claimer_id,
                f"心愿「{bottle.title}」已被发布者确认为已完成！感谢你的参与。"
            )

        await self._save_and_notify(new_bottle)
        return new_bottle

    async def expire_bottle(self, user: UserContext, bottle_id: str) -> ExpiredBottle:
        if user.role < UserRole.ADMIN:
            raise PermissionError("只有管理员可以强制过期。")
        bottle = await self.repo.get(bottle_id)

        if isinstance(bottle, (CompletedBottle, ExpiredBottle)):
            raise StateTransitionError("已是最终状态。")

        claimer_ids = getattr(bottle, "claimer_ids", set())
        new_bottle = ExpiredBottle(
            claimer_ids=claimer_ids,
            **bottle.model_dump(exclude={"state", "claimer_ids", "completed_at"})
        )

        await self._save_and_notify(new_bottle)
        return new_bottle

    async def get_user_bottles(self, user: UserContext) -> List[AnyBottle]:
        all_bottles = await self.repo.get_all()
        return [b for b in all_bottles if b.author_id == user.user_id]

    async def get_available_bottles(self, user: UserContext) -> List[AnyBottle]:
        all_bottles = await self.repo.get_all()
        return [
            b for b in all_bottles
            if isinstance(b, AvailableBottle) and b.author_id != user.user_id
        ]
