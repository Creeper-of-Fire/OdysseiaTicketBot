"""归档频道权限守卫。

投诉系统的两条链路都要求 BOT 能访问「归档频道」：

- 工单编号计数器：读归档频道历史（找 ``[投诉计数]已发布N``）+ 写计数消息
- 归档文件投递：把归档文件发到归档频道

Discord 对"看不见频道"和"缺具体权限"返回不同的错误码：

- 50001 Missing Access —— BOT 看不见这个频道（缺「查看频道」权限）
- 50013 Missing Permissions —— 看得见，但缺某项操作权限（如「读取消息历史」）

两者对用户都是"点按钮没反应"（异常逃逸到 view 层被 discord.py 吞掉），
但排查方向完全不同。这里在发起请求前先做一次本地权限比对，
把缺失项直接说清楚，避免等 HTTP 403 才炸。

守卫只做**本地判定**：``permissions_for`` 读的是 Discord 下发的权限覆盖，
不需要额外 API 调用，也不产生任何副作用。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

logger = logging.getLogger(__name__)

# 工单编号计数器需要的权限：读历史（扫计数消息）+ 发消息（写计数消息）。
COUNTER_PERMISSIONS: tuple[str, ...] = ("read_message_history", "send_messages")

# 归档文件投递需要的权限：发消息 + 上传附件（归档文件本身是附件）。
ARCHIVE_PERMISSIONS: tuple[str, ...] = ("send_messages", "attach_files")


class ArchivePermissionError(RuntimeError):
    """BOT 对归档频道缺少必要权限。

    继承 ``RuntimeError``：既有的 ``except RuntimeError`` 分支仍能接住它，
    同时保留结构化字段供上层做本地化渲染。

    Attributes:
        channel_id: 归档频道 ID。
        missing: 缺失的权限名列表（Discord 官方英文标识）。
    """

    def __init__(self, channel_id: int, missing: list[str]) -> None:
        self.channel_id = channel_id
        self.missing = missing
        super().__init__(
            f"机器人缺少归档频道 <#{channel_id}> 的权限：{'、'.join(missing)}"
        )


def missing_permissions(
    channel: discord.abc.GuildChannel | discord.Thread,
    required: tuple[str, ...],
) -> list[str]:
    """返回 BOT 在该频道上缺失的权限名列表。

    ``channel.permissions_for(guild.me)`` 返回的是**有效权限**
    （服务器角色权限 ⊕ 频道覆盖 ⊕ 分类继承），与 Discord 服务端的判定一致，
    所以本地比对结果可以直接用来解释 403。

    权限名用 Discord 的官方英文标识（如 ``read_message_history``），
    便于管理员在 Discord 界面里对上号。

    拿不到有效权限时返回空列表（不误报），交由后续真实请求去报错。
    """
    guild = channel.guild
    me = guild.me
    if me is None:
        logger.warning("无法获取服务器 %s 的 BOT 成员对象，跳过权限预检", guild.id)
        return []

    try:
        effective = channel.permissions_for(me)
    except Exception:
        # permissions_for 在极少数边界情况（如线程父频道未缓存）会抛错；
        # 此时拿不到有效权限，交给后续的真实 HTTP 请求去报错。
        logger.warning("无法计算频道 %s 的 BOT 权限，跳过权限预检", channel.id, exc_info=True)
        return []

    missing: list[str] = []
    for name in required:
        if not getattr(effective, name, False):
            missing.append(name)
    return missing


def ensure_permissions(
    channel: discord.abc.GuildChannel | discord.Thread,
    required: tuple[str, ...],
) -> None:
    """权限不足时抛 :class:`ArchivePermissionError`。

    调用点应在真正发起 Discord 请求**之前**调用，把"权限缺失"变成
    一条明确的用户可见提示，而不是等 HTTP 403 冒泡。
    """
    missing = missing_permissions(channel, required)
    if missing:
        raise ArchivePermissionError(channel.id, missing)
