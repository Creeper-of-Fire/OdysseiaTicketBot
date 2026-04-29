from __future__ import annotations
import discord


class BottleView(discord.ui.View):
    """漂流瓶视图"""

    def __init__(self, bottle_id: str):
        super().__init__(timeout=300)
        self.bottle_id = bottle_id

    @discord.ui.button(label="打开漂流瓶", style=discord.ButtonStyle.primary, custom_id="bottle:open")
    async def open_bottle(self, interaction: discord.Interaction, button: discord.ui.Button):
        """打开漂流瓶按钮"""
        # 按钮点击事件会在 Cog 的 on_interaction 中处理
        pass

    @discord.ui.button(label="回复漂流瓶", style=discord.ButtonStyle.secondary, custom_id="bottle:reply")
    async def reply_bottle(self, interaction: discord.Interaction, button: discord.ui.Button):
        """回复漂流瓶按钮"""
        # 按钮点击事件会在 Cog 的 on_interaction 中处理
        pass


class CreateBottleModal(discord.ui.Modal, title="写下你的心愿"):
    """创建漂流瓶的模态框"""
    content = discord.ui.TextInput(
        label="心愿内容",
        style=discord.TextStyle.paragraph,
        placeholder="写下你想说的话...",
        required=True,
        max_length=500
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        """提交创建漂流瓶"""
        await self.cog.create_bottle(interaction, self.content.value)


class ReplyBottleModal(discord.ui.Modal, title="回复漂流瓶"):
    """回复漂流瓶的模态框"""
    reply = discord.ui.TextInput(
        label="回复内容",
        style=discord.TextStyle.paragraph,
        placeholder="写下你的回复...",
        required=True,
        max_length=300
    )

    def __init__(self, cog, bottle_id: str):
        super().__init__()
        self.cog = cog
        self.bottle_id = bottle_id

    async def on_submit(self, interaction: discord.Interaction):
        """提交回复"""
        await self.cog.reply_bottle(interaction, self.bottle_id, self.reply.value)