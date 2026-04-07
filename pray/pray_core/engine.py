from .models import Wish, UserContext, WishState, UserRole, WishCategory
from .ports import IWishExternalAdapter, IWishRepository


class PermissionError(Exception): pass


class StateTransitionError(Exception): pass


class WishEngine:
    SUPPORT_THRESHOLD = 5  # 达到5个支持进入讨论中

    def __init__(self, repo: IWishRepository, adapter: IWishExternalAdapter):
        self.repo = repo
        self.adapter = adapter

    async def _save_and_notify(self, wish: Wish):
        wish.update_timestamp()
        await self.repo.save(wish)

    # ================= 发起与基础交互 =================

    async def create_wish(self, user: UserContext, category: WishCategory, title: str, content: str) -> Wish:
        if user.role < UserRole.BUILDER:
            raise PermissionError("普通用户没有发起愿望的权限，您至少应当是管理员。")

        if category == WishCategory.ADMIN_HELP and user.role < UserRole.ADMIN:
            raise PermissionError("只有管理组才能发布管理组求助。")

        wish = Wish(author_id=user.user_id, category=category, title=title, content=content)

        # 状态机：管理求助直接跳过活跃状态
        if category == WishCategory.ADMIN_HELP:
            wish.state = WishState.IN_DISCUSSION
            # 触发外部副作用：创建讨论区
            wish.thread_id = await self.adapter.create_discussion_thread(wish)
        else:
            wish.state = WishState.ACTIVE

        await self._save_and_notify(wish)
        return wish

    async def support_wish(self, user: UserContext, wish_id: str) -> Wish:
        wish = await self.repo.get(wish_id)
        if not wish: raise ValueError("愿望不存在")
        if wish.state != WishState.ACTIVE:
            raise StateTransitionError("只有[活跃]状态的愿望可以被支持")

        wish.supporters.add(user.user_id)

        # 状态机：检查是否达到阈值
        if len(wish.supporters) >= self.SUPPORT_THRESHOLD:
            wish.state = WishState.IN_DISCUSSION
            wish.thread_id = await  self.adapter.create_discussion_thread(wish)
            await  self.adapter.broadcast_event(f"愿望 '{wish.title}' 已获得足够支持，开启讨论！")

        await   self._save_and_notify(wish)
        return wish

    # ================= 用户流转操作 =================

    async def claim_wish(self, user: UserContext, wish_id: str, proposal_link: str) -> Wish:
        """用户认领愿望并提交提案链接"""
        wish = await self.repo.get(wish_id)
        if wish.state != WishState.IN_DISCUSSION:
            raise StateTransitionError("只能认领[讨论中]的愿望")

        wish.claimer_id = user.user_id
        wish.proposal_link = proposal_link
        wish.state = WishState.IN_PROGRESS

        # 锁定讨论区，防止讨论分散到两个地方（可选业务逻辑）
        if wish.thread_id:
            await   self.adapter.lock_discussion_thread(wish.thread_id)

        await  self._save_and_notify(wish)
        return wish

    async def withdraw_wish(self, user: UserContext, wish_id: str) -> Wish:
        """建设者撤回自己的愿望"""
        wish = await  self.repo.get(wish_id)
        if wish.author_id != user.user_id and user.role < UserRole.ADMIN:
            raise PermissionError("只能撤回自己的愿望")
        if wish.state == WishState.CLOSED:
            raise StateTransitionError("该愿望已被关闭")

        wish.state = WishState.CLOSED
        wish.close_reason = "作者自行撤回"

        if wish.thread_id:
            await  self.adapter.lock_discussion_thread(wish.thread_id)

        await  self._save_and_notify(wish)
        return wish

    # ================= 管理员专属高级操作 =================

    async def admin_force_activate(self, user: UserContext, wish_id: str) -> Wish:
        """管理员无视支持数直接激活讨论"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        wish = await  self.repo.get(wish_id)

        if wish.state == WishState.ACTIVE:
            wish.state = WishState.IN_DISCUSSION
            wish.thread_id = await self.adapter.create_discussion_thread(wish)
            await  self._save_and_notify(wish)
        return wish

    async def admin_merge_wishes(self, user: UserContext, source_id: str, target_id: str) -> Wish:
        """管理员合并愿望"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        source = await self.repo.get(source_id)
        target = await self.repo.get(target_id)

        # 转移支持者
        target.supporters.update(source.supporters)

        # 关闭源愿望
        source.state = WishState.CLOSED
        source.close_reason = f"合并至愿望 ID: {target_id}"
        source.merged_into_id = target_id
        if source.thread_id:
            await self.adapter.lock_discussion_thread(source.thread_id)

        await  self.repo.save(target)
        await  self._save_and_notify(source)
        return source

    async def admin_resolve_proposal(self, user: UserContext, wish_id: str, is_accepted: bool) -> Wish:
        """处理提案结果"""
        if user.role < UserRole.ADMIN: raise PermissionError()
        wish = await self.repo.get(wish_id)

        if wish.state != WishState.IN_PROGRESS:
            raise StateTransitionError("只有[实现中]的愿望能处理结果")

        if is_accepted:
            wish.state = WishState.FULFILLED
            await  self.adapter.broadcast_event(f"🎉 愿望 '{wish.title}' 对应的提案已通过/完成！")
        else:
            wish.state = WishState.CLOSED
            wish.close_reason = "对应的提案被否决"

        await self._save_and_notify(wish)
        return wish
