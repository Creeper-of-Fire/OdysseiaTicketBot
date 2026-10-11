# utility/command_naming.py
"""OdysseiaTicketBot 的命令命名入口——**本 bot 的命令组前缀在这里声明一次**。

实际实现在 ``shared/app_command_group.py``（三个 bot 共用，纯逻辑，不认识任何具体 bot）。
本模块只做两件事：

1. 拿本 bot 的 ``config.COMMAND_GROUP_NAME`` 调 :func:`init_command_prefix`
2. 原样再导出命名工具，让各 cog 只需要认一个 import 路径

为什么 init 放这儿、而不是 main.py 开头
------------------------------------

命令组是 **class 属性，在 cog 被 import 的那一刻就构造完了**。而 ``main.py`` 顶部的
``from core.CoreCog import CoreCog`` 这些行，**比 main.py 函数体里的任何语句都先执行**——
把 ``init`` 写在 main.py 函数体里会来不及，前缀会静默变成 ``None丨核心``。

放在本模块就由 **import 图**保证了：cog ``from utility.command_naming import prefixed_group``
的时候，本模块先执行完 init，之后 cog 的类体才开始求值。顺序不靠人记。
"""
from __future__ import annotations

import config
from shared.app_command_group import (
    ManagedGroup,
    format_command_name,
    init_command_prefix,
    prefixed_group,
    prefixed_name,
)

init_command_prefix(config.COMMAND_GROUP_NAME)

__all__ = [
    "ManagedGroup",
    "format_command_name",
    "init_command_prefix",
    "prefixed_group",
    "prefixed_name",
]