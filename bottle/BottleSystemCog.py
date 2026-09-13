"""bottle 系统 cog 入口。

启动流程:
1. setup_hook 遍历 bot.guilds,逐 guild 调 self._try_enable(guild_id)
2. _try_enable:调 selfManager.load(guild_id) 加载 toml
   - ValidationError / ValueError → logger.exception,该 guild 跳过
   - 成功 → 缓存 config,创建 BottleService
3. cog_load:注册 BottlePanelView(常驻) + 启动 recycle_loop 后台 task
4. 后台 task 每 60 秒遍历所有 enabled guild 做 recycle_stale

toml 命令:
- / /上传配置、/下载配置、/查看配置哈希 走 _shared/ 通用 handler
- 配置 invalidate 后下次访问重新 load
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import tasks
from pydantic import ValidationError

import config
from shared.config.toml_command import (
    handle_toml_download,
    handle_toml_upload,
    handle_toml_view_hash,
)
from shared.config.toml_manager import TomlConfigManager
from utility.feature_cog import FeatureCog

from .bottle_config import BottleConfig
from .panel import BottlePanelView
from .service import BottleDataManager, BottleService

if TYPE_CHECKING:
    from main import TicketBot

logger = logging.getLogger(__name__)


class BottleSystemCog(FeatureCog):
    """bottle 漂流瓶系统 cog。"""

    # ----- 配置管理 -----

    DATA_DIR = Path("data")
    FILENAME_PATTERN = "bottle_{guild_id}.toml"
    DOC_PATH = Path("docs") / "bottle-doc.md"

    def __init__(self, bot: "TicketBot"):
        super().__init__(bot)

        self._configs: dict[int, BottleConfig] = {}
        self._services: dict[int, BottleService] = {}
        self._data_manager = BottleDataManager.get_instance(logger=self.logger)

        self.toml_manager = TomlConfigManager(
            data_dir=self.DATA_DIR,
            filename_pattern=self.FILENAME_PATTERN,
            model_class=BottleConfig,
            doc_path=self.DOC_PATH,
        )

        # 注册常驻 panel view(持久化,bot 重启后按钮仍可用)
        self.bot.add_view(BottlePanelView(self))
        self.logger.info("BottlePanelView 已注册")

    # ----- guild 启停 -----

    def is_enabled(self, guild_id: int) -> bool:
        return guild_id in self._services

    def _try_enable(self, guild_id: int) -> bool:
        """尝试加载 toml 并启用该 guild。失败 → False,logger.exception。"""
        try:
            cfg = self.toml_manager.load(guild_id)
        except (ValidationError, ValueError) as e:
            self.logger.exception(
                "guild %s bottle 配置缺失或非法,该 guild bottle 功能禁用: %s",
                guild_id, e,
            )
            return False
        self._configs[guild_id] = cfg
        self._services[guild_id] = BottleService(self._data_manager, guild_id, cfg)
        self.logger.info("guild %s bottle 已启用(max_held=%d)", guild_id, cfg.max_held_per_user)
        return True

    def _invalidate(self, guild_id: int) -> None:
        """toml 更新后清缓存,下次访问重新 load。"""
        self._configs.pop(guild_id, None)
        self._services.pop(guild_id, None)

    def service_for(self, guild_id: int) -> BottleService:
        """取 service;若该 guild 之前缺配置被禁用,这里 lazy 尝试启用一次。"""
        svc = self._services.get(guild_id)
        if svc is not None:
            return svc
        if self._try_enable(guild_id):
            return self._services[guild_id]
        raise RuntimeError(
            f"guild {guild_id} bottle 配置缺失或非法,功能未启用。"
            f"请检查 data/bottle_{guild_id}.toml,参考 docs/bottle-doc.md。"
        )

    # ----- lifecycle -----

    async def cog_load(self):
        """遍历所有 guild 尝试启用 + 启动后台回收 task。"""
        for guild in self.bot.guilds:
            self._try_enable(guild.id)

        if not self.recycle_loop.is_running():
            self.recycle_loop.start()

    async def cog_unload(self):
        if self.recycle_loop.is_running():
            self.recycle_loop.cancel()
            try:
                await self.recycle_loop
            except (asyncio.CancelledError, Exception):
                pass

    @tasks.loop(seconds=60)
    async def recycle_loop(self):
        """每 60 秒遍历所有 enabled guild 做 recycle_stale。"""
        """每 60 秒(默认)遍历所有 enabled guild 做 recycle_stale。"""
        for guild_id, svc in list(self._services.items()):
            try:
                reclaimed, expired = await svc.recycle_stale()
                if reclaimed or expired:
                    self.logger.info(
                        "guild %s recycle: 回收 %d (回海), %d (过期)",
                        guild_id, reclaimed, expired,
                    )
            except Exception:
                self.logger.exception(
                    "guild %s recycle 失败,该 guild 暂时跳过", guild_id,
                )

    @recycle_loop.before_loop
    async def before_recycle_loop(self):
        await self.bot.wait_until_ready()

    # ----- slash commands -----

    bottle_group = app_commands.Group(
        name=f"{config.COMMAND_GROUP_NAME}丨漂流瓶管理",
        description="漂流瓶系统管理(toml / 面板)",
        guild_ids=[gid for gid in config.GUILD_IDS],
        default_permissions=discord.Permissions(manage_channels=True),
    )

    @bottle_group.command(name="发布面板", description="在当前频道发布常驻 panel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_post_panel(self, interaction: discord.Interaction):
        gid = interaction.guild_id
        if gid is None:
            await interaction.response.send_message("❌ 只能在服务器中使用。", ephemeral=True)
            return
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message("❌ 无法定位当前频道。", ephemeral=True)
            return

        # 确认该 guild bottle 功能已启用(toml 已加载)
        try:
            svc = self.service_for(gid)
        except RuntimeError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            pool = svc._pool()
            embed = discord.Embed(
                title="🌊 漂流瓶",
                description=(
                    "在这里投放、捞取漂流瓶。\n"
                    "• 发布者实名,捞到的人可以认领 / 跳过\n"
                    "• 认领后有完成时限;海里过期后自动作废"
                ),
                color=discord.Color.blue(),
            )
            embed.add_field(name="🌊 海里", value=str(len(pool.available)), inline=True)
            embed.add_field(name="🤝 已认领", value=str(len(pool.claimed)), inline=True)
            embed.add_field(name="✅ 已完成", value=str(len(pool.completed)), inline=True)
            view = BottlePanelView(self)
            await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.edit_original_response(content="❌ 没有权限在该频道发消息。")
            return
        except Exception as e:
            self.logger.exception("发布 panel 失败 guild=%s", gid)
            await interaction.edit_original_response(content=f"❌ 发布失败: {e}")
            return
        await interaction.edit_original_response(content="✅ Panel 已发布到当前频道。")

    @bottle_group.command(
        name="上传配置",
        description="上传修改后的 toml;本地有配置时必须把 SHA-256 粘到 hash_str 字段",
    )
    @app_commands.describe(
        toml_file="修改后的 toml 文件",
        hash_str="SHA-256 校验值(前 12 字符);首次上传可省",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_upload_config(
        self,
        interaction: discord.Interaction,
        toml_file: discord.Attachment,
        hash_str: str | None = None,
    ):
        # 先按现有规则跑(可能 invalidate 缓存),handler 内部不会改 cog 状态
        # 我们在调用前记录 guild_id,handler 写盘成功后我们 invalidate
        gid = interaction.guild_id
        await handle_toml_upload(
            interaction,
            manager=self.toml_manager,
            toml_file=toml_file,
            hash_str=hash_str,
            label="bottle",
            permission_check=None,
        )
        # handle_toml_upload 成功后会 send_message,所以这里的 invalidate 应该只
        # 在没抛错时执行;但 handler 已经 send 完,我们在 followup 上发 invalidate 结果。
        if gid is not None:
            self._invalidate(gid)
            self._try_enable(gid)

    @bottle_group.command(
        name="下载配置",
        description="下载当前 toml + 教程 doc;当前 SHA-256 前 12 字符在 embed 里显示",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_download_config(self, interaction: discord.Interaction):
        await handle_toml_download(
            interaction,
            manager=self.toml_manager,
            label="bottle",
            permission_check=None,
        )

    @bottle_group.command(
        name="查看配置哈希",
        description="查看当前 toml 的 SHA-256(上传时用来防止覆盖别人版本)",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def cmd_view_hash(self, interaction: discord.Interaction):
        await handle_toml_view_hash(
            interaction,
            manager=self.toml_manager,
            label="bottle",
            permission_check=None,
        )


async def setup(bot: "TicketBot"):
    """cog setup hook。"""
    await bot.add_cog(BottleSystemCog(bot))