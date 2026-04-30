from __future__ import annotations
import discord


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

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.create_bottle(
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
            # Could update the original message here if needed
            await itl.response.send_message("✅ 已强制过期。", ephemeral=True)
        except (StateTransitionError, Exception) as e:
            await itl.response.send_message(f"❌ 操作失败: {e}", ephemeral=True)
