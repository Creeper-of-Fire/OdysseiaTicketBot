from __future__ import annotations
from datetime import datetime, timedelta
import random
import uuid
from typing import Optional, List

from .models import Bottle, UserContext, BottleConfig


class BottleEngine:
    """漂流瓶引擎"""

    def __init__(self, repository, config: BottleConfig, guild_id: int):
        self.repository = repository
        self.config = config
        self.guild_id = guild_id

    async def create_bottle(self, ctx: UserContext, content: str) -> Bottle:
        """创建漂流瓶"""
        # 检查用户是否达到最大漂流瓶数量
        user_bottles = await self.repository.get_user_bottles(self.guild_id, ctx.user_id)
        if len(user_bottles) >= self.config.max_bottles_per_user:
            raise ValueError(f"你已经达到了最大漂流瓶数量 ({self.config.max_bottles_per_user} 个)")

        # 检查用户是否在冷却期内
        last_bottle = next((b for b in user_bottles if b.created_at > datetime.now() - timedelta(seconds=self.config.cooldown_seconds)), None)
        if last_bottle:
            raise ValueError("你刚刚扔了一个漂流瓶，请稍后再试")

        # 创建漂流瓶
        bottle = Bottle(
            id=str(uuid.uuid4()),
            content=content,
            creator_id=ctx.user_id,
            created_at=datetime.now()
        )

        # 保存漂流瓶
        await self.repository.save_bottle(self.guild_id, bottle)
        return bottle

    async def find_bottle(self, ctx: UserContext) -> Optional[Bottle]:
        """查找漂流瓶"""
        # 获取所有未被找到的漂流瓶，排除自己创建的
        available_bottles = await self.repository.get_available_bottles(self.guild_id, ctx.user_id)

        if not available_bottles:
            return None

        # 随机选择一个漂流瓶
        bottle = random.choice(available_bottles)

        # 标记为已找到
        bottle.found_by = ctx.user_id
        bottle.found_at = datetime.now()
        await self.repository.update_bottle(self.guild_id, bottle)

        return bottle

    async def open_bottle(self, ctx: UserContext, bottle_id: str) -> Bottle:
        """打开漂流瓶"""
        bottle = await self.repository.get_bottle(self.guild_id, bottle_id)

        if not bottle:
            raise ValueError("漂流瓶不存在")

        if bottle.found_by != ctx.user_id:
            raise ValueError("你没有找到这个漂流瓶")

        if bottle.is_opened:
            raise ValueError("漂流瓶已经被打开了")

        # 标记为已打开
        bottle.is_opened = True
        await self.repository.update_bottle(self.guild_id, bottle)

        return bottle

    async def reply_bottle(self, ctx: UserContext, bottle_id: str, reply: str) -> Bottle:
        """回复漂流瓶"""
        bottle = await self.repository.get_bottle(self.guild_id, bottle_id)

        if not bottle:
            raise ValueError("漂流瓶不存在")

        if bottle.found_by != ctx.user_id:
            raise ValueError("你没有找到这个漂流瓶")

        if not bottle.is_opened:
            raise ValueError("请先打开漂流瓶")

        # 添加回复
        bottle.replies.append(reply)
        await self.repository.update_bottle(self.guild_id, bottle)

        return bottle

    async def get_user_bottles(self, ctx: UserContext) -> List[Bottle]:
        """获取用户的漂流瓶"""
        return await self.repository.get_user_bottles(self.guild_id, ctx.user_id)

    async def cleanup_expired_bottles(self) -> int:
        """清理过期的漂流瓶"""
        cutoff_date = datetime.now() - timedelta(days=self.config.bottle_lifetime_days)
        return await self.repository.delete_expired_bottles(self.guild_id, cutoff_date)