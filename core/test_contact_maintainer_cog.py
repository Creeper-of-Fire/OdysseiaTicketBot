# core/test_contact_maintainer_cog.py

"""ContactMaintainerCog 最小化自测（mock bot，不连 Discord、不连 QQ）。

跑法：``python core/test_contact_maintainer_cog.py``

跟 ``utility/test_command_naming.py`` 同 pattern：mock 掉 bot / interaction，
只验"不依赖线上环境"的那部分逻辑——cog 能构造、命令组名对、modal 对、
额度跨天归零、发送成功才计数、QQ 消息文本格式对。

不测的部分（需要真实 token / 网络）：QQ 平台 token 换取、消息真发出去。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core.contact_maintainer_cog import (
    DAILY_LIMIT,
    ContactMaintainerCog,
    ContactMaintainerModal,
    _UTC8,
)
from utility.command_naming import prefixed_name

logging.basicConfig(level=logging.WARNING)


class MockBot:
    def __init__(self):
        self.logger = logging.getLogger("mock")


class MockFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return None


class MockUser:
    def __init__(self, uid: int = 1, display_name: str = "测试用户"):
        self.id = uid
        self.display_name = display_name


class MockGuild:
    def __init__(self, gid: int = 100, name: str = "测试服务器"):
        self.id = gid
        self.name = name


class MockResponse:
    """modal 提交后 cog 会先 defer 再 followup——记录 defer 调用以便断言。"""

    def __init__(self):
        self.deferred = False
        self.defer_kwargs: dict = {}

    async def defer(self, **kwargs):
        self.deferred = True
        self.defer_kwargs = kwargs


class MockInteraction:
    def __init__(self):
        self.user = MockUser()
        self.guild = MockGuild()
        self.followup = MockFollowup()
        self.response = MockResponse()


def _fake_qq_config():
    """临时填上 QQ 配置——测试不依赖 .env，也不碰真凭据。"""
    return (
        mock.patch.object(config, "QQBOT_APP_ID", "test-app-id"),
        mock.patch.object(config, "QQBOT_APP_SECRET", "test-app-secret"),
        mock.patch.object(config, "QQBOT_OWNER_OPENID", "test-openid"),
    )


def test_cog_init():
    """cog 能构造，命令组名正确。"""
    cog = ContactMaintainerCog(MockBot())
    assert cog.contact_group.name == prefixed_name("运维"), cog.contact_group.name
    assert cog._daily_usage == {"date": "", "count": 0}
    print(f"✅ cog init OK; group name = {cog.contact_group.name}")


def test_command_registered():
    """命令挂在组里，且权限检查挂在 Command 对象上。"""
    cog = ContactMaintainerCog(MockBot())
    cmd = cog.contact_group.get_command("联系维护者")
    assert cmd is not None, "命令没注册上"
    assert cmd.checks, "命令上没有权限检查（@is_admin() 应装饰 Command 对象）"
    print(f"✅ 命令已注册: {cog.contact_group.name} 联系维护者; checks={len(cmd.checks)}")


def test_modal_construction():
    """modal 标题 + 一个 TextInput，长度限制符合设计。"""
    cog = ContactMaintainerCog(MockBot())
    modal = ContactMaintainerModal(cog)
    assert modal.title == "联系维护者", modal.title
    assert len(modal.children) == 1, f"expected 1 input, got {len(modal.children)}"
    text_input = modal.children[0]
    assert text_input.min_length == 5, text_input.min_length
    assert text_input.max_length == 800, text_input.max_length
    print(f"✅ modal OK: title={modal.title!r}, inputs={len(modal.children)}")


def test_quota_rollover():
    """额度按 UTC+8 自然日算，跨天自动归零。"""
    cog = ContactMaintainerCog(MockBot())
    today = datetime.now(_UTC8).strftime("%Y-%m-%d")

    cog._daily_usage = {"date": "1999-01-01", "count": 5}
    assert cog._quota_used_today() == 0, cog._daily_usage
    assert cog._daily_usage["count"] == 0, cog._daily_usage

    cog._daily_usage = {"date": today, "count": 3}
    assert cog._quota_used_today() == 3, cog._daily_usage
    print("✅ 额度跨天归零 OK")


def test_quota_only_counts_on_success():
    """只有真发出去了才计数；发送失败不占额度。"""
    cog = ContactMaintainerCog(MockBot())
    sent: list[str] = []

    async def fake_send(content: str) -> None:
        sent.append(content)

    cog._send_qq_message = fake_send

    app_id, app_secret, owner_openid = _fake_qq_config()
    with app_id, app_secret, owner_openid:
        inter = MockInteraction()
        asyncio.run(cog._handle_submit(inter, "服务器出事了"))
        assert cog._daily_usage["count"] == 1, cog._daily_usage
        assert len(sent) == 1 and "服务器出事了" in sent[0]
        # 线上教训（10015 Unknown Webhook）：modal 提交后必须先 defer 才能 followup
        assert inter.response.deferred, "提交后必须先 defer 再走后续网络调用"
        assert inter.response.defer_kwargs.get("ephemeral") is True

        async def boom(content: str) -> None:
            raise RuntimeError("模拟发送失败")

        cog._send_qq_message = boom
        inter2 = MockInteraction()
        asyncio.run(cog._handle_submit(inter2, "又出事了"))
        assert cog._daily_usage["count"] == 1, "发送失败不该计数"

    print("✅ 发送成功才计数 OK")


def test_quota_exhausted_blocks_submit():
    """额度用完时直接回执，不发 QQ。"""
    cog = ContactMaintainerCog(MockBot())
    today = datetime.now(_UTC8).strftime("%Y-%m-%d")
    cog._daily_usage = {"date": today, "count": DAILY_LIMIT}

    called = []

    async def fake_send(content: str) -> None:
        called.append(content)

    cog._send_qq_message = fake_send
    inter = MockInteraction()
    asyncio.run(cog._handle_submit(inter, "额度没了还想发"))
    assert not called, "额度用完时不该真的发送"
    assert inter.followup.sent, "应该给用户回执"
    print("✅ 额度用完不发送 OK")


def test_qq_message_format():
    """QQ 消息文本格式固定。"""
    cog = ContactMaintainerCog(MockBot())
    inter = MockInteraction()
    text = cog._build_qq_text(inter, "问题内容")

    lines = text.splitlines()
    assert lines[0] == "[odysseia_ticket_bot] 管理组联系请求", lines[0]
    assert "来自: 测试用户 (ID: 1)" in text, text
    assert "服务器: 测试服务器 (ID: 100)" in text, text
    assert "(UTC+8)" in text, text
    assert text.endswith("问题内容"), text
    # 时间戳格式：YYYY-MM-DD HH:MM:SS
    stamp = lines[3].removeprefix("时间: ").removesuffix(" (UTC+8)")
    datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    print(f"✅ QQ 消息格式 OK:\n{text}")


def test_missing_config_is_reported():
    """配置缺失会被识别出来（fail-loud，不静默）。"""
    cog = ContactMaintainerCog(MockBot())
    with mock.patch.object(config, "QQBOT_APP_ID", None), \
         mock.patch.object(config, "QQBOT_APP_SECRET", None), \
         mock.patch.object(config, "QQBOT_OWNER_OPENID", None):
        missing = cog._missing_qq_config()
    assert set(missing) == {"QQBot_AppID", "QQBot_AppSecret", "QQBot_OwnerOpenID"}, missing
    print(f"✅ 缺失配置能被识别: {missing}")


# ==================================================================
# QQ 平台调用：假 session 顶替网络，检查 URL / header / body 的形状
# ==================================================================

class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class FakeSession:
    """记录每次 post 的 URL / kwargs，按 URL 返回预设响应。"""

    calls: list[tuple[str, dict]] = []
    responses: dict[str, FakeResponse] = {}

    def __init__(self, *args, **kwargs):
        pass

    def post(self, url, **kwargs):
        FakeSession.calls.append((url, kwargs))
        for prefix, resp in FakeSession.responses.items():
            if url.startswith(prefix):
                return resp
        raise AssertionError(f"没给这个 URL 预设响应: {url}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def test_qq_api_request_shape():
    """取 token / 发消息的 URL、header、body 形状都要对。"""
    cog = ContactMaintainerCog(MockBot())
    FakeSession.calls = []
    FakeSession.responses = {
        "https://api.bot.qq.com/": FakeResponse(200, {"access_token": "TKN", "expires_in": 7200}),
        "https://api.sgroup.qq.com/": FakeResponse(200, {"id": "MSG", "timestamp": "2026-11-11"}),
    }

    app_id, app_secret, owner_openid = _fake_qq_config()
    with app_id, app_secret, owner_openid, \
         mock.patch("core.contact_maintainer_cog.aiohttp.ClientSession", FakeSession):
        asyncio.run(cog._send_qq_message("测试内容"))

    token_url, token_kwargs = FakeSession.calls[0]
    msg_url, msg_kwargs = FakeSession.calls[1]

    # ① 取 token：域名是 api.bot.qq.com，参数名是 clientSecret
    assert token_url == "https://api.bot.qq.com/app/getAppAccessToken", token_url
    assert token_kwargs["json"] == {"appId": "test-app-id", "clientSecret": "test-app-secret"}, \
        token_kwargs["json"]

    # ② 发消息：域名是 api.sgroup.qq.com，header 是 QQBot + 空格 + token
    assert msg_url == "https://api.sgroup.qq.com/v2/users/test-openid/messages", msg_url
    assert msg_kwargs["headers"]["Authorization"] == "QQBot TKN", msg_kwargs["headers"]
    assert msg_kwargs["json"] == {"msg_type": 0, "content": "测试内容"}, msg_kwargs["json"]
    print("✅ QQ API 请求形状 OK")


def test_qq_api_business_error_is_failure():
    """HTTP 200 但 body 带 code → 判失败（跟取 token 接口一个坑）。"""
    from core.contact_maintainer_cog import QQApiError

    cog = ContactMaintainerCog(MockBot())
    FakeSession.calls = []
    FakeSession.responses = {
        "https://api.bot.qq.com/": FakeResponse(200, {"access_token": "TKN", "expires_in": 7200}),
        "https://api.sgroup.qq.com/": FakeResponse(200, {"code": 40054013, "message": "用户拒收"}),
    }

    app_id, app_secret, owner_openid = _fake_qq_config()
    with app_id, app_secret, owner_openid, \
         mock.patch("core.contact_maintainer_cog.aiohttp.ClientSession", FakeSession):
        try:
            asyncio.run(cog._send_qq_message("测试内容"))
        except QQApiError as exc:
            assert exc.code == 40054013, exc.code
            assert exc.message == "用户拒收", exc.message
            print(f"✅ HTTP 200 + code 判失败 OK: code={exc.code}")
        else:
            raise AssertionError("应当抛 QQApiError")


if __name__ == "__main__":
    test_cog_init()
    test_command_registered()
    test_modal_construction()
    test_quota_rollover()
    test_quota_only_counts_on_success()
    test_quota_exhausted_blocks_submit()
    test_qq_message_format()
    test_missing_config_is_reported()
    test_qq_api_request_shape()
    test_qq_api_business_error_is_failure()
    print("\n🎉 All contact maintainer cog tests passed.")
