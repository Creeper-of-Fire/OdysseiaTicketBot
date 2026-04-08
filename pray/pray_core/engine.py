from .models import AnyWish, UserContext, UserRole, WishCategory, DiscussionWish, ActiveWish, ClosedWish, FulfilledWish, InProgressWish
from .ports import IWishExternalAdapter, IWishRepository


class PermissionError(Exception): pass


class StateTransitionError(Exception): pass


class WishEngine:
    SUPPORT_THRESHOLD = 5  # 达到5个支持进入讨论中

    def __init__(self, repo: IWishRepository, adapter: IWishExternalAdapter):
        self.repo = repo
        self.adapter = adapter

    async def _save_and_notify(self, wish: AnyWish):
        wish.update_timestamp()
        await self.repo.save(wish)

    # ================= 发起与基础交互 =================

    async def create_wish(self, user: UserContext, category: WishCategory, title: str, content: str) -> AnyWish:
        if user.role < UserRole.BUILDER:
            raise PermissionError("权限不足。")
        if category == WishCategory.ADMIN_HELP and user.role < UserRole.ADMIN:
            raise PermissionError("只有管理组能发布该类别的愿望。")

        base_data = {
            "author_id": user.user_id,
            "category": category,
            "title": title,
            "content": content
        }

        if category == WishCategory.ADMIN_HELP:
            # 特殊类别直接进入讨论态
            wish = DiscussionWish(**base_data)
            wish.thread_id = await self.adapter.create_discussion_thread(wish)
        else:
            # 普通愿望进入活跃态
            wish = ActiveWish(**base_data)

        await self._save_and_notify(wish)
        return wish

    async def support_wish(self, user: UserContext, wish_id: str) -> AnyWish:
        wish = await self.repo.get(wish_id)

        # 1. 类型约束代替状态枚举校验
        if not isinstance(wish, ActiveWish):
            raise StateTransitionError("当前状态无法【支持】。可能是愿望已进入讨论阶段或已关闭。")

        # 2. 调用领域模型内部的状态机转移
        new_wish = wish.support(user.user_id, self.SUPPORT_THRESHOLD)

        # 3. 如果对象类型发生了变化，说明发生了状态转移，触发外部副作用
        if isinstance(new_wish, DiscussionWish):
            new_wish.thread_id = await self.adapter.create_discussion_thread(new_wish)
            await self.adapter.broadcast_event(f"愿望 '{new_wish.title}' 开启讨论！")

        await self._save_and_notify(new_wish)
        return new_wish

    # ================= 用户流转操作 =================

    async def claim_wish(self, user: UserContext, wish_id: str, proposal_link: str) -> AnyWish:
        wish = await self.repo.get(wish_id)

        if not isinstance(wish, DiscussionWish):
            raise StateTransitionError("只能认领【讨论中】的愿望。")

        new_wish = wish.claim(user.user_id, proposal_link)

        if new_wish.thread_id:
            await self.adapter.lock_discussion_thread(new_wish.thread_id)

        await self._save_and_notify(new_wish)
        return new_wish

    async def withdraw_wish(self, user: UserContext, wish_id: str) -> AnyWish:
        wish = await self.repo.get(wish_id)
        if not wish: raise ValueError("不存在")

        # 权限检查：只有作者或管理员能关闭
        if wish.author_id != user.user_id and user.role < UserRole.ADMIN:
            raise PermissionError("无权操作此愿望。")

        if isinstance(wish, (ClosedWish, FulfilledWish)):
            raise StateTransitionError("愿望已是最终状态，无法撤回。")

        # 转换为关闭态，保留大部分元数据
        new_wish = ClosedWish(
            close_reason="作者自行撤回" if user.user_id == wish.author_id else "由管理员关闭",
            **wish.model_dump(exclude={"state", "close_reason"})
        )

        if getattr(new_wish, "thread_id", None):
            await self.adapter.lock_discussion_thread(new_wish.thread_id)

        await self._save_and_notify(new_wish)
        return new_wish

    # ================= 管理员专属高级操作 =================

    async def admin_force_activate(self, user: UserContext, wish_id: str) -> AnyWish:
        """无视支持阈值强行开启讨论"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        wish = await self.repo.get(wish_id)

        if not isinstance(wish, ActiveWish):
            raise StateTransitionError("只有活跃状态的愿望可以被强制激活。")

        new_wish = DiscussionWish(**wish.model_dump(exclude={"state"}))
        new_wish.thread_id = await self.adapter.create_discussion_thread(new_wish)

        await self._save_and_notify(new_wish)
        return new_wish

    async def admin_merge_wishes(self, user: UserContext, source_id: str, target_id: str) -> AnyWish:
        """将 source 合并到 target"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        source = await self.repo.get(source_id)
        target = await self.repo.get(target_id)

        if isinstance(source, (ClosedWish, FulfilledWish)):
            raise StateTransitionError("已关闭的愿望不能再合并。")

        # 逻辑：转移支持者到目标愿望（如果目标支持支持者的话）
        if hasattr(target, "supporters") and hasattr(source, "supporters"):
            target.supporters.update(source.supporters)
            await self.repo.save(target)

        # 关闭源愿望
        new_source = ClosedWish(
            close_reason=f"已合并至 ID: {target_id}",
            merged_into_id=target_id,
            **source.model_dump(exclude={"state", "close_reason", "merged_into_id"})
        )

        if getattr(new_source, "thread_id", None):
            await self.adapter.lock_discussion_thread(new_source.thread_id)

        await self._save_and_notify(new_source)
        return new_source

    async def admin_resolve_proposal(self, user: UserContext, wish_id: str, is_accepted: bool) -> AnyWish:
        """决定提案最终生死"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        wish = await self.repo.get(wish_id)

        if not isinstance(wish, InProgressWish):
            raise StateTransitionError("只有实现中的愿望可以结算。")

        if is_accepted:
            new_wish = FulfilledWish(**wish.model_dump(exclude={"state"}))
            await self.adapter.broadcast_event(f"🎉 愿望 '{wish.title}' 已达成！")
        else:
            new_wish = ClosedWish(
                close_reason="相关提案未通过审核",
                **wish.model_dump(exclude={"state", "close_reason"})
            )

        await self._save_and_notify(new_wish)
        return new_wish
