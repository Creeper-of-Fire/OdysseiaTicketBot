from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import config
from utility.command_naming import prefixed_group

if TYPE_CHECKING:
    from main import TicketBot

# 隐私政策的最后更新日期——改文案时记得同步更新这里。
_PRIVACY_LAST_UPDATED = "2026-11"

# 完整政策站点（GitHub Pages）。站内中英双语，英文版为默认版本。
# 本 Embed 只是摘要——口径必须与完整政策一致，有出入时以完整政策为准，
# 但两边要一起改，不要只改一处。
_POLICY_URL = "https://creeper-of-fire.github.io/privacy/odysseia-ticket-bot/"
_POLICY_URL_ZH = "https://creeper-of-fire.github.io/zh/privacy/odysseia-ticket-bot/"
_REPO_URL = "https://github.com/Creeper-of-Fire/OdysseiaTicketBot"
_ISSUES_URL = "https://github.com/Creeper-of-Fire/OdysseiaTicketBot/issues"


def _build_privacy_embed(bot: "TicketBot") -> discord.Embed:
    """构造隐私政策 Embed。

    文案是 BOT 对用户的合规承诺（Discord 开发者政策要求收集用户数据的
    BOT 提供隐私政策），改动前先跟维护者确认。各项内容与 ticket bot 的
    实际数据实践一一对应，不要从别的 bot 直接复制。
    """
    embed = discord.Embed(
        title="隐私政策",
        description=(
            f"{bot.user.name} 尊重并保护用户隐私。以下是本政策要点的摘要；"
            "完整政策（含数据处理细节与你的权利）见文末链接。"
        ),
        color=discord.Color.from_rgb(88, 101, 242),
    )

    embed.add_field(
        name="📥 我们收集的数据",
        value="\n".join([
            "• Discord 用户 ID、服务器 ID、角色、频道与消息 ID——功能运转的基础标识",
            "• 投诉表单：你填写的被投诉人用户名或 ID、事件描述、证据链接"
            "（只有链接，不支持上传附件）；表单在你确认提交前只存在于内存中",
            "• 工单频道内的消息与后续沟通",
            "• 许愿墙：作者、标题、正文、支持与认领记录（实名展示）",
            "• 漂流瓶：作者、打捞者、标题、正文与各阶段时间戳（实名展示）",
        ]),
        inline=False,
    )
    embed.add_field(
        name="🎯 数据的用途",
        value=(
            "仅用于提供工单处理、许愿墙与漂流瓶等社区功能。"
            "工单内容仅对提交者本人与该投诉类型的处理组可见，不会公开在频道中；"
            "许愿与漂流瓶按功能设计在服务器内展示。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🗄️ 存储与保留",
        value=(
            "数据保存在 BOT 维护者控制的服务器上（文件），并定期备份以便在误操作后"
            "回退。投诉记录不会自动过期，保留至被删除；归档的工单长期保留。"
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
        value=(
            f"你可以随时通过 Discord 私信维护者，或在 <{_ISSUES_URL}> 提交 Issue，"
            "查询、更正或要求删除与你相关的数据（由维护者人工处理）。\n"
            "如果某条投诉涉及你，处理组可能持有他人提交的关于你的信息，"
            "你同样可以提出查询或删除。"
        ),
        inline=False,
    )
    embed.add_field(
        name="📖 完整政策",
        value=(
            f"英文（默认）：<{_POLICY_URL}>\n"
            f"中文：<{_POLICY_URL_ZH}>\n"
            f"源代码公开可查：<{_REPO_URL}>"
        ),
        inline=False,
    )

    embed.set_footer(
        text=f"{bot.user.name} · 隐私政策 · 最后更新 {_PRIVACY_LAST_UPDATED}"
    )
    return embed


class HelpCenterCog(commands.Cog, name="HelpCenter"):
    """帮助中心——对外展示隐私政策等合规信息。

    背景：Discord 开发者政策要求收集用户数据的 BOT 提供隐私政策；
    完整政策在独立站点（_POLICY_URL），本命令展示的是要点摘要。
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
