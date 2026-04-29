from typing import TYPE_CHECKING
import discord

from pray.pray_core.models import (
    AnyWish, ActiveWish, DiscussionWish, InProgressWish,
    ClosedWish, FulfilledWish, UserContext
)

if TYPE_CHECKING:
    from ..WishSystemCog import WishSystemCog
    from main import TicketBot

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


class WishInteractionView(discord.ui.View):
    """
    持久化视图：负责处理所有愿望卡片的交互。
    timeout=None 确保机器人重启后依然有效。
    """

    def __init__(self,bot : 'TicketBot', wish_id: str = None):
        super().__init__(timeout=None)
        # 如果是新生成的视图，我们可以动态添加按钮
        # 如果是从 bot.add_view 调用的（全局监听），则不需要 wish_id
        self.wish_id = wish_id
        self.bot = bot

    @staticmethod
    def _parse_id(custom_id: str) -> str:
        return custom_id.split(":")[-1]

    async def _get_context_and_engine(self, interaction: discord.Interaction):
        """快捷获取 Cog 引用"""
        cog: 'WishSystemCog' = self.bot.get_cog("WishSystemCog")
        engine = cog._get_engine(interaction.guild_id)
        ctx = cog._get_user_context(interaction)
        return cog, engine, ctx

    # 使用装饰器定义按钮。custom_id 必须包含愿望 ID
    # 这里我们采用一种“工厂模式”来生成带 ID 的按钮，
    # 或者在 View 级拦截所有 Interaction。

    @discord.ui.button(label="支持", style=discord.ButtonStyle.primary, custom_id="wish:support:base")
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = self._parse_id(interaction.data["custom_id"])
        _, engine, ctx = await self._get_context_and_engine(interaction)

        new_wish = await engine.support_wish(ctx, wish_id)
        await interaction.response.edit_message(
            embed=WishEmbed(new_wish),
            view=WishUIFactory.build_view(new_wish, ctx)
        )

    @discord.ui.button(label="认领", style=discord.ButtonStyle.success, custom_id="wish:claim:base")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = self._parse_id(interaction.data["custom_id"])
        cog, engine, ctx = await self._get_context_and_engine(interaction)
        await cog._show_claim_modal(interaction, engine, ctx, wish_id)

    @discord.ui.button(label="管理", style=discord.ButtonStyle.secondary, custom_id="wish:manage:base")
    async def manage_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = self._parse_id(interaction.data["custom_id"])
        cog, engine, ctx = await self._get_context_and_engine(interaction)
        await cog._show_manage_panel(interaction, engine, ctx, wish_id)

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