from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod, ABCMeta
from dataclasses import dataclass
from typing import List, TYPE_CHECKING, Optional

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from core.CoreCog import CoreCog
    from main import TicketBot

@dataclass
class PanelEntry:
    """主面板上的一个功能入口"""
    button: discord.ui.Button
    description: Optional[str] = None # 描述是可选的

# 1. 定义一个新的组合元类
#    这个新元类同时继承了 CogMeta 和 ABCMeta，解决了冲突
class CogABCMeta(commands.CogMeta, ABCMeta):
    pass


class FeatureCog(commands.Cog, ABC, metaclass=CogABCMeta):
    """
    功能模块Cog的基类。

    自动处理 bot 和 logger 的初始化，并提供向 CoreCog 注册的标准流程。
    所有继承此基类的 Cog 都必须实现 `update_safe_roles_cache` 方法。
    """

    def __init__(self, bot: 'TicketBot'):
        """
        初始化基类，设置 bot 和 logger 实例。
        """
        self.bot = bot
        self.logger = bot.logger.getChild(self.__class__.__name__)

    @property
    def core_cog(self) -> CoreCog | None:
        core_cog: CoreCog | None = self.bot.get_cog("Core")
        return core_cog

    @property
    def role_name_cache(self) -> dict[int, str] | None:
        core_cog: CoreCog | None = self.core_cog
        if (core_cog is None) or (core_cog.role_name_cache is None):
            return None
        return core_cog.role_name_cache

    async def cog_load(self) -> None:
        """
        当Cog被加载时，等待并向 CoreCog 注册自己。
        子类如果需要覆盖此方法，必须调用 `await super().cog_load()`。
        """
        # 短暂等待，以确保 CoreCog 已经加载完毕
        await asyncio.sleep(1)

        core_cog: CoreCog | None = self.bot.get_cog("Core")

        if core_cog:
            # 调用 CoreCog 的注册方法，把自己传进去
            core_cog.register_feature_cog(self)
            self.logger.info(f"模块 {self.qualified_name} 已注册到 CoreCog")
        else:
            self.logger.error(f"无法找到 CoreCog。模块 {self.qualified_name} 的功能将受限，无法自动更新缓存。")
