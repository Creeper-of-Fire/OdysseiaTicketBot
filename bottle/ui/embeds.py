from __future__ import annotations
import discord

from ..bottle_core.models import (
    AnyBottle, AvailableBottle, ClaimedBottle,
    CompletedBottle, ExpiredBottle, UserContext
)


class BottleEmbed(discord.Embed):
    STATE_COLORS = {
        "AVAILABLE": discord.Color.blue(),
        "CLAIMED": discord.Color.gold(),
        "COMPLETED": discord.Color.green(),
        "EXPIRED": discord.Color.light_gray(),
    }
    STATE_LABELS = {
        "AVAILABLE": "待揭榜",
        "CLAIMED": "已揭榜",
        "COMPLETED": "已完成",
        "EXPIRED": "已过期",
    }

    def __init__(self, bottle: AnyBottle):
        state_str = bottle.state
        label = self.STATE_LABELS.get(state_str, state_str)
        super().__init__(
            title=f"【{label}】{bottle.title}",
            description=bottle.content,
            color=self.STATE_COLORS.get(state_str, discord.Color.default())
        )
        self.add_field(name="发布人", value=f"<@{bottle.author_id}>", inline=True)

        if hasattr(bottle, "claimer_ids") and bottle.claimer_ids:
            claimer_mentions = " ".join(f"<@{cid}>" for cid in bottle.claimer_ids)
            self.add_field(name="认领人", value=claimer_mentions, inline=True)

        if isinstance(bottle, CompletedBottle):
            self.add_field(
                name="完成时间",
                value=bottle.completed_at.strftime("%Y-%m-%d %H:%M"),
                inline=True
            )

        self.set_footer(text=f"ID: {bottle.id} | 更新于 {bottle.updated_at.strftime('%m-%d %H:%M')}")

    @staticmethod
    def extract_bottle_id(embed: discord.Embed) -> str:
        """从 embed footer 提取 bottle_id。格式: 'ID: {uuid} | 更新于 ...'"""
        return embed.footer.text.split("ID: ")[1].split(" |")[0]


class BottleUIFactory:

    @staticmethod
    def build_view(bottle: AnyBottle, user_ctx: UserContext) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        allowed_actions = bottle.get_allowed_actions(user_ctx)

        if "CLAIM" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="🙋 揭榜认领",
                style=discord.ButtonStyle.success,
                custom_id=f"bottle:claim:{bottle.id}"
            ))

        if "UNCLAIM" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="取消认领",
                style=discord.ButtonStyle.secondary,
                custom_id=f"bottle:unclaim:{bottle.id}"
            ))

        if "COMPLETE" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="✅ 确认完成",
                style=discord.ButtonStyle.primary,
                custom_id=f"bottle:complete:{bottle.id}"
            ))

        if "MANAGE" in allowed_actions:
            view.add_item(discord.ui.Button(
                label="⚙️ 管理",
                style=discord.ButtonStyle.secondary,
                custom_id=f"bottle:manage:{bottle.id}"
            ))

        return view

    @staticmethod
    def create_success_embed(message: str) -> discord.Embed:
        return discord.Embed(
            title="✅ 操作成功",
            description=message,
            color=discord.Color.green()
        )

    @staticmethod
    def create_error_embed(message: str) -> discord.Embed:
        return discord.Embed(
            title="❌ 操作失败",
            description=message,
            color=discord.Color.red()
        )
