# core/contact_maintainer_cog.py

"""「联系维护者」——管理组在 Discord 里填一张表，问题直接推到维护者的 QQ 单聊。

用途：服务器出了紧急状况、维护者本人不在线时，管理组不用等 Discord 通知，
直接把消息送进维护者自己的 QQ。

链路是 QQ 官方机器人开放平台的两步（注意两个域名不一样）：

    1. 取 access_token —— POST https://api.bot.qq.com/app/getAppAccessToken
    2. 发单聊主动消息 —— POST https://api.sgroup.qq.com/v2/users/{openid}/messages

凭据来自 config 的 ``QQBOT_APP_ID`` / ``QQBOT_APP_SECRET`` / ``QQBOT_OWNER_OPENID``。
任一项缺失 → 命令明确提示"未配置"并拒绝执行（fail-loud），但 bot 照常启动。
"""

from __future__ import annotations

import asyncio
import time
import typing
from datetime import datetime, timedelta, timezone

import aiohttp
import discord
from discord import ui
from discord.ext import commands

import config
from utility.command_naming import prefixed_group
from utility.permison import is_admin

if typing.TYPE_CHECKING:
    from main import TicketBot


# --- QQ 开放平台端点 ---
# 注意：取 token 的域名是 api.bot.qq.com，发消息的域名是 api.sgroup.qq.com，别搞混。
QQ_TOKEN_URL = "https://api.bot.qq.com/app/getAppAccessToken"
QQ_MESSAGE_URL = "https://api.sgroup.qq.com/v2/users/{openid}/messages"

# 每日额度上限（全局共享，不分用户）。
DAILY_LIMIT = 10

# token 到期前 60 秒就重新取——官方保证这段时间内新旧 token 并存，提前换不会断。
_TOKEN_REFRESH_MARGIN_SECONDS = 60

# HTTP 超时（一次主动消息最多等 10 秒）
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)

# 日期口径统一按 UTC+8 自然日算
_UTC8 = timezone(timedelta(hours=8))


class QQApiError(RuntimeError):
    """QQ 开放平台返回了业务错误（HTTP 200 但 body 里有 code，或者 4xx）。"""

    def __init__(self, code: object, message: str):
        super().__init__(f"code={code} message={message}")
        self.code = code
        self.message = message


class ContactMaintainerModal(ui.Modal, title="联系维护者"):
    """填写问题描述的弹窗。提交后交给 cog 推到维护者的 QQ。"""

    def __init__(self, cog: "ContactMaintainerCog"):
        super().__init__(title="联系维护者")
        self.cog = cog
        self.description_input = ui.TextInput(
            label="问题描述",
            style=discord.TextStyle.paragraph,
            min_length=5,
            max_length=800,
            placeholder="写清楚：发生了什么、影响范围、是否需要立刻处理。",
            required=True,
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog._handle_submit(interaction, self.description_input.value)


class ContactMaintainerCog(commands.Cog, name="ContactMaintainer"):
    """管理组 → 维护者 QQ 的紧急联系通道。

    只做一件事：slash 命令 → modal 填表 → QQ 单聊主动消息推给维护者。
    权限走 ``utility.permison.is_admin()``（维护者 + 超级管理组 + 管理组）。
    """

    def __init__(self, bot: "TicketBot"):
        self.bot = bot
        self.logger = bot.logger

        # 每日额度：{"date": "YYYY-MM-DD", "count": 已用条数}，日期按 UTC+8 自然日。
        self._daily_usage: dict[str, typing.Any] = {"date": "", "count": 0}

        # access_token 缓存 + 并发锁（同一时刻只让一个协程去取 token）
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    # =================================================================
    # 每日额度
    # =================================================================

    def _today_str(self) -> str:
        """今天（UTC+8 自然日）的日期字符串——跨天判定用。"""
        return datetime.now(_UTC8).strftime("%Y-%m-%d")

    def _quota_used_today(self) -> int:
        """今天已经用掉了几条额度（跨天自动归零）。

        **为什么这个上限做得这么糙**——它不是防滥用的机制，而是"万一 bot 被盗号、
        权限被绕过"时的兜底闸门：能用到这个命令的都是可信的管理组成员，平时几乎
        不会用，只在真出状况时才通知维护者。所以：
        - 不做持久化：bot 重启归零无所谓（重启本身也意味着要重新 deploy）；
        - 不按用户分账：全局 10 条就够，记账越简单越不容易出错；
        - 极端情况下真被刷爆了，最坏后果也只是维护者的 QQ 多几个未读小红点，
          忽略即可，不会有任何实质损害。

        保持简单比保持周全重要：这个功能的真正价值在"紧急时能叫到人"，
        不在额度本身。
        """
        today = self._today_str()
        if self._daily_usage["date"] != today:
            self._daily_usage["date"] = today
            self._daily_usage["count"] = 0
        return int(self._daily_usage["count"])

    # =================================================================
    # QQ 通道配置
    # =================================================================

    @staticmethod
    def _missing_qq_config() -> list[str]:
        """返回缺失的 QQ 配置项名；全齐则返回空列表。

        fail-loud：配置缺失要在命令里**直接告诉用户**，而不是等到发送时再报一个
        语焉不详的"通道故障"。这里只列配置项**名字**，不碰值。
        """
        missing = []
        if not config.QQBOT_APP_ID:
            missing.append("QQBot_AppID")
        if not config.QQBOT_APP_SECRET:
            missing.append("QQBot_AppSecret")
        if not config.QQBOT_OWNER_OPENID:
            missing.append("QQBot_OwnerOpenID")
        return missing

    # =================================================================
    # QQ 开放平台调用
    # =================================================================

    @staticmethod
    async def _read_json(resp: aiohttp.ClientResponse) -> dict:
        """读 JSON 响应体；不是 JSON / 不是对象时返回空 dict（不炸）。"""
        try:
            data = await resp.json(content_type=None)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def _fetch_access_token(self) -> tuple[str, int]:
        """真的去 QQ 平台换 access_token，返回 (token, expires_in 秒)。"""
        payload = {
            "appId": config.QQBOT_APP_ID,
            # 参数名是 clientSecret，不是 appSecret
            "clientSecret": config.QQBOT_APP_SECRET,
        }

        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            async with session.post(QQ_TOKEN_URL, json=payload) as resp:
                body = await self._read_json(resp)

                # 坑：业务错误时 HTTP 状态码仍然是 200，必须看 body 里有没有 code
                # （如 100007 appid invalid / 100016 secret 错误）。
                if "code" in body:
                    code = body.get("code")
                    message = body.get("message", "")
                    self.logger.error(f"获取 QQ access_token 失败: code={code} message={message}")
                    raise QQApiError(code, message)

                if resp.status != 200:
                    self.logger.error(f"获取 QQ access_token 失败: HTTP {resp.status}")
                    raise QQApiError(resp.status, body.get("message", ""))

                token = body.get("access_token")
                if not token:
                    self.logger.error("获取 QQ access_token 失败: 响应里没有 access_token")
                    raise QQApiError("no_access_token", "响应里没有 access_token")

                try:
                    expires_in = int(body.get("expires_in", 7200))
                except (TypeError, ValueError):
                    expires_in = 7200
                return token, expires_in

    async def _get_access_token(self) -> str:
        """拿一个可用的 access_token：有效期内直接用缓存，快到期了才重新取。"""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        async with self._token_lock:
            # 双重检查：等锁的这段时间里，前一个协程可能已经取好了
            if self._access_token and time.monotonic() < self._token_expires_at:
                return self._access_token

            token, expires_in = await self._fetch_access_token()
            self._access_token = token
            self._token_expires_at = (
                time.monotonic() + max(expires_in - _TOKEN_REFRESH_MARGIN_SECONDS, 0)
            )
            return token

    async def _send_qq_message(self, content: str) -> None:
        """把一条纯文本消息推到维护者的 QQ 单聊。失败抛 QQApiError。

        注意：access_token 只出现在请求头里，**绝不进日志**。
        """
        token = await self._get_access_token()
        url = QQ_MESSAGE_URL.format(openid=config.QQBOT_OWNER_OPENID)

        async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as session:
            async with session.post(
                url,
                headers={"Authorization": f"QQBot {token}"},
                json={"msg_type": 0, "content": content},
            ) as resp:
                body = await self._read_json(resp)

                # 文档说发消息失败是 4xx；但取 token 那个接口存在"HTTP 200 + body 带 code"
                # 的坑，同一套平台不排除消息接口也这样——两种都按失败处理，绝不假装送达。
                if resp.status != 200 or "code" in body:
                    code = body.get("code", resp.status)
                    message = body.get("message", "")
                    # 完整 code/message 是线上唯一的排障线索，必须落日志。
                    self.logger.error(
                        f"QQ 通知发送失败: HTTP {resp.status} code={code} message={message}"
                    )
                    raise QQApiError(code, message)

    # =================================================================
    # 消息组装与回执
    # =================================================================

    def _build_qq_text(self, interaction: discord.Interaction, description: str) -> str:
        """组装要发到 QQ 的纯文本（msg_type=0）。"""
        guild = interaction.guild
        guild_name = guild.name if guild else "未知服务器"
        guild_id = guild.id if guild else "未知"
        stamp = datetime.now(_UTC8).strftime("%Y-%m-%d %H:%M:%S")

        return (
            "[odysseia_ticket_bot] 管理组联系请求\n"
            f"来自: {interaction.user.display_name} (ID: {interaction.user.id})\n"
            f"服务器: {guild_name} (ID: {guild_id})\n"
            f"时间: {stamp} (UTC+8)\n"
            "--------\n"
            f"{description}"
        )

    def _success_embed(self) -> discord.Embed:
        remaining = max(DAILY_LIMIT - self._quota_used_today(), 0)
        embed = discord.Embed(
            title="✅ 已通过 QQ 通知维护者",
            description="维护者会通过 QQ 单聊收到你提交的问题描述。",
            color=discord.Color.green(),
        )
        embed.add_field(name="今日剩余额度", value=f"{remaining} 条 / {DAILY_LIMIT} 条")
        return embed

    def _quota_exhausted_embed(self) -> discord.Embed:
        return discord.Embed(
            title="❌ 今日额度已用完",
            description=(
                f"今日额度已用完（{DAILY_LIMIT} 条/天），请改用其他方式联系维护者。"
            ),
            color=discord.Color.red(),
        )

    def _not_configured_embed(self, missing: list[str]) -> discord.Embed:
        return discord.Embed(
            title="⚠️ 未配置：QQ 通知通道不可用",
            description=(
                "QQ 通知通道未配置，本命令当前不可用。\n"
                f"缺失的配置项：`{'`、`'.join(missing)}`\n"
                "请**联系 BOT 维护者**处理（这些值只能由维护者配置）。"
            ),
            color=discord.Color.red(),
        )

    def _send_failed_embed(self, error: Exception) -> discord.Embed:
        embed = discord.Embed(
            title="❌ 通知通道故障，消息未能送达",
            description=(
                "消息**未能送达**维护者的 QQ，请改用其他渠道联系维护者。\n"
                "（本次未计入今日额度）"
            ),
            color=discord.Color.red(),
        )
        code = getattr(error, "code", None)
        if code is not None:
            embed.add_field(name="错误码", value=str(code))
        return embed

    # =================================================================
    # 交互流程
    # =================================================================

    async def _handle_submit(self, interaction: discord.Interaction, description: str) -> None:
        """modal 提交后的处理：再查额度 → 组装消息 → 发送 → 回执。"""
        # 0. 立即 defer（ephemeral）：modal 提交的 interaction 必须在 3 秒内响应，
        #    且接下来要走两段跨境 HTTP（取 token + 发消息），耗时不可控。
        #    不 defer 直接 followup.send 会 404 Unknown Webhook（线上实测 10015，
        #    消息实际已发出、回执却发不出来——2026-11-11 首次线上使用时踩过）。
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1. 额度二次检查：modal 开着的时候额度可能已经被别人用掉了
        if self._quota_used_today() >= DAILY_LIMIT:
            await interaction.followup.send(embed=self._quota_exhausted_embed(), ephemeral=True)
            return

        # 2. 配置再检查一次：跟命令里那次分开，免得把"没配"报成"通道故障"
        missing = self._missing_qq_config()
        if missing:
            await interaction.followup.send(
                embed=self._not_configured_embed(missing), ephemeral=True
            )
            return

        # 3. 组装并发送
        text = self._build_qq_text(interaction, description)
        try:
            await self._send_qq_message(text)
        except Exception as e:
            self.logger.error(
                f"QQ 通知发送失败（发起人 {interaction.user.id}）: {e}", exc_info=True
            )
            await interaction.followup.send(
                embed=self._send_failed_embed(e), ephemeral=True
            )
            return

        # 4. 只有真的发出去了才计数
        self._daily_usage["count"] += 1
        await interaction.followup.send(embed=self._success_embed(), ephemeral=True)

    # =================================================================
    # 斜杠命令
    # =================================================================

    contact_group = prefixed_group(
        "运维",
        description="运维相关指令（紧急联系维护者）",
        guild_ids=[gid for gid in config.GUILD_IDS],
        # 刻意不设 default_permissions：权限判定走 @is_admin()（我们自己维护的
        # ID 表），不是 Discord 的权限位。管理组不一定有 manage_roles，
        # 把限制写在 Discord 层会把命令从他们眼前藏掉。
    )

    @contact_group.command(
        name="联系维护者",
        description=f"填写问题描述，通过 QQ 通知维护者（每日 {DAILY_LIMIT} 条额度）",
    )
    @is_admin()
    async def cmd_contact_maintainer(self, interaction: discord.Interaction):
        """弹窗收集问题描述，再推送到维护者的 QQ 单聊。"""
        # 1. 额度检查——用完了就别让用户白填一张表
        if self._quota_used_today() >= DAILY_LIMIT:
            await interaction.response.send_message(
                embed=self._quota_exhausted_embed(), ephemeral=True
            )
            return

        # 2. QQ 通道配置检查——没配就明说，不装成功
        missing = self._missing_qq_config()
        if missing:
            await interaction.response.send_message(
                embed=self._not_configured_embed(missing), ephemeral=True
            )
            return

        # 3. 弹窗
        await interaction.response.send_modal(ContactMaintainerModal(self))


async def setup(bot: "TicketBot"):
    """Cog的入口点。"""
    await bot.add_cog(ContactMaintainerCog(bot))
