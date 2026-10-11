"""command_naming 单元测试 + **命名守卫**。

跑法：``python utility/test_command_naming.py``

这个测试同时是"所有命令组都必须走 prefixed_group"这条约定的**执行者**——
不是靠文档记着，而是靠下面两个守卫自动挡住绕过：
1. :func:`test_no_bypass_in_source` —— 源码里除 helper 本身外不许直接调 `app_commands.Group(`
2. :func:`test_every_registered_group_is_managed` —— 运行时每个已注册 cog 的命令组
   都必须是 :class:`ManagedGroup`
"""
from __future__ import annotations

import importlib
import inspect
import re
import sys
from pathlib import Path

# 让脚本能直接 import 项目包
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from discord import app_commands
from discord.ext import commands as dpy_commands

from utility.command_naming import (
    ManagedGroup,
    format_command_name,
    prefixed_group,
    prefixed_name,
)


def _registered_cog_classes() -> list[type]:
    """取出 bot 实际会加载的全部 Cog 类。

    **刻意不在这里维护清单。** ``TicketBot.cog_map`` 是实例属性（建在 ``__init__`` 里），
    类上取不到；而 ``main.py`` 顶部的 import 恰好把每个 cog 模块都拉了进来——
    所以 ``main`` 的命名空间就是真正的注册表。

    早先在 role_bot 上这里硬编码过一份 ``COG_MODULES``，结果是新增 cog 要人记得补一条，
    而且让守卫对某个尚未提交的新模块产生硬依赖（守卫属于"命令命名"，不该被某个功能的
    落地与否绑住）。改成从 main 推导后，加 cog 不用改测试。
    """
    main_mod = importlib.import_module("main")
    return sorted(
        {
            obj
            for _name, obj in inspect.getmembers(main_mod, inspect.isclass)
            if issubclass(obj, dpy_commands.Cog)
        },
        key=lambda c: f"{c.__module__}.{c.__qualname__}",
    )


# helper 自身与 shared/ 子树不参与扫描（后者是 _shared 的副本，另仓管理）
SCAN_SKIP = {"shared", "__pycache__", ".venv", "data", ".claude", ".idea"}


# ==================================================================
# 一、format_command_name：自动修 / 不自动修
# ==================================================================

def test_format_lowercases():
    """大写自动转小写——这是 Discord 的硬性要求，也是启动崩的根因。"""
    assert format_command_name("FooBar") == "foobar"
    assert format_command_name("SCAN_MEMBERS") == "scan_members"
    print("✅ 大写自动转小写 OK")


def test_format_keeps_chinese():
    """中文命令名合法，必须原样保留（不能被任何"清洗"动到）。"""
    assert format_command_name("投诉管理") == "投诉管理"
    assert format_command_name("许愿") == "许愿"
    print("✅ 中文原样保留 OK")


def test_format_rejects_illegal():
    """非法字符 / 空名不自动修，直接报错——静默改名字比崩更糟。"""
    for bad in ["bad name", "bad!name", "", "a" * 33]:
        try:
            format_command_name(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} 应当报错而不是被自动修好")
    print("✅ 非法名 fail-loud OK")


def test_format_error_names_source():
    """报错要能指出来源，否则几个 cog 里排查靠猜。"""
    try:
        format_command_name("bad name", where="测试组")
    except ValueError as exc:
        assert "测试组" in str(exc), f"报错里应含来源，实际: {exc}"
        print("✅ 报错带来源 OK")
    else:
        raise AssertionError("应当报错")


def test_format_error_explains_pipe():
    """ASCII `|` 和全角 `｜` 都被拒、只有汉字 `丨` 行——报错要直接说这件事。

    这是最容易踩的一个坑：看着都是竖线，Discord 只认 U+4E28 那个。
    """
    for bad, label in [("装饰|同步", "|"), ("装饰｜同步", "｜")]:
        try:
            format_command_name(bad)
        except ValueError as exc:
            assert "丨" in str(exc), f"{label} 的报错应提示改用「丨」，实际: {exc}"
        else:
            raise AssertionError(f"{bad!r} 应当被拒绝")
    # 反证：换成 U+4E28 就合法
    assert format_command_name("装饰丨同步") == "装饰丨同步"
    print("✅ 竖线类字符报错会指路到「丨」OK")


# ==================================================================
# 二、ManagedGroup：组名 / 子命令名 / 推导名 都自动格式化
# ==================================================================

def test_group_name_normalized():
    """组名自动小写化。注意期望值用 prefixed_name() 推导，不写死——
    换前缀时这个测试不该跟着改。"""
    g = prefixed_group("MixedCase", description="d")
    assert isinstance(g, ManagedGroup)
    expected = prefixed_name("mixedcase")
    assert g.name == expected, f"got {g.name!r}, want {expected!r}"
    print(f"✅ 组名自动小写 OK: {g.name!r}")


def test_subcommand_name_normalized():
    g = prefixed_group("测试组", description="d")

    @g.command(name="SubCMD", description="x")
    async def _cb(interaction):  # noqa: ARG001
        pass

    assert [c.name for c in g.commands] == ["subcmd"], [c.name for c in g.commands]
    print("✅ 子命令名自动小写 OK")


def test_derived_subcommand_name_normalized():
    """没写 name= 时 discord.py 直接拿函数名当命令名且不转小写——这里兜住。

    没有这层，`async def SendPanel` 会让 bot 在 import 阶段就崩。
    """
    g = prefixed_group("测试组", description="d")

    @g.command(description="x")
    async def SendPanel(interaction):  # noqa: N802, ARG001
        pass

    assert [c.name for c in g.commands] == ["sendpanel"], [c.name for c in g.commands]
    print("✅ 推导名自动小写 OK")


def test_nested_group_normalized():
    outer = prefixed_group("外层", description="d")
    inner = prefixed_group("Inner", description="d")
    outer.add_command(inner)
    expected = prefixed_name("inner")
    assert inner.name == expected, f"got {inner.name!r}, want {expected!r}"
    print(f"✅ 嵌套子组自动小写 OK: {inner.name!r}")


# ==================================================================
# 三、prefixed_name：前缀由 config 决定，且能用它校验文案
# ==================================================================

def test_prefixed_name_matches_prefixed_group():
    """文案里推导出来的名字，必须跟 Discord 上真实注册的名字一模一样。"""
    g = prefixed_group("投诉管理", description="d")
    assert prefixed_name("投诉管理") == g.name
    print(f"✅ prefixed_name 与实际组名一致: {g.name!r}")


# ==================================================================
# 四、守卫：所有命令组都必须走 prefixed_group
# ==================================================================

def test_no_bypass_in_source():
    """守卫 A：源码扫描——除 helper 外不许直接 `app_commands.Group(`。

    这条是"新增 cog 自动受管"的关键：不用维护清单，加了新 cog 也照样被扫到。
    """
    pattern = re.compile(r"app_commands\.Group\(")
    offenders = []
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if rel.parts and rel.parts[0] in SCAN_SKIP:
            continue
        if rel == Path("utility/command_naming.py") or rel == Path(
            "utility/test_command_naming.py"
        ):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")

    assert not offenders, "这些地方绕开了 prefixed_group，会跳过命令名格式化：\n" + "\n".join(
        offenders
    )
    print("✅ 守卫 A：源码里没有绕过 prefixed_group 的命令组")


def test_every_registered_group_is_managed():
    """守卫 B：运行时——每个 cog 的命令组都必须是 ManagedGroup 实例。"""
    checked = 0
    offenders = []
    for cls in _registered_cog_classes():
        where = f"{cls.__module__}.{cls.__qualname__}"
        for attr, value in vars(cls).items():
            if isinstance(value, app_commands.Group):
                checked += 1
                if not isinstance(value, ManagedGroup):
                    offenders.append(f"{where}.{attr}")

    assert checked, "一个命令组都没找到——是 _registered_cog_classes() 的推导失效了吗"
    assert not offenders, f"这些命令组不是 prefixed_group 造的：{offenders}"
    print(f"✅ 守卫 B：{checked} 个命令组全部来自 prefixed_group")


if __name__ == "__main__":
    test_format_lowercases()
    test_format_keeps_chinese()
    test_format_rejects_illegal()
    test_format_error_names_source()
    test_format_error_explains_pipe()
    test_group_name_normalized()
    test_subcommand_name_normalized()
    test_derived_subcommand_name_normalized()
    test_nested_group_normalized()
    test_prefixed_name_matches_prefixed_group()
    test_no_bypass_in_source()
    test_every_registered_group_is_managed()
    print("\n🎉 All command_naming tests passed.")