"""bottle panel + 所有 ephemeral views / modals。

设计:
- BottlePanelView:常驻,timeout=None,挂 4 个用户按钮 + 1 个 admin 入口按钮。
- 其他 View:ephemeral,带 timeout,挂按钮做具体操作。

所有 callback 内部调 service,异常走 try/except + ephemeral 反馈,失败不能静默。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import discord
from discord import ui

from utility.paginated_view import PaginatedView

from .models import Bottle
from .service import (
    BottleError,
    BottleNotFound,
    HeldLimitReached,
    PermissionDenied,
)

if TYPE_CHECKING:
    from .BottleSystemCog import BottleSystemCog

logger = logging.getLogger(__name__)


# ============= 工具函数 =============

def _format_dt(dt: Optional[datetime]) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M")


def _bottle_summary(b: Bottle) -> str:
    """打捞/我的瓶子列表用的一行摘要。"""
    lines = [
        f"**{b.title}**",
        f"> {b.content[:120]}{'…' if len(b.content) > 120 else ''}",
        f"发布: <@{b.author_id}> · {b.created_at.strftime('%m-%d %H:%M')}",
    ]
    if b.claimer_id:
        lines.append(f"认领: <@{b.claimer_id}> · {_format_dt(b.claimed_at)}")
    if b.completed_at:
        lines.append(f"完成: {_format_dt(b.completed_at)}")
    return "\n".join(lines)


# ============= 常驻 Panel View =============

class BottlePanelView(ui.View):
    """常驻 panel 视图(timeout=None)。

    5 个按钮:
    - 📮 发布
    - 🎣 打捞
    - 📤 我发的
    - 🎣 我捞的
    - ⚙️ 配置(管理员)
    """

    def __init__(self, cog: "BottleSystemCog"):
        super().__init__(timeout=None)
        self.cog = cog

    async def _ensure_guild_id(self, interaction: discord.Interaction) -> Optional[int]:
        gid = interaction.guild_id
        if gid is None:
            await interaction.response.send_message(
                "❌ 只能在服务器中使用。", ephemeral=True
            )
            return None
        if not self.cog.is_enabled(gid):
            await interaction.response.send_message(
                "❌ 当前服务器未启用漂流瓶功能(请检查 toml 配置)。", ephemeral=True
            )
            return None
        return gid

    @ui.button(label="📮 发布", style=discord.ButtonStyle.success, custom_id="bottle:publish")
    async def publish_button(self, interaction: discord.Interaction, _: ui.Button):
        gid = await self._ensure_guild_id(interaction)
        if gid is None:
            return
        modal = PublishModal(self.cog, gid)
        await interaction.response.send_modal(modal)

    @ui.button(label="🎣 打捞", style=discord.ButtonStyle.primary, custom_id="bottle:draw")
    async def draw_button(self, interaction: discord.Interaction, _: ui.Button):
        gid = await self._ensure_guild_id(interaction)
        if gid is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            bottle = await self.cog.service_for(gid).pick_random_available()
        except Exception as e:
            self.cog.logger.exception("打捞失败 guild=%s", gid)
            await interaction.followup.send(f"❌ 打捞失败: {e}", ephemeral=True)
            return

        if bottle is None:
            await interaction.followup.send("🌊 海里目前没有瓶子。", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🎣 捡到一个瓶子: {bottle.title}",
            description=bottle.content,
            color=discord.Color.blue(),
        )
        embed.add_field(name="发布者", value=f"<@{bottle.author_id}>", inline=True)
        embed.add_field(name="漂浮至", value=_format_dt(bottle.bottle_expires_at), inline=True)
        embed.set_footer(text=f"ID: {bottle.id}")

        view = DrawBottleView(self.cog, gid, bottle.id)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @ui.button(label="📤 我发的", style=discord.ButtonStyle.secondary, custom_id="bottle:my_released")
    async def my_released_button(self, interaction: discord.Interaction, _: ui.Button):
        gid = await self._ensure_guild_id(interaction)
        if gid is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            groups = await self.cog.service_for(gid).get_my_released(str(interaction.user.id))
        except Exception as e:
            self.cog.logger.exception("查询我发的瓶子失败 guild=%s", gid)
            await interaction.followup.send(f"❌ 查询失败: {e}", ephemeral=True)
            return
        view = MyBottlesView(self.cog, gid, mode="released", user_id=str(interaction.user.id))
        await view.start(interaction, ephemeral=True)

    @ui.button(label="🎣 我捞的", style=discord.ButtonStyle.secondary, custom_id="bottle:my_claimed")
    async def my_claimed_button(self, interaction: discord.Interaction, _: ui.Button):
        gid = await self._ensure_guild_id(interaction)
        if gid is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            groups = await self.cog.service_for(gid).get_my_claimed(str(interaction.user.id))
        except Exception as e:
            self.cog.logger.exception("查询我捞的瓶子失败 guild=%s", gid)
            await interaction.followup.send(f"❌ 查询失败: {e}", ephemeral=True)
            return
        view = MyBottlesView(self.cog, gid, mode="claimed", user_id=str(interaction.user.id))
        await view.start(interaction, ephemeral=True)

    @ui.button(label="⚙️ 配置", style=discord.ButtonStyle.secondary, custom_id="bottle:config_help")
    async def config_help_button(self, interaction: discord.Interaction, _: ui.Button):
        """给 admin 提示 toml 配置命令。普通用户看到也无所谓——只是说明性消息。"""
        await interaction.response.send_message(
            (
                "📦 **漂流瓶配置管理**\n\n"
                "• `/上传配置` — 上传新的 toml(需要 SHA-256 校验)\n"
                "• `/下载配置` — 下载当前 toml + 教程\n"
                "• `/查看配置哈希` — 查看当前 SHA-256\n\n"
                "完整字段说明:`docs/bottle-doc.md`"
            ),
            ephemeral=True,
        )


# ============= 发布 Modal =============

class PublishModal(ui.Modal, title="发布漂流瓶"):
    """发布 modal:标题 / 内容 / 过期天数 / 完成时限。

    天数字段允许覆盖 toml 的默认值,但不能小于 1(下界由 pydantic 校验)。
    """

    title_input = ui.TextInput(label="标题", max_length=100)
    content_input = ui.TextInput(
        label="内容", style=discord.TextStyle.paragraph, max_length=500
    )
    lifetime_days_input = ui.TextInput(
        label="海里过期天数(覆盖 toml 默认)", default="14", max_length=3
    )
    claim_deadline_days_input = ui.TextInput(
        label="认领后完成时限(天,覆盖 toml 默认)", default="7", max_length=3
    )

    def __init__(self, cog: "BottleSystemCog", guild_id: int):
        super().__init__()
        self.cog = cog
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            lifetime = int(self.lifetime_days_input.value)
            deadline = int(self.claim_deadline_days_input.value)
            if lifetime < 1 or deadline < 1:
                raise ValueError("天数必须 >= 1")
        except ValueError as e:
            await interaction.response.send_message(f"❌ 天数格式错误: {e}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 二次确认 ephemeral
        embed = discord.Embed(
            title="📮 确认发布这个瓶子?",
            color=discord.Color.orange(),
        )
        embed.add_field(name="标题", value=self.title_input.value, inline=False)
        embed.add_field(name="内容", value=self.content_input.value, inline=False)
        embed.add_field(name="海里过期", value=f"{lifetime} 天后", inline=True)
        embed.add_field(name="认领时限", value=f"{deadline} 天后", inline=True)
        view = PublishConfirmView(
            self.cog, self.guild_id,
            title=self.title_input.value,
            content=self.content_input.value,
            lifetime_days=lifetime,
            claim_deadline_days=deadline,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class PublishConfirmView(ui.View):
    """二次确认:确认发布 / 取消。"""

    def __init__(
        self,
        cog: "BottleSystemCog",
        guild_id: int,
        *,
        title: str,
        content: str,
        lifetime_days: int,
        claim_deadline_days: int,
    ):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.title = title
        self.content = content
        self.lifetime_days = lifetime_days
        self.claim_deadline_days = claim_deadline_days
        self._resolved = False

    def _disable(self):
        for child in self.children:
            child.disabled = True
        self._resolved = True

    @ui.button(label="✅ 确认发布", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: ui.Button):
        if self._resolved:
            await interaction.response.send_message("已处理。", ephemeral=True)
            return
        try:
            bottle = await self.cog.service_for(self.guild_id).release(
                author_id=str(interaction.user.id),
                title=self.title,
                content=self.content,
                lifetime_days=self.lifetime_days,
                claim_deadline_days=self.claim_deadline_days,
            )
        except Exception as e:
            self.cog.logger.exception("发布瓶子失败 guild=%s", self.guild_id)
            self._disable()
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 发布失败",
                    description=f"```\n{e}\n```",
                    color=discord.Color.red(),
                ),
                view=self,
            )
            return
        self._disable()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 投放成功",
                description=(
                    f"瓶子 **{bottle.title}** 已扔进海里。\n"
                    f"ID: `{bottle.id}`\n"
                    f"海里过期: {_format_dt(bottle.bottle_expires_at)}"
                ),
                color=discord.Color.green(),
            ),
            view=self,
        )

    @ui.button(label="❌ 取消", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: ui.Button):
        if self._resolved:
            return
        self._disable()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="已取消", description="瓶子未投放。",
                color=discord.Color.greyple(),
            ),
            view=self,
        )


# ============= 打捞 View(认领 / 跳过) =============

class DrawBottleView(ui.View):
    """打捞到的瓶子 ephemeral view:认领 / 跳过。"""

    def __init__(self, cog: "BottleSystemCog", guild_id: int, bottle_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.bottle_id = bottle_id
        self._resolved = False

    def _disable(self):
        for child in self.children:
            child.disabled = True
        self._resolved = True

    @ui.button(label="🤝 认领", style=discord.ButtonStyle.success)
    async def claim(self, interaction: discord.Interaction, _: ui.Button):
        if self._resolved:
            return
        try:
            bottle = await self.cog.service_for(self.guild_id).claim(
                claimer_id=str(interaction.user.id),
                bottle_id=self.bottle_id,
            )
        except HeldLimitReached as e:
            self._disable()
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 认领失败", description=str(e), color=discord.Color.red()),
                view=self,
            )
            return
        except BottleNotFound as e:
            self._disable()
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 认领失败", description=str(e), color=discord.Color.red()),
                view=self,
            )
            return
        except BottleError as e:
            self._disable()
            await interaction.response.edit_message(
                embed=discord.Embed(title="❌ 认领失败", description=str(e), color=discord.Color.red()),
                view=self,
            )
            return
        except Exception as e:
            self.cog.logger.exception("认领瓶子失败 guild=%s bottle=%s", self.guild_id, self.bottle_id)
            self._disable()
            await interaction.response.edit_message(
                embed=discord.Embed(
                    title="❌ 内部错误",
                    description=f"```\n{e}\n```",
                    color=discord.Color.red(),
                ),
                view=self,
            )
            return

        self._disable()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ 认领成功",
                description=(
                    f"瓶子 **{bottle.title}** 已归你。\n"
                    f"认领时限: {_format_dt(bottle.claim_expires_at)}"
                ),
                color=discord.Color.green(),
            ),
            view=self,
        )

    @ui.button(label="⏭️ 跳过", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, _: ui.Button):
        if self._resolved:
            return
        self._disable()
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⏭️ 已跳过", description="瓶子仍在海里,别人可能捞到。",
                color=discord.Color.greyple(),
            ),
            view=self,
        )


# ============= 我的瓶子 View =============

class MessageModal(ui.Modal, title="发送私信"):
    """通过瓶子给对方发 DM 的 modal。

    提示文案写在 label 里——DM 失败时友好的"对方可能关闭了私信"提示由 _handle_message 完成。
    """

    message_input = ui.TextInput(
        label="消息内容",
        style=discord.TextStyle.paragraph,
        max_length=1000,
        placeholder="说点什么吧～",
    )

    def __init__(self, target_user_id: str):
        super().__init__(timeout=300)
        self.target_user_id = target_user_id

    async def on_submit(self, interaction: discord.Interaction):
        content = self.message_input.value.strip()
        if not content:
            await interaction.response.send_message("❌ 消息内容不能为空。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        # 取对方用户对象
        try:
            target = await interaction.client.fetch_user(int(self.target_user_id))
        except (ValueError, discord.NotFound):
            await interaction.followup.send(
                "❌ 找不到对方(可能已不在服务器,或 ID 无效)。", ephemeral=True
            )
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 拉取用户信息失败: {e}", ephemeral=True)
            return

        # 拼 DM 内容——开头说明来源 + 原文
        sender = interaction.user
        dm_text = (
            f"💌 你在漂流瓶里收到一条来自 {sender.mention}({sender.display_name}) 的消息:\n\n"
            f"{content}\n\n"
            f"—— 来自漂流瓶"
        )
        try:
            await target.send(dm_text)
        except discord.Forbidden:
            await interaction.followup.send(
                f"❌ 无法送达 DM 给 {target.mention}。\n\n"
                f"可能原因:\n"
                f"• 对方在 discord 设置里**关闭了**'允许来自服务器成员的私信'\n"
                f"• 你不是对方的好友(对方可能开启了'仅好友可私信')\n\n"
                f"请联系对方调整隐私设置后再试。",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ DM 发送失败: {e}", ephemeral=True)
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 内部错误: {e}", ephemeral=True)
            return

        await interaction.followup.send(
            f"✅ 已 DM 给 {target.mention}。",
            ephemeral=True,
        )


class MyBottlesView(PaginatedView):
    """我的瓶子分页视图。每页 4 个瓶子,每个瓶子按需挂按钮:

    - ✅ 完成:claimed 池子里,且当前用户是 author(released)或 claimer(claimed)
    - 📩 私信:存在"对方"时(claimer_id / author_id)

    items 是 list[tuple[Bottle, status_key]]。分页 / 完成 / 私信按钮通过 interaction_check 路由。
    """

    POOL_LABELS = {
        "available": "🌊 海里",
        "claimed": "🤝 已认领",
        "completed": "✅ 已完成",
        "expired": "🗑️ 废弃",
    }

    def __init__(self, cog: "BottleSystemCog", guild_id: int, *, mode: str, user_id: str):
        cog_ref = cog
        gid_ref = guild_id
        mode_ref = mode
        user_ref = user_id

        async def provider():
            svc = cog_ref.service_for(gid_ref)
            groups = (
                await svc.get_my_released(user_ref)
                if mode_ref == "released"
                else await svc.get_my_claimed(user_ref)
            )
            items: list[tuple[Bottle, str]] = []
            for key in ("available", "claimed", "completed", "expired"):
                for b in groups.get(key, []):
                    items.append((b, key))
            return items

        super().__init__(all_items_provider=provider, items_per_page=4)
        self.cog = cog
        self.guild_id = guild_id
        self.mode = mode
        self.user_id = user_id

    def _other_user_id(self, bottle: Bottle) -> str | None:
        """返回对方 ID。released 模式 → claimer;claimed 模式 → author。"""
        if self.mode == "released":
            return bottle.claimer_id
        return bottle.author_id

    def _other_user_label(self) -> str:
        return "认领者" if self.mode == "released" else "发布者"

    def _can_complete(self, bottle: Bottle, status: str) -> bool:
        if status != "claimed":
            return False
        if self.mode == "released":
            return bottle.author_id == self.user_id
        return bottle.claimer_id == self.user_id

    async def _rebuild_view(self):
        self.clear_items()
        items: list[tuple[Bottle, str]] = self.get_page_items()  # type: ignore[assignment]

        title = "📤 我发的瓶子" if self.mode == "released" else "🎣 我捞的瓶子"
        embed = discord.Embed(title=title, color=discord.Color.blue())
        if not self.all_items:
            embed.description = "(空)"
        else:
            embed.description = (
                f"共 {len(self.all_items)} 个 · 第 {self.page + 1}/{self.total_pages} 页"
            )
            for bottle, status in items:
                pool_label = self.POOL_LABELS.get(status, status)
                other_id = self._other_user_id(bottle)
                other_line = f"{self._other_user_label()}: <@{other_id}>" if other_id else ""
                lines = [
                    line for line in [
                        other_line,
                        f"> {bottle.content[:80]}{'…' if len(bottle.content) > 80 else ''}",
                        f"`{bottle.id[:8]}`",
                    ] if line
                ]
                embed.add_field(
                    name=f"{pool_label} · {bottle.title}",
                    value="\n".join(lines),
                    inline=False,
                )
        self.embed = embed

        # 每个瓶子最多两个按钮:✅ 完成(claimed + 权限 ok)+ 📩 私信(有对方)
        # row 安排:row i 给第 i 个瓶子,row 4 给分页
        for i, (bottle, status) in enumerate(items):
            row = min(i, 3)  # 给分页留 row=4
            if self._can_complete(bottle, status):
                self.add_item(ui.Button(
                    label="✅ 完成",
                    style=discord.ButtonStyle.success,
                    custom_id=f"complete:{bottle.id}",
                    row=row,
                ))
            if self._other_user_id(bottle):
                self.add_item(ui.Button(
                    label="📩 私信",
                    style=discord.ButtonStyle.primary,
                    custom_id=f"msg:{bottle.id}",
                    row=row,
                ))

        self._add_pagination_buttons(row=4)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id", "")
        if custom_id.startswith("page_"):
            await self._handle_pagination(interaction)
            return False
        if custom_id.startswith("complete:"):
            bottle_id = custom_id.split(":", 1)[1]
            await self._handle_complete(interaction, bottle_id)
            return False
        if custom_id.startswith("msg:"):
            bottle_id = custom_id.split(":", 1)[1]
            await self._handle_message(interaction, bottle_id)
            return False
        return True

    async def _handle_complete(self, interaction: discord.Interaction, bottle_id: str):
        await interaction.response.defer()
        try:
            await self.cog.service_for(self.guild_id).complete(
                completer_id=self.user_id,
                bottle_id=bottle_id,
            )
        except BottleError as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)
            await self.update_view(interaction)
            return
        except Exception as e:
            self.cog.logger.exception("完成瓶子失败 guild=%s bottle=%s", self.guild_id, bottle_id)
            await interaction.followup.send(f"❌ 内部错误: {e}", ephemeral=True)
            await self.update_view(interaction)
            return
        await interaction.followup.send("✅ 已标记完成。", ephemeral=True)
        await self.update_view(interaction)

    async def _handle_message(self, interaction: discord.Interaction, bottle_id: str):
        """打开发 DM 的 modal。"""
        # 找瓶子
        try:
            pool = self.cog.service_for(self.guild_id)._pool()
        except RuntimeError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        bottle: Bottle | None = None
        for attr in ("available", "claimed", "completed", "expired"):
            for b in getattr(pool, attr):
                if b.id == bottle_id:
                    bottle = b
                    break
            if bottle is not None:
                break
        if bottle is None:
            await interaction.response.send_message("❌ 找不到这个瓶子。", ephemeral=True)
            return

        target_id = self._other_user_id(bottle)
        if not target_id:
            await interaction.response.send_message(
                "❌ 这个瓶子没有可以联系的对象(还没人认领/你是发布者本人)。",
                ephemeral=True,
            )
            return
        if target_id == self.user_id:
            await interaction.response.send_message(
                "❌ 不能给自己发 DM。", ephemeral=True,
            )
            return

        modal = MessageModal(target_user_id=target_id)
        await interaction.response.send_modal(modal)