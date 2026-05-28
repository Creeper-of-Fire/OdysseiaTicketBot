from __future__ import annotations
from typing import TYPE_CHECKING
import discord

from .embeds import BottleEmbed, BottleUIFactory

if TYPE_CHECKING:
    from ..BottleSystemCog import BottleSystemCog
    from ..bottle_core.models import AnyBottle, UserContext


class BottleCardView(discord.ui.View):
    """持久化视图：处理漂流瓶卡片的所有按钮交互。

    通过 bot.add_view(BottleCardView()) 全局注册，bot 重启后按钮仍然可用。
    bottle_id 从交互消息的 embed footer 中提取。
    """

    def __init__(self):
        super().__init__(timeout=None)

    @classmethod
    def for_bottle(cls, bottle: "AnyBottle", user_ctx: "UserContext") -> "BottleCardView":
        """根据漂流瓶状态和用户角色构建仅含合法按钮的视图。"""
        view = cls()
        allowed = bottle.get_allowed_actions(user_ctx)

        remove_ids = set()
        if "CLAIM" not in allowed:
            remove_ids.add("bottle:claim")
        if "UNCLAIM" not in allowed:
            remove_ids.add("bottle:unclaim")
        if "COMPLETE" not in allowed:
            remove_ids.add("bottle:complete")
        if "MANAGE" not in allowed:
            remove_ids.add("bottle:manage")

        for item in list(view.children):
            if item.custom_id in remove_ids:
                view.remove_item(item)

        return view

    # ---- 按钮回调 ----

    @discord.ui.button(label="🙋 揭榜认领", style=discord.ButtonStyle.success, custom_id="bottle:claim")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        bottle_id = BottleEmbed.extract_bottle_id(interaction.message.embeds[0])
        cog: "BottleSystemCog" = interaction.client.get_cog("BottleSystemCog")
        user_ctx = cog._get_user_context(interaction)
        engine = cog._get_engine(interaction.guild_id)

        from ..bottle_core.engine import StateTransitionError
        try:
            bottle = await engine.claim_bottle(user_ctx, bottle_id)
            if interaction.message:
                await interaction.response.edit_message(
                    embed=BottleEmbed(bottle),
                    view=BottleCardView.for_bottle(bottle, user_ctx)
                )
            await interaction.followup.send(
                embed=BottleUIFactory.create_success_embed("认领成功！"), ephemeral=True
            )
        except (StateTransitionError, ValueError) as e:
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed(str(e)), ephemeral=True
            )

    @discord.ui.button(label="取消认领", style=discord.ButtonStyle.secondary, custom_id="bottle:unclaim")
    async def unclaim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        bottle_id = BottleEmbed.extract_bottle_id(interaction.message.embeds[0])
        cog: "BottleSystemCog" = interaction.client.get_cog("BottleSystemCog")
        user_ctx = cog._get_user_context(interaction)
        engine = cog._get_engine(interaction.guild_id)

        from ..bottle_core.engine import StateTransitionError
        try:
            bottle = await engine.unclaim_bottle(user_ctx, bottle_id)
            if interaction.message:
                await interaction.response.edit_message(
                    embed=BottleEmbed(bottle),
                    view=BottleCardView.for_bottle(bottle, user_ctx)
                )
            await interaction.followup.send(
                embed=BottleUIFactory.create_success_embed("已取消认领。"), ephemeral=True
            )
        except (StateTransitionError, ValueError) as e:
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed(str(e)), ephemeral=True
            )

    @discord.ui.button(label="✅ 确认完成", style=discord.ButtonStyle.primary, custom_id="bottle:complete")
    async def complete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        bottle_id = BottleEmbed.extract_bottle_id(interaction.message.embeds[0])
        cog: "BottleSystemCog" = interaction.client.get_cog("BottleSystemCog")
        user_ctx = cog._get_user_context(interaction)
        engine = cog._get_engine(interaction.guild_id)

        from ..bottle_core.engine import StateTransitionError
        try:
            bottle = await engine.complete_bottle(user_ctx, bottle_id)
            if interaction.message:
                await interaction.response.edit_message(
                    embed=BottleEmbed(bottle),
                    view=BottleCardView.for_bottle(bottle, user_ctx)
                )
            await interaction.followup.send(
                embed=BottleUIFactory.create_success_embed("心愿已完成！"), ephemeral=True
            )
        except (StateTransitionError, ValueError) as e:
            await interaction.response.send_message(
                embed=BottleUIFactory.create_error_embed(str(e)), ephemeral=True
            )

    @discord.ui.button(label="⚙️ 管理", style=discord.ButtonStyle.secondary, custom_id="bottle:manage")
    async def manage_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        bottle_id = BottleEmbed.extract_bottle_id(interaction.message.embeds[0])
        cog: "BottleSystemCog" = interaction.client.get_cog("BottleSystemCog")
        user_ctx = cog._get_user_context(interaction)
        engine = cog._get_engine(interaction.guild_id)

        await interaction.response.send_message(
            "管理面板",
            view=BottleManageView(engine, user_ctx, bottle_id, interaction),
            ephemeral=True
        )


class CreateBottleModal(discord.ui.Modal, title="发布心愿漂流瓶"):
    title_input = discord.ui.TextInput(
        label="标题 (一句话概括你的心愿)",
        max_length=100
    )
    content_input = discord.ui.TextInput(
        label="详细说明",
        style=discord.TextStyle.paragraph,
        placeholder="描述你的心愿...例如：想找人一起创作、想交新朋友一起玩游戏...",
        max_length=500
    )

    async def on_submit(self, interaction: discord.Interaction):
        cog: "BottleSystemCog" = interaction.client.get_cog("BottleSystemCog")
        await cog.create_bottle(
            interaction, self.title_input.value, self.content_input.value
        )


class BottleManageView(discord.ui.View):

    def __init__(self, engine, ctx, bottle_id, original_interaction):
        super().__init__(timeout=120)
        self.engine = engine
        self.ctx = ctx
        self.bottle_id = bottle_id
        self.original_interaction = original_interaction

    @discord.ui.button(label="强制过期", style=discord.ButtonStyle.danger)
    async def force_expire(self, itl: discord.Interaction, _):
        from ..bottle_core.engine import StateTransitionError
        try:
            bottle = await self.engine.expire_bottle(self.ctx, self.bottle_id)
            await itl.response.send_message("✅ 已强制过期。", ephemeral=True)
        except (StateTransitionError, Exception) as e:
            await itl.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)
