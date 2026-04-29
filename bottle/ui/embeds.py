from __future__ import annotations
import discord
from datetime import datetime

from ..bottle_core.models import Bottle


class BottleEmbed:
    """漂流瓶嵌入消息"""

    @staticmethod
    def create_bottle_embed(bottle: Bottle) -> discord.Embed:
        """创建漂流瓶嵌入消息"""
        embed = discord.Embed(
            title="🏺 漂流瓶",
            description="你发现了一个漂流瓶！",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        if bottle.is_opened:
            embed.add_field(name="内容", value=bottle.content, inline=False)
            if bottle.replies:
                embed.add_field(name="回复", value="\n".join(bottle.replies), inline=False)
        else:
            embed.add_field(name="状态", value="未打开", inline=False)
            embed.add_field(name="提示", value="点击按钮打开漂流瓶", inline=False)

        embed.set_footer(text=f"漂流瓶 ID: {bottle.id[:8]}")
        return embed

    @staticmethod
    def create_success_embed(message: str) -> discord.Embed:
        """创建成功消息嵌入"""
        embed = discord.Embed(
            title="✅ 操作成功",
            description=message,
            color=discord.Color.green(),
            timestamp=datetime.now()
        )
        return embed

    @staticmethod
    def create_error_embed(message: str) -> discord.Embed:
        """创建错误消息嵌入"""
        embed = discord.Embed(
            title="❌ 操作失败",
            description=message,
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        return embed