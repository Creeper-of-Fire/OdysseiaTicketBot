from __future__ import annotations

import asyncio
import gc
import io
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

from .archive_export import build_archive

if TYPE_CHECKING:
    from complaint.config.models import ComplaintConfig

logger = logging.getLogger(__name__)


class ComplaintArchiveService:
    def __init__(self, config: ComplaintConfig):
        self._config = config
        self._semaphore = asyncio.Semaphore(config.global_.archive_concurrent_limit)

    async def archive_channel(
        self,
        channel: discord.TextChannel,
        *,
        type_label: str,
        type_emoji: str,
        complainant_id: int,
        visibility: str,
        form_data: dict[str, str],
    ) -> None:
        """归档频道并发送到归档频道，然后删除原频道。

        严格保证：只有在归档文件生成且成功发送到归档频道后，才删除原频道。
        """
        guild = channel.guild
        archive_channel_id = self._config.guild.archive_channel_id
        if not archive_channel_id:
            raise RuntimeError("未配置归档频道，请先使用 /投诉管理 配置服务器")

        archive_channel = guild.get_channel(archive_channel_id)
        if not isinstance(archive_channel, discord.TextChannel):
            raise RuntimeError("归档频道不可用")

        header_lines = self._build_header_lines(
            channel=channel,
            type_label=type_label,
            type_emoji=type_emoji,
            complainant_id=complainant_id,
            visibility=visibility,
            form_data=form_data,
        )

        result = None
        try:
            # Phase 1: 生成归档（受并发信号量限制）
            async with self._semaphore:
                result = await build_archive(
                    channel=channel,
                    header_lines=header_lines,
                    guild_filesize_limit=int(guild.filesize_limit),
                    media_budget_bytes=self._media_budget_bytes(),
                    single_image_max_bytes=self._single_image_max_bytes(),
                    archive_title=f"投诉归档 - {type_label}",
                )

            # Phase 2: 严格验证归档生成结果
            if result is None:
                raise RuntimeError("归档生成失败：build_archive 返回 None")
            if not result.data:
                raise RuntimeError("归档生成失败：归档数据为空")
            if not result.mode:
                raise RuntimeError("归档生成失败：归档模式未知")

            # Phase 3: 发送到归档频道
            summary = discord.Embed(
                title=f"{type_emoji} 投诉归档｜{type_label}",
                description=f"已从 {channel.mention} 导出为 {result.mode.upper()}。",
                color=0x2B2D31,
            )
            summary.add_field(
                name="投诉人",
                value=f"<@{complainant_id}> (`{complainant_id}`)",
                inline=True,
            )
            summary.add_field(name="类型", value=f"{type_emoji} {type_label}", inline=True)
            summary.add_field(name="可见性", value=visibility, inline=True)

            if form_data:
                desc_lines = []
                for key, value in form_data.items():
                    desc_lines.append(f"**{key}**：{value[:200]}")
                summary.add_field(
                    name="表单内容",
                    value="\n".join(desc_lines)[:1024],
                    inline=False,
                )

            if result.warnings:
                summary.add_field(
                    name="注意",
                    value="\n".join(result.warnings)[:1024],
                    inline=False,
                )

            ext = "zip" if result.mode == "zip" else "html"
            filename = f"complaint-{channel.id}-archive.{ext}"
            file = discord.File(fp=io.BytesIO(result.data), filename=filename)

            sent_msg = await archive_channel.send(
                embed=summary,
                file=file,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            # Phase 4: 严格验证发送结果
            if sent_msg is None:
                raise RuntimeError("归档发送失败：Discord API 未返回消息对象")
            if not sent_msg.attachments:
                raise RuntimeError(
                    f"归档发送验证失败：已发送消息 (ID: {sent_msg.id}) 中未检测到附件"
                )

            logger.info(
                "归档发送验证通过：频道 %s 的归档已发送到 %s (消息 ID: %s, 附件数: %d)",
                channel.id, archive_channel.id, sent_msg.id, len(sent_msg.attachments),
            )

            # Phase 5: 归档已确认成功，安全删除原频道
            try:
                await channel.delete(reason=f"投诉频道已归档 - {type_label}")
            except Exception as e:
                logger.error("归档后删除频道 %s 失败: %s", channel.id, e)
                raise RuntimeError(f"归档成功但删除频道失败: {e}")

        except RuntimeError:
            raise
        except Exception as e:
            logger.error("归档频道 %s 失败: %s", channel.id, e, exc_info=True)
            raise RuntimeError(f"归档失败: {e}")
        finally:
            result = None
            gc.collect()

    def _build_header_lines(
        self,
        *,
        channel: discord.TextChannel,
        type_label: str,
        type_emoji: str,
        complainant_id: int,
        visibility: str,
        form_data: dict[str, str],
    ) -> list[str]:
        now = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M UTC")
        lines = [
            f"投诉类型：{type_emoji} {type_label}",
            f"频道：{channel.name}（ID：{channel.id}）",
            f"可见性：{visibility}",
            f"投诉人：{complainant_id}",
            f"归档时间：{now}",
        ]
        if form_data:
            lines.append("")
            for key, value in form_data.items():
                lines.append(f"{key}：{value}")
        return lines

    def _media_budget_bytes(self) -> int:
        mb = self._config.global_.media_budget_mb
        return mb * 1024 * 1024 if mb > 0 else 0

    def _single_image_max_bytes(self) -> int:
        mb = self._config.global_.single_image_max_mb
        return mb * 1024 * 1024 if mb > 0 else 0
