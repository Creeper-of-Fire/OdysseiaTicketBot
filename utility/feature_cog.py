from __future__ import annotations

from abc import ABC, ABCMeta
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from core.CoreCog import CoreCog
    from main import TicketBot


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
