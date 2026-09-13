"""bottle 业务层。

操作单 guild 的 4 池子。所有写操作走 AsyncGuildDataManager.save_data()(内部 asyncio.Lock + 节流)。

对外只暴露 6 个意图清晰的方法 + 1 个回收入口。recycle_loop 在 cog 持有,不在 service 里。
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from pydantic import ValidationError

from utility.base_data_manager import AsyncGuildDataManager
from .bottle_config import BottleConfig
from .models import Bottle, GuildBottlePool

logger = logging.getLogger(__name__)


class BottleDataManager(AsyncGuildDataManager[GuildBottlePool]):
    """bot 全局单例,管理 `data/bottle_data.json` (Dict[guild_id, GuildBottlePool])。"""

    DATA_FILENAME = "bottle_data"
    GUILD_MODEL = GuildBottlePool


# ============= 错误类型 =============

class BottleError(Exception):
    """bottle 业务错误基类。"""


class BottleNotFound(BottleError):
    """瓶子不在 expected 池子。"""


class AlreadyClaimed(BottleError):
    """认领竞态失败:瓶子已被抢。"""


class HeldLimitReached(BottleError):
    """用户同时持有瓶子上限达到 max_held_per_user。"""


class PermissionDenied(BottleError):
    """权限不足。"""


# ============= Service =============

class BottleService:
    """单 guild 的 bottle 业务层。"""

    def __init__(self, data_manager: BottleDataManager, guild_id: int, config: BottleConfig):
        self.data_manager = data_manager
        self.guild_id = guild_id
        self.config = config

    def _pool(self) -> GuildBottlePool:
        return self.data_manager.ensure_guild(self.guild_id)

    # ----- 发布 -----

    async def release(
        self,
        *,
        author_id: str,
        title: str,
        content: str,
        lifetime_days: int,
        claim_deadline_days: int,
    ) -> Bottle:
        """创建瓶子并放入 available 池子。"""
        now = datetime.utcnow()
        bottle = Bottle(
            author_id=author_id,
            title=title,
            content=content,
            created_at=now,
            bottle_expires_at=now + timedelta(days=lifetime_days),
            claim_expires_at=None,
        )
        pool = self._pool()
        pool.available.append(bottle)
        await self.data_manager.save_data()
        logger.info(
            "guild %s 用户 %s 投放瓶子 %s title=%r lifetime=%dd",
            self.guild_id, author_id, bottle.id, title, lifetime_days,
        )
        return bottle

    # ----- 打捞 -----

    async def pick_random_available(self) -> Optional[Bottle]:
        """从 available 池子随机抽一个返回(不动池子,只让 UI DM 展示)。

        多个用户可以同时被打捞到同一个瓶子——只有 claim() 才挪池子,做竞态检查。
        """
        pool = self._pool()
        if not pool.available:
            return None
        return random.choice(pool.available)

    # ----- 认领 -----

    async def claim(self, *, claimer_id: str, bottle_id: str) -> Bottle:
        """认领:竞态检查 + 名额检查 + 挪池子。

        Raises:
            BottleNotFound: 瓶子不在 available(已被抢或根本不存在)。
            HeldLimitReached: 用户同时持有瓶子上限达到 max_held_per_user。
        """
        pool = self._pool()

        # 1. 竞态检查:瓶子必须还在 available 池子
        idx = next((i for i, b in enumerate(pool.available) if b.id == bottle_id), None)
        if idx is None:
            raise BottleNotFound("瓶子不在海里,可能已被抢走。")

        # 2. 名额检查:该用户 claimed 池子的数量
        held = sum(1 for b in pool.claimed if b.claimer_id == claimer_id)
        if held >= self.config.max_held_per_user:
            raise HeldLimitReached(
                f"你已持有 {held} 个瓶子,达到上限 {self.config.max_held_per_user}。"
            )

        # 3. 挪池子 + 写时间戳
        bottle = pool.available.pop(idx)
        now = datetime.utcnow()
        bottle.claimer_id = claimer_id
        bottle.claimed_at = now
        bottle.claim_expires_at = now + timedelta(days=self.config.claim_deadline_days_default)
        pool.claimed.append(bottle)
        await self.data_manager.save_data()
        logger.info(
            "guild %s 用户 %s 认领瓶子 %s claim_deadline=%s",
            self.guild_id, claimer_id, bottle.id, bottle.claim_expires_at.isoformat(),
        )
        return bottle

    # ----- 完成 -----

    async def complete(self, *, completer_id: str, bottle_id: str) -> Bottle:
        """作者确认完成(只有瓶子作者能完成)。

        Raises:
            BottleNotFound: 瓶子不在 claimed。
            PermissionDenied: 调用者不是作者。
        """
        pool = self._pool()

        idx = next(
            (i for i, b in enumerate(pool.claimed) if b.id == bottle_id),
            None,
        )
        if idx is None:
            raise BottleNotFound("瓶子不在已认领状态,无法完成。")

        bottle = pool.claimed[idx]
        if bottle.author_id != completer_id:
            raise PermissionDenied("只有发布者才能确认完成。")

        bottle.completed_at = datetime.utcnow()
        # 清理认领字段(进入 completed 后不再需要)
        # 但保留 claimer_id / claimed_at 用于历史展示
        pool.completed.append(pool.claimed.pop(idx))
        await self.data_manager.save_data()
        logger.info(
            "guild %s 用户 %s 完成瓶子 %s",
            self.guild_id, completer_id, bottle.id,
        )
        return bottle

    # ----- 手动过期(管理员) -----

    async def expire_bottle(self, *, bottle_id: str) -> Bottle:
        """从任意池子拿出,挪到 expired。

        Raises:
            BottleNotFound: 4 个池子都找不到。
        """
        pool = self._pool()
        for attr in ("available", "claimed", "completed"):
            lst = getattr(pool, attr)
            idx = next((i for i, b in enumerate(lst) if b.id == bottle_id), None)
            if idx is not None:
                bottle = lst.pop(idx)
                pool.expired.append(bottle)
                await self.data_manager.save_data()
                logger.info(
                    "guild %s 瓶子 %s 已挪到 expired (from %s)",
                    self.guild_id, bottle_id, attr,
                )
                return bottle
        raise BottleNotFound(f"瓶子 {bottle_id} 不存在。")

    # ----- 查询 -----

    async def get_my_released(self, user_id: str) -> dict[str, list[Bottle]]:
        """按池子分组返回用户(author_id)发布的所有瓶子。"""
        pool = self._pool()
        return {
            "available": [b for b in pool.available if b.author_id == user_id],
            "claimed": [b for b in pool.claimed if b.author_id == user_id],
            "completed": [b for b in pool.completed if b.author_id == user_id],
            "expired": [b for b in pool.expired if b.author_id == user_id],
        }

    async def get_my_claimed(self, user_id: str) -> dict[str, list[Bottle]]:
        """按池子分组返回用户(claimer_id)持有的瓶子(claimed + completed)。"""
        pool = self._pool()
        return {
            "claimed": [b for b in pool.claimed if b.claimer_id == user_id],
            "completed": [b for b in pool.completed if b.claimer_id == user_id],
            "expired": [b for b in pool.expired if b.claimer_id == user_id],
        }

    # ----- 回收(后台 task 调) -----

    async def recycle_stale(self) -> tuple[int, int]:
        """回收超时的瓶子。

        Returns:
            (回收的 claimed→available 数量, 回收的 available→expired 数量)
        """
        pool = self._pool()
        now = datetime.utcnow()
        reclaimed = 0
        expired = 0

        # claimed 里超时 → 挪回 available(清空认领信息)
        still_claimed: list[Bottle] = []
        for b in pool.claimed:
            if b.claim_expires_at and b.claim_expires_at < now:
                # 清空认领字段,放回海里
                b.claimer_id = None
                b.claimed_at = None
                b.claim_expires_at = None
                pool.available.append(b)
                reclaimed += 1
            else:
                still_claimed.append(b)
        pool.claimed = still_claimed

        # available 里超时 → 挪到 expired
        still_available: list[Bottle] = []
        for b in pool.available:
            if b.bottle_expires_at < now:
                pool.expired.append(b)
                expired += 1
            else:
                still_available.append(b)
        pool.available = still_available

        if reclaimed or expired:
            await self.data_manager.save_data()
            logger.info(
                "guild %s recycle: 回收 %d (回海), %d (过期)",
                self.guild_id, reclaimed, expired,
            )
        return reclaimed, expired