# shared/app_command_group.py
"""命令名的**唯一实现**——三个 bot 共用。所有 `app_commands.Group` 都必须从这里造。

本模块是纯逻辑，**不认识任何具体 bot**：它不 import 宿主的 ``config``，命令组前缀由
各 bot 在启动时通过 :func:`init_command_prefix` 显式声明（见 role_bot 的
``utility/command_naming.py``）。

为什么要有这个模块（两个理由，互相独立）
==========================================

**1. 前缀是配置，不是散落在各处的字符串。**
以前每个 cog 自己写 ``app_commands.Group(name=f"{config.COMMAND_GROUP_NAME}丨合战丨核心")``，
想加品牌前缀就得改二十几个文件。现在组内本地名（``合战丨核心``）写在 cog 里，前缀统一拼
——**加前缀 / 换格式 / 彻底去掉前缀，都只改 bot 启动处一行**。

也正因如此，**文档里不要写死前缀**：前缀会改，组内本地名不会改。docs / README /
代码里的 docstring 与注释一律只写本地名（``合战丨核心``），需要展示完整命令名的地方
用 :func:`prefixed_name` 推导。

**2. 命令名在这里自动格式化。**
Discord 命令名的硬性限制：可以是中文，但**不允许大写字母**，也不允许空格等非法字符。
discord.py 在**构造期**（``Command.__init__`` / ``Group.__init__``）就调 ``validate_name``
校验——而 Group 是模块级类属性，等于 **import 阶段就抛 ValueError，整个 bot 起不来**。

所以命令名统一从 :func:`format_command_name` 过一遍：

- 大写自动转小写（大小写没有语义，转了就对了）
- 其余非法项（空格 / 非法符号 / 超 32 字符 / 空名）**不自动修**，直接报错并指出来源
  ——自动截断或丢字符会让命令名静默变成另一个意思，宁可启动就崩

各 bot 怎么用
=============

**声明前缀**（每个 bot 一个薄入口，在 import 期完成）::

    # role_bot/utility/command_naming.py
    import config
    from shared.app_command_group import init_command_prefix, ...
    init_command_prefix(config.COMMAND_GROUP_NAME)

**定义命令组**（各 cog 一行导入，之后不用再管前缀）::

    from utility.command_naming import prefixed_group

    admin_group = prefixed_group("合战丨核心", description="创作大会管理")

子命令照常用 ``@admin_group.command(name=..., description=...)``——名字会被自动格式化。

**为什么不用"注册机制"（bot 启动时调 init，cog 通过全局拿）**
------------------------------------------------------------

命令组是 **class 属性，在 cog 被 import 的那一刻就构造完了**。而 ``main.py`` 顶部的
``from core.CoreCog import CoreCog`` 这些行，**比 main.py 函数体里的任何语句都先执行**。
把 ``init`` 写在 main.py 函数体里，来不及——前缀会静默变成 ``None丨核心``。

所以初始化必须由 **import 图**保证，而不是靠"记得写在所有 cog import 之前"。各 bot 那层
薄入口（``utility/command_naming.py``）存在的意义就在这：cog import 它的时候，前缀必然
已经初始化好了。忘了初始化会直接抛 RuntimeError（见 :func:`_require_prefix`），不会静默。
"""

from __future__ import annotations

from typing import Any, Callable, Coroutine, Optional

from discord import app_commands
from discord.app_commands.commands import validate_name
from discord.utils import MISSING

# 前后缀之间的分隔符——`李曦曦丨装饰丨同步` 里的那个 `丨`。
# 组内本地名本身也可以含 `丨`（如 `装饰丨同步`），用来表达命令组的层级。
_GROUP_NAME_SEPARATOR = "丨"

# 「本来想写这个，结果被 Discord 拒了」的对照表。
# discord.py 的报错只说"只允许小写字母/数字/连字符/下划线"，不会告诉你是哪个字符的问题，
# 更不会说「丨 行、| 不行」。这里补上，省得每次都去翻 discord 源码。
#
# 根因：discord 的名字正则大致是 `^[-_\w...]{1,32}$`，而 `\w`（Unicode 模式）匹配**汉字**。
# `丨`（U+4E28）本身就是汉字 → 过；`|`（ASCII）和 `｜`（U+FF5C 全角）都是标点 → 不过。
_CHAR_HINTS = {
    "|": "分隔符请用 U+4E28 的「丨」——ASCII 竖线 | 和全角 ｜ 都是标点，Discord 一律拒绝",
    "｜": "分隔符请用 U+4E28 的「丨」——全角 ｜ 也是标点，Discord 拒绝",
    " ": "名字里不能有空格（命令组与子命令之间在 Discord 里本来就是空格分隔的）",
    ":": "名字里不能用冒号",
    ".": "名字里不能用点",
    "/": "名字里不能用斜杠（/ 是 Discord 自己加分组的记号）",
}

# 本进程的命令组前缀。None = 还没初始化。刻意用 None 而不是 ""——
# 未初始化和"显式配了空前缀"是两回事，前者必须炸出来。
_prefix: Optional[str] = None


def init_command_prefix(prefix: str) -> None:
    """声明本 bot 的命令组前缀。**必须在任何 cog 被 import 之前**调用。

    各 bot 应该在各自的薄入口模块里调一次（role_bot: ``utility/command_naming.py``），
    那个模块由 cog import，从而保证顺序，而不是靠人记着写在 main.py 的哪一行。

    传空字符串 ``""`` 表示不加前缀（此时 :func:`prefixed_name` 直接返回本地名）。
    """
    global _prefix
    _prefix = prefix


def _require_prefix() -> str:
    """取当前前缀；没初始化过就抛——绝不静默用空值。"""
    if _prefix is None:
        raise RuntimeError(
            "命令组前缀尚未初始化。请在 bot 启动入口调用 "
            "init_command_prefix(config.COMMAND_GROUP_NAME)，"
            "且必须发生在任何 cog 被 import 之前"
            "（命令组是 class 属性，import 期就构造完了）。"
        )
    return _prefix


def format_command_name(name: str, *, where: str = "") -> str:
    """把命令名规范化成 Discord 允许的形式，并返回规范化后的名字。

    - **大写自动转小写**：``"FooBar" -> "foobar"``。
    - **其余非法项直接报错**：非法字符 / 超过 32 字符 / 空名。这几类不自动"修"——
      自动截断或丢弃字符会让命令名静默变成另一个意思，炸在启动时比发给用户一个错命令好。
      报错会额外指出**具体是哪个字符的问题**（见 ``_CHAR_HINTS``）——
      比如写了 ``装饰|同步`` 会直接告诉你该用 ``装饰丨同步``。

    ``where`` 只用于在报错里指出这个名字的来源（哪个组、哪条命令），排查时省事。
    合法性判定直接用 discord.py 自己的 :func:`validate_name`，不自己重写那份正则——
    免得库升级改了规则、我们这边还以为过。
    """
    normalized = name.lower()
    try:
        return validate_name(normalized)
    except ValueError as exc:
        ctx = f"（{where}）" if where else ""
        hints = "；".join(_CHAR_HINTS[ch] for ch in _CHAR_HINTS if ch in name)
        hint_line = f"\n  ↳ {hints}" if hints else ""
        raise ValueError(f"命令名 {name!r}{ctx} 非法：{exc}{hint_line}") from None


def prefixed_name(local_name: str) -> str:
    """把组内本地名补全成 Discord 上实际展示的完整命令组名。

    仅在需要把**完整命令名**写进用户可见文案时使用；定义 Group 本身请用
    :func:`prefixed_group`。前缀取自 :func:`init_command_prefix` 声明的值，因此改前缀时
    文案自动跟着变——这也是**不要在文案/文档里手写命令名**的原因。
    """
    prefix = _require_prefix()
    if not prefix:
        return format_command_name(local_name, where="命令组名")
    return format_command_name(
        f"{prefix}{_GROUP_NAME_SEPARATOR}{local_name}", where="命令组名"
    )


class ManagedGroup(app_commands.Group):
    """命令名自动格式化的 ``app_commands.Group``。

    覆写 ``__init__`` / ``command()``，让**组名、子命令名、以及没写 ``name=`` 时由
    函数名推导出的名字**统统过 :func:`format_command_name`。这样几十个子命令一个都不用
    改，误写 CamelCase 也不会让 bot 在 import 阶段崩掉。

    不要直接用 ``app_commands.Group(...)``——绕开这里就等于绕开格式化，
    各 bot 的 ``test_app_command_group.py`` 里的守卫测试会失败。
    """

    def __init__(self, **kwargs: Any) -> None:
        name = kwargs.get("name")
        if isinstance(name, str):
            kwargs["name"] = format_command_name(name, where="命令组名")
        super().__init__(**kwargs)

    def command(
        self,
        *,
        name: Any = MISSING,
        description: Any = MISSING,
        nsfw: bool = False,
        auto_locale_strings: bool = True,
        extras: Any = MISSING,
    ) -> Callable[[Callable[..., Coroutine[Any, Any, Any]]], Any]:
        """``app_commands.Group.command``，额外把命令名过一遍格式化。

        多做一件事：**没写 ``name=`` 时** discord.py 直接拿 Python 函数名当命令名，
        且**不会**转小写（``async def SendPanel`` -> ValueError，import 阶段崩）。
        这里改成用小写化的函数名，让"忘了写 name="不至于炸掉整个 bot。
        """
        explicit_name = isinstance(name, str)
        if explicit_name:
            name = format_command_name(name, where="子命令名")

        def make_decorator(final_name: Any) -> Callable[..., Any]:
            return super(ManagedGroup, self).command(
                name=final_name,
                description=description,
                nsfw=nsfw,
                auto_locale_strings=auto_locale_strings,
                extras=extras,
            )

        if explicit_name:
            return make_decorator(name)

        def wrapper(func: Callable[..., Any]) -> Any:
            return make_decorator(
                format_command_name(
                    func.__name__, where=f"子命令名（由函数 {func.__name__} 推导）"
                )
            )(func)

        return wrapper


def prefixed_group(name: str, **kwargs: Any) -> ManagedGroup:
    """建一个命令组——**所有 cog 都必须走这个函数**。

    用法::

        admin_group = prefixed_group("合战丨核心", description="创作大会管理")

    ``name`` 是**组内本地名**（不含前缀）。其余参数（``description`` / ``guild_ids`` /
    ``guild_only`` / ``default_permissions`` / ``nsfw``）原样透传给 ``app_commands.Group``。
    """
    return ManagedGroup(name=prefixed_name(name), **kwargs)