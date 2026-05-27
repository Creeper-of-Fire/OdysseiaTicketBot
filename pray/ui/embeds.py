from typing import TYPE_CHECKING
import discord

from pray.pray_core.engine import StateTransitionError, PermissionError
from pray.pray_core.models import (
    AnyWish, ActiveWish, DiscussionWish, InProgressWish,
    ClosedWish, FrozenWish, FulfilledWish, UserContext, UserRole
)

if TYPE_CHECKING:
    from ..WishSystemCog import WishSystemCog


class WishEmbed(discord.Embed):
    STATE_COLORS = {
        "ACTIVE": discord.Color.blue(),
        "IN_DISCUSSION": discord.Color.gold(),
        "IN_PROGRESS": discord.Color.purple(),
        "FROZEN": discord.Color.dark_gray(),
        "FULFILLED": discord.Color.green(),
        "CLOSED": discord.Color.light_gray(),
    }

    def __init__(self, wish: AnyWish):
        state_str = wish.state
        super().__init__(
            title=f"【{state_str}】{wish.title}",
            description=wish.content,
            color=self.STATE_COLORS.get(state_str, discord.Color.default())
        )
        self.add_field(name="分类", value=wish.category.value, inline=True)
        self.add_field(name="发起人", value=f"<@{wish.author_id}>", inline=True)

        if hasattr(wish, "supporters") and wish.supporters:
            self.add_field(name="支持人数", value=f"🔥 {len(wish.supporters)}", inline=True)

        if hasattr(wish, "claimer_id") and wish.claimer_id:
            self.add_field(name="认领人", value=f"<@{wish.claimer_id}>", inline=True)

        if hasattr(wish, "proposal_link") and wish.proposal_link:
            self.add_field(name="相关提案", value=f"[点击跳转]({wish.proposal_link})", inline=True)

        if isinstance(wish, FrozenWish) and wish.freeze_reason:
            self.add_field(name="冻结原因", value=wish.freeze_reason, inline=False)

        if isinstance(wish, ClosedWish) and wish.close_reason:
            self.add_field(name="关闭原因", value=wish.close_reason, inline=False)

        self.set_footer(text=f"ID: {wish.id} | 更新于 {wish.updated_at.strftime('%m-%d %H:%M')}")

    @staticmethod
    def extract_wish_id(embed: discord.Embed) -> str:
        """从 embed footer 提取 wish_id。格式: 'ID: {uuid} | 更新于 ...'"""
        return embed.footer.text.split("ID: ")[1].split(" |")[0]


class WishCardView(discord.ui.View):
    """持久化视图：处理愿望卡片的所有按钮交互。

    通过 bot.add_view(WishCardView()) 全局注册，bot 重启后按钮仍然可用。
    wish_id 从交互消息的 embed footer 中提取。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @classmethod
    def for_wish(cls, wish: AnyWish, user_ctx: UserContext) -> "WishCardView":
        """根据愿望状态和用户角色构建仅含合法按钮的视图。"""
        view = cls()
        allowed = wish.get_allowed_actions(user_ctx)

        # 更新支持按钮的标签为含计数
        if hasattr(wish, "supporters") and wish.supporters:
            for child in view.children:
                if child.custom_id == "wish:support":
                    child.label = f"支持 ({len(wish.supporters)})"
                    break

        # 移除不适用的按钮
        remove_ids = set()
        if "SUPPORT" not in allowed:
            remove_ids.add("wish:support")
        if "CLAIM" not in allowed:
            remove_ids.add("wish:claim")
        if "REOPEN" not in allowed:
            remove_ids.add("wish:reopen")
        if "MANAGE" not in allowed:
            remove_ids.add("wish:manage")

        for item in list(view.children):
            if item.custom_id in remove_ids:
                view.remove_item(item)

        # 已支持的视觉反馈
        if "SUPPORT" not in allowed and hasattr(wish, "supporters") and user_ctx.user_id in wish.supporters:
            btn = discord.ui.Button(
                label="已支持", style=discord.ButtonStyle.primary,
                custom_id="wish:noop", disabled=True, row=0
            )
            view.add_item(btn)

        return view

    # ---- 按钮回调 ----

    @discord.ui.button(label="支持", style=discord.ButtonStyle.primary, custom_id="wish:support", row=0)
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = WishEmbed.extract_wish_id(interaction.message.embeds[0])
        cog: "WishSystemCog" = interaction.client.get_cog("WishSystemCog")
        engine = cog._get_engine(interaction.guild_id)
        ctx = cog._get_user_context(interaction)
        try:
            new_wish = await engine.support_wish(ctx, wish_id)
            await interaction.response.edit_message(
                embed=WishEmbed(new_wish),
                view=WishCardView.for_wish(new_wish, ctx)
            )
        except (StateTransitionError, PermissionError, ValueError) as e:
            await interaction.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)

    @discord.ui.button(label="认领", style=discord.ButtonStyle.success, custom_id="wish:claim", row=0)
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = WishEmbed.extract_wish_id(interaction.message.embeds[0])
        cog: "WishSystemCog" = interaction.client.get_cog("WishSystemCog")
        engine = cog._get_engine(interaction.guild_id)
        ctx = cog._get_user_context(interaction)
        modal = cog.ClaimModal(engine, ctx, wish_id, interaction.message)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="重新开启", style=discord.ButtonStyle.primary, custom_id="wish:reopen", row=1)
    async def reopen_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = WishEmbed.extract_wish_id(interaction.message.embeds[0])
        cog: "WishSystemCog" = interaction.client.get_cog("WishSystemCog")
        engine = cog._get_engine(interaction.guild_id)
        ctx = cog._get_user_context(interaction)
        try:
            new_wish = await engine.admin_reopen_wish(ctx, wish_id)
            await interaction.response.edit_message(
                embed=WishEmbed(new_wish),
                view=WishCardView.for_wish(new_wish, ctx)
            )
        except (StateTransitionError, PermissionError, ValueError) as e:
            await interaction.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)

    @discord.ui.button(label="管理", style=discord.ButtonStyle.secondary, custom_id="wish:manage", row=1)
    async def manage_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        wish_id = WishEmbed.extract_wish_id(interaction.message.embeds[0])
        cog: "WishSystemCog" = interaction.client.get_cog("WishSystemCog")
        engine = cog._get_engine(interaction.guild_id)
        ctx = cog._get_user_context(interaction)

        await interaction.response.defer()

        wish = await engine.repo.get(wish_id)
        if not wish:
            await interaction.followup.send("愿望不存在", ephemeral=True)
            return

        view = WishManageView(
            wish_id=wish_id, cog=cog, engine=engine, ctx=ctx,
            original_message=interaction.message, wish=wish
        )
        await interaction.followup.send("请选择管理操作：", view=view, ephemeral=True)


class WishManageView(discord.ui.View):
    """管理面板视图。非持久化（timeout=300），因为是 ephemeral 消息。"""

    def __init__(self, wish_id: str, cog, engine, ctx,
                 original_message: discord.Message, wish: AnyWish):
        super().__init__(timeout=300)
        self._wish_id = wish_id
        self._cog = cog
        self._engine = engine
        self._ctx = ctx
        self._original_message = original_message

        # 撤回/关闭 (非终态)
        if not isinstance(wish, (ClosedWish, FulfilledWish)):
            btn = discord.ui.Button(label="撤回/关闭愿望", style=discord.ButtonStyle.danger, row=0)
            btn.callback = self._withdraw
            self.add_item(btn)

        # ActiveWish 管理员
        if isinstance(wish, ActiveWish) and ctx.role >= UserRole.ADMIN:
            btn = discord.ui.Button(label="强制开启讨论", style=discord.ButtonStyle.primary, row=0)
            btn.callback = self._force_activate
            self.add_item(btn)

            btn = discord.ui.Button(label="强制关闭(含理由)", style=discord.ButtonStyle.danger, row=1)
            btn.callback = self._force_close_modal_cb
            self.add_item(btn)

        # DiscussionWish 管理员
        if isinstance(wish, DiscussionWish) and ctx.role >= UserRole.ADMIN:
            btn = discord.ui.Button(label="强制关闭(含理由)", style=discord.ButtonStyle.danger, row=0)
            btn.callback = self._force_close_modal_cb
            self.add_item(btn)

            btn = discord.ui.Button(label="强制认领", style=discord.ButtonStyle.primary, row=0)
            btn.callback = self._force_claim_modal_cb
            self.add_item(btn)

        # InProgressWish 管理员
        if isinstance(wish, InProgressWish) and ctx.role >= UserRole.ADMIN:
            btn = discord.ui.Button(label="通过提案", style=discord.ButtonStyle.success, row=1)
            btn.callback = self._resolve_accept
            self.add_item(btn)

            btn = discord.ui.Button(label="驳回退回讨论", style=discord.ButtonStyle.primary, row=1)
            btn.callback = self._resolve_reject_reopen
            self.add_item(btn)

            btn = discord.ui.Button(label="驳回并关闭", style=discord.ButtonStyle.danger, row=1)
            btn.callback = self._resolve_reject_close
            self.add_item(btn)

            btn = discord.ui.Button(label="回退认领", style=discord.ButtonStyle.secondary, row=2)
            btn.callback = self._revert_claim
            self.add_item(btn)

        # ClosedWish / FrozenWish 管理员
        if isinstance(wish, (ClosedWish, FrozenWish)) and ctx.role >= UserRole.ADMIN:
            btn = discord.ui.Button(label="重新开启讨论", style=discord.ButtonStyle.primary, row=0)
            btn.callback = self._reopen
            self.add_item(btn)

        # 合并愿望 (Admin, 非终态)
        if ctx.role >= UserRole.ADMIN and not isinstance(wish, (ClosedWish, FulfilledWish)):
            btn = discord.ui.Button(label="合并愿望", style=discord.ButtonStyle.secondary, row=3)
            btn.callback = self._merge_modal_cb
            self.add_item(btn)

    async def _update_original_card(self, new_wish):
        """更新原始愿望卡片的 embed 和按钮。"""
        try:
            await self._original_message.edit(
                embed=WishEmbed(new_wish),
                view=WishCardView.for_wish(new_wish, self._ctx)
            )
        except (discord.NotFound, discord.Forbidden):
            pass

    async def _call_engine(self, interaction: discord.Interaction, coro):
        """执行引擎操作并处理业务异常。"""
        try:
            return await coro
        except (StateTransitionError, PermissionError, ValueError) as e:
            await interaction.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)
            return None

    async def _withdraw(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.withdraw_wish(self._ctx, self._wish_id))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 愿望已关闭。", ephemeral=True)

    async def _force_activate(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_force_activate(self._ctx, self._wish_id))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 已强制开启讨论。", ephemeral=True)

    async def _resolve_accept(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_resolve_proposal(self._ctx, self._wish_id, "accept"))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 提案已通过。", ephemeral=True)

    async def _resolve_reject_reopen(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_resolve_proposal(self._ctx, self._wish_id, "reject_reopen"))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 已驳回并退回讨论。", ephemeral=True)

    async def _resolve_reject_close(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_resolve_proposal(self._ctx, self._wish_id, "reject_close"))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 已驳回并关闭。", ephemeral=True)

    async def _revert_claim(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_revert_claim(self._ctx, self._wish_id))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 已回退认领。", ephemeral=True)

    async def _reopen(self, interaction: discord.Interaction):
        result = await self._call_engine(interaction, self._engine.admin_reopen_wish(self._ctx, self._wish_id))
        if result is None: return
        await self._update_original_card(result)
        await interaction.response.send_message("✅ 已重新开启讨论。", ephemeral=True)

    async def _force_close_modal_cb(self, interaction: discord.Interaction):
        modal = self._cog.ForceCloseModal(self._engine, self._ctx, self._wish_id, self._original_message)
        await interaction.response.send_modal(modal)

    async def _force_claim_modal_cb(self, interaction: discord.Interaction):
        modal = self._cog.ForceClaimModal(self._engine, self._ctx, self._wish_id, self._original_message)
        await interaction.response.send_modal(modal)

    async def _merge_modal_cb(self, interaction: discord.Interaction):
        modal = self._cog.MergeWishModal(self._engine, self._ctx, self._wish_id, self._original_message)
        await interaction.response.send_modal(modal)
