"""第二轮补充:游客上限边界、取消请求的迟到响应、usage 坏行压实。

这些是复审第二轮新功能时发现的真实边界缺陷,与 test_hardening.py 同一性质:
只测「用户会遇到的边界」,不重复功能测试。
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import store
import usage


def _auth_app() -> TestClient:
    app = Starlette(routes=[
        Route("/api/auth/login", auth.login, methods=["POST"]),
        Route("/api/auth/register", auth.register, methods=["POST"]),
    ])
    return TestClient(app, raise_server_exceptions=False)


def _guest(client: TestClient):
    auth._auth_limiter.reset()
    return client.post("/api/auth/login", json={"method": "wechat", "nickname": "g"})


def _seed_guest(uid: str, created: str = "2026-01-01T00:00:00") -> None:
    store.create_user({
        "uid": uid,
        "phone": None,
        "password_hash": None,
        "authMethod": "wechat",
        "nickname": "guest",
        "avatar": "preset:sum",
        "createdAt": created,
    })


# ---------- 游客上限:满额时必须能腾位,而不是变成永久硬墙 ----------

def test_guest_cap_frees_slot_at_capacity(temp_store, monkeypatch):
    """刚好满额 + 有一个 guest 的 token 已失效 → 新游客应能登录。

    旧实现 prune_guests(max) 在 excess==0 时什么都不做,满额后即使 token
    全过期也永远 429(500 个游客攒满 = 微信/QQ 登录永久失效)。
    """
    monkeypatch.setenv("MG_GUEST_MAX", "2")
    client = _auth_app()
    assert _guest(client).status_code == 200
    assert _guest(client).status_code == 200
    assert store.guest_count() == 2

    # 让最早那个游客没有有效 token(模拟隔天 token 过期)
    stale_uid = next(uid for uid in store._users if uid.startswith(store.GUEST_UID_PREFIX))
    for token in [t for t, e in store._tokens.items()
                  if store._token_uid(e) == stale_uid]:
        store._tokens.pop(token, None)

    assert _guest(client).status_code == 200, "满额时没有为新游客腾出位置"
    assert store.guest_count() == 2, "腾位后游客数应仍为上限"
    assert stale_uid not in store._users, "无 token 的最旧游客应被清掉"


def test_guest_cap_keeps_guests_with_live_tokens(temp_store, monkeypatch):
    """所有游客 token 都有效时,不应为了腾位删掉活跃账号;应直接 429。"""
    monkeypatch.setenv("MG_GUEST_MAX", "2")
    client = _auth_app()
    assert _guest(client).status_code == 200
    assert _guest(client).status_code == 200
    users_before = dict(store._users)
    assert _guest(client).status_code == 429
    assert store._users == users_before, "活跃游客被误删"


def test_guest_max_zero_rejects_without_side_effects(temp_store, monkeypatch):
    """MG_GUEST_MAX=0 = 禁止游客登录:必须拒绝,且不能顺手删现存游客。"""
    monkeypatch.setenv("MG_GUEST_MAX", "0")
    _seed_guest("guest-wechat-aaa")
    _seed_guest("guest-wechat-bbb", created="2026-01-02T00:00:00")
    users_before = dict(store._users)
    tokens_before = dict(store._tokens)

    client = _auth_app()
    assert _guest(client).status_code == 429
    assert store._users == users_before, "被拒绝的登录仍删除了游客账号"
    assert store._tokens == tokens_before, "被拒绝的登录仍改动了 tokens"


def test_guest_cap_does_not_touch_phone_accounts(temp_store, monkeypatch):
    monkeypatch.setenv("MG_GUEST_MAX", "1")
    client = _auth_app()
    auth._auth_limiter.reset()
    assert client.post("/api/auth/register",
                       json={"phone": "13900000222", "password": "secret123"}).status_code == 200
    assert _guest(client).status_code == 200
    assert _guest(client).status_code == 429          # 满额
    assert any(not uid.startswith(store.GUEST_UID_PREFIX) for uid in store._users), \
        "手机号账号被游客清理波及"


# ---------- 取消请求:迟到返回的响应句柄必须关闭 ----------

def test_late_response_is_closed_after_cancel(monkeypatch):
    """取消发生在 urlopen 返回之前时,外层已错过这次响应;线程侧必须自己关掉。"""
    import rag.research.sources as sources

    class FakeResp:
        closed = False

        def read(self, n=-1):
            return b"data"

        def close(self):
            FakeResp.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    def slow_urlopen(*args, **kwargs):
        time.sleep(0.3)          # urlopen 比取消更晚返回
        return FakeResp()

    monkeypatch.setattr(sources.urllib.request, "urlopen", slow_urlopen)

    async def scenario():
        task = asyncio.create_task(sources._http_get_async("https://example.invalid", 5))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.5)  # 等线程把 urlopen 做完
        return FakeResp.closed

    assert asyncio.run(scenario()), "迟到的响应句柄没有关闭(连接要等 GC 才回收)"
    assert not sources._inflight
    assert not sources._cancel_flags


def test_cancel_closes_inflight_response(monkeypatch):
    """常规路径:取消时 close() 在途响应,让线程里阻塞的 read() 尽快退出。"""
    import threading

    import rag.research.sources as sources

    closed = threading.Event()

    class BlockingResp:
        def read(self, n=-1):
            closed.wait(timeout=5)
            raise ValueError("I/O operation on closed file")

        def close(self):
            closed.set()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.close()
            return False

    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *a, **k: BlockingResp())

    async def scenario():
        task = asyncio.create_task(sources._http_get_async("https://example.invalid", 15))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return closed.is_set()

    assert asyncio.run(scenario()), "取消后没有关闭在途响应"
    assert not sources._inflight
    assert not sources._cancel_flags


# ---------- usage:进程重启后坏行会被压实清掉,旧 JSON 能迁移 ----------

def test_usage_compacts_corrupt_line_after_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    usage.reset_for_tests()

    usage.record(user="u", phone="", cmd="c", prompt_len=1, reply_len=2,
                 role="main", research=False, ts=time.time())
    with usage.PATH.open("a", encoding="utf-8") as fh:
        fh.write("{oops not json\n")   # 模拟写一半/外部手改

    usage.reset_for_tests()            # 模拟进程重启(下次读取时才发现坏行)
    usage.record(user="u", phone="", cmd="c", prompt_len=1, reply_len=2,
                 role="main", research=False, ts=time.time())

    text = usage.PATH.read_text(encoding="utf-8")
    assert "{oops" not in text, "坏行没有被压实清掉"
    for line in text.splitlines():
        if line.strip():
            json.loads(line)


def test_usage_migrates_legacy_json(tmp_path, monkeypatch):
    legacy = tmp_path / "usage.json"
    legacy.write_text(json.dumps([
        {"ts": 1.0, "user": "a", "phone": "", "cmd": "x", "prompt_len": 1,
         "reply_len": 10, "role": "main", "research": False},
        {"ts": 2.0, "user": "b", "phone": "", "cmd": "y", "prompt_len": 1,
         "reply_len": 5, "role": "deep", "research": True},
    ]), encoding="utf-8")

    monkeypatch.setattr(usage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", legacy)
    usage.reset_for_tests()

    before = usage.summary()
    assert before["calls"] == 2 and before["totalChars"] == 15, "旧数据没被读出来"

    usage.record(user="c", phone="", cmd="z", prompt_len=1, reply_len=3,
                 role="main", research=False, ts=time.time())

    lines = [ln for ln in usage.PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3, "迁移后 jsonl 行数 %d != 3" % len(lines)
    assert legacy.exists(), "旧 usage.json 应保留作备份"
    assert usage.summary()["calls"] == 3
