from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import config
from utility.command_naming import prefixed_group

if TYPE_CHECKING:
    from main import TicketBot

# 隐私政策的最后更新日期——改文案时记得同步更新这里。
_PRIVACY_LAST_UPDATED = "2026-10"


def _build_privacy_embed(bot: "TicketBot") -> discord.Embed:
    """构造隐私政策 Embed。

    文案是 BOT 对用户的合规承诺（Discord 开发者政策要求收集用户数据的
    BOT 提供隐私政策），改动前先跟维护者确认。各项内容与 ticket bot 的
    实际数据实践一一对应，不要从别的 bot 直接复制。
    """
    embed = discord.Embed(
        title="隐私政策",
        description=(
            f"{bot.user.name} 尊重并保护用户隐私。本政策说明本 BOT 收集哪些数据、"
            "如何使用、如何保存，以及你对自身数据拥有的权利。"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )

    embed.add_field(
        name="📥 我们收集的数据",
        value="\n".join([
            "• Discord 用户 ID 与服务器 ID——功能运转的基础标识",
            "• 工单（投诉）数据：你提交的表单内容，以及工单频道内的消息；"
            "工单关闭后整个频道会归档到归档频道，供管理组查阅",
            "• 漂流瓶：你投出的标题与正文、投递与捞取记录",
            "• 许愿墙：愿望标题与内容、支持记录",
        ]),
        inline=False,
    )
    embed.add_field(
        name="🎯 数据的用途",
        value=(
            "仅用于提供工单处理、漂流瓶、许愿墙等社区功能。"
            "工单内容仅对参与处理的管理人员可见，不会公开；"
            "漂流瓶与愿望按功能设计在服务器内展示。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🗄️ 存储与保留",
        value=(
            "数据保存在 BOT 维护者控制的服务器上（本地数据库与文件），"
            "并定期自动备份到指定服务器频道，仅维护者与管理组可访问。"
            "数据在功能需要期间保留。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔗 数据共享",
        value=(
            "不与任何第三方共享、出售或转移数据。"
            "数据仅存在于 Discord 与本 BOT 自身的基础设施。"
        ),
        inline=False,
    )
    embed.add_field(
        name="✅ 你的权利",
        value="你可以随时通过私信联系 BOT 维护者，查询或删除与你相关的数据。",
        inline=False,
    )

    embed.set_footer(
        text=f"{bot.user.name} · 隐私政策 · 最后更新 {_PRIVACY_LAST_UPDATED}"
    )
    return embed


class HelpCenterCog(commands.Cog, name="HelpCenter"):
    """帮助中心——对外展示隐私政策等合规信息。

    背景：Discord 开发者政策要求收集用户数据的 BOT 提供隐私政策；
    我们没有独立网站，用帮助组的「隐私政策」命令作为政策展示入口。
    命令全员可用（不设 default_permissions），私密回复不刷屏。
    """

    help_group = prefixed_group(
        "帮助",
        description="查看 BOT 的帮助信息与隐私政策",
        guild_ids=[gid for gid in config.GUILD_IDS],
    )

    def __init__(self, bot: "TicketBot"):
        self.bot = bot

    @help_group.command(
        name="隐私政策",
        description="查看本 BOT 的隐私政策（我们收集什么、如何使用、你的权利）",
    )
    async def privacy_policy(self, interaction: discord.Interaction):
        """展示隐私政策。"""
        await interaction.response.send_message(
            embed=_build_privacy_embed(self.bot),
            ephemeral=True,
        )


async def setup(bot: "TicketBot"):
    """Cog 的入口点。"""
    await bot.add_cog(HelpCenterCog(bot))
