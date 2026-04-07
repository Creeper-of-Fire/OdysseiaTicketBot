import discord
from pray.pray_core.models import Wish, WishState, UserRole, UserContext


class WishEmbed(discord.Embed):
    STATE_COLORS = {
        WishState.ACTIVE: discord.Color.blue(),
        WishState.IN_DISCUSSION: discord.Color.gold(),
        WishState.IN_PROGRESS: discord.Color.purple(),
        WishState.FULFILLED: discord.Color.green(),
        WishState.CLOSED: discord.Color.light_gray(),
        WishState.FROZEN: discord.Color.dark_grey()
    }

    def __init__(self, wish: Wish):
        super().__init__(
            title=f"【{wish.state.value}】{wish.title}",
            description=wish.content,
            color=self.STATE_COLORS.get(wish.state, discord.Color.default())
        )
        self.add_field(name="分类", value=wish.category.value, inline=True)
        self.add_field(name="发起人", value=f"<@{wish.author_id}>", inline=True)
        if wish.supporters:
            self.add_field(name="支持人数", value=f"🔥 {len(wish.supporters)}", inline=True)

        if wish.claimer_id:
            self.add_field(name="认领人", value=f"<@{wish.claimer_id}>", inline=True)
        if wish.proposal_link:
            self.add_field(name="相关提案", value=f"[点击跳转]({wish.proposal_link})", inline=True)
        if wish.close_reason:
            self.add_field(name="关闭原因", value=wish.close_reason, inline=False)

        self.set_footer(text=f"ID: {wish.id} | 更新于 {wish.updated_at.strftime('%Y-%m-%d %H:%M')}")


class WishUIFactory:
    """根据当前状态生成 View。按钮的 custom_id 携带意图和愿望ID"""

    @staticmethod
    def build_view(wish: Wish, user_ctx: UserContext) -> discord.ui.View:
        view = discord.ui.View(timeout=None)

        # 1. 支持按钮
        if wish.state == WishState.ACTIVE:
            btn_support = discord.ui.Button(
                label=f"支持 ({len(wish.supporters)})",
                style=discord.ButtonStyle.primary,
                custom_id=f"wish:support:{wish.id}"
            )
            # 如果自己已经支持过，可以禁用按钮或变灰
            if user_ctx.user_id in wish.supporters:
                btn_support.disabled = True
                btn_support.label = "已支持"
            view.add_item(btn_support)

        # 2. 认领按钮
        if wish.state == WishState.IN_DISCUSSION:
            view.add_item(discord.ui.Button(
                label="🙋 认领愿望",
                style=discord.ButtonStyle.success,
                custom_id=f"wish:claim:{wish.id}"
            ))

        # 3. 管理操作 (作者 或 管理员 可见)
        if user_ctx.role >= UserRole.ADMIN or user_ctx.user_id == wish.author_id:
            view.add_item(discord.ui.Button(
                label="⚙️ 管理",
                style=discord.ButtonStyle.secondary,
                custom_id=f"wish:manage:{wish.id}"
            ))

        return view