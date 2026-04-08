import discord
from pray.pray_core.models import (
    AnyWish, ActiveWish, DiscussionWish, InProgressWish,
    ClosedWish, FulfilledWish, UserContext
)


class WishEmbed(discord.Embed):
    STATE_COLORS = {
        "ACTIVE": discord.Color.blue(),
        "IN_DISCUSSION": discord.Color.gold(),
        "IN_PROGRESS": discord.Color.purple(),
        "FULFILLED": discord.Color.green(),
        "CLOSED": discord.Color.light_gray(),
    }

    def __init__(self, wish: AnyWish):
        # 利用 Pydantic 的 discriminator 字段 'state'
        state_str = wish.state
        super().__init__(
            title=f"【{state_str}】{wish.title}",
            description=wish.content,
            color=self.STATE_COLORS.get(state_str, discord.Color.default())
        )
        self.add_field(name="分类", value=wish.category.value, inline=True)
        self.add_field(name="发起人", value=f"<@{wish.author_id}>", inline=True)

        # 动态属性展示：利用 hasattr 检查多态属性
        if hasattr(wish, "supporters") and wish.supporters:
            self.add_field(name="支持人数", value=f"🔥 {len(wish.supporters)}", inline=True)

        if hasattr(wish, "claimer_id") and wish.claimer_id:
            self.add_field(name="认领人", value=f"<@{wish.claimer_id}>", inline=True)

        if hasattr(wish, "proposal_link") and wish.proposal_link:
            self.add_field(name="相关提案", value=f"[点击跳转]({wish.proposal_link})", inline=True)

        if isinstance(wish, ClosedWish) and wish.close_reason:
            self.add_field(name="关闭原因", value=wish.close_reason, inline=False)

        self.set_footer(text=f"ID: {wish.id} | 更新于 {wish.updated_at.strftime('%m-%d %H:%M')}")


class WishUIFactory:
    """根据当前状态生成 View。按钮的 custom_id 携带意图和愿望ID"""

    @staticmethod
    def build_view(wish: AnyWish, user_ctx: UserContext) -> discord.ui.View:
        view = discord.ui.View(timeout=None)

        # 让多态的实体告诉 UI 它可以做什么
        allowed_actions = wish.get_allowed_actions(user_ctx)

        # 1. 渲染支持按钮
        if "SUPPORT" in allowed_actions:
            view.add_item(discord.ui.Button(
                label=f"支持 ({len(wish.supporters)})",
                style=discord.ButtonStyle.primary,
                custom_id=f"wish:support:{wish.id}"
            ))
        elif hasattr(wish, "supporters") and user_ctx.user_id in wish.supporters:
            # 已支持的视觉反馈
            btn = discord.ui.Button(label="已支持", style=discord.ButtonStyle.primary, custom_id="noop")
            btn.disabled = True
            view.add_item(btn)

        # 2. 渲染认领按钮
        if "CLAIM" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="🙋 认领愿望",
                style=discord.ButtonStyle.success,
                custom_id=f"wish:claim:{wish.id}"
            ))

        # 3. 渲染管理按钮
        if "MANAGE" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="⚙️ 管理",
                style=discord.ButtonStyle.secondary,
                custom_id=f"wish:manage:{wish.id}"
            ))

        return view