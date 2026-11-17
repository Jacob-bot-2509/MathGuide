"""auth.py:注册/登录/登出、演示模式、PBKDF2 升级、管理员守卫与限流。"""
from __future__ import annotations

import hashlib
import time

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import http_utils
import research_corpus
import session_cache
import store
import usage
import exercise_history
from rate_limit import SlidingWindowLimiter

PHONE = "13800138000"
PASSWORD = "secret123"


@pytest.fixture()
def client(temp_store, temp_usage, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/auth/login", auth.login, methods=["POST"]),
        Route("/api/auth/session", auth.session),
        Route("/api/auth/logout", auth.logout, methods=["POST"]),
        Route("/api/account/export", auth.export_account, methods=["POST"]),
        Route("/api/account/delete", auth.delete_account, methods=["POST"]),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient, phone: str = PHONE, password: str = PASSWORD) -> dict:
    res = c.post("/api/auth/register", json={"phone": phone, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def _legacy_user(uid: str = "u-1", phone: str = PHONE, password: str = PASSWORD) -> dict:
    salt = "0123456789abcdef"
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return {
        "uid": uid,
        "phone": phone,
        "password_hash": (salt, digest),
        "authMethod": "phone-pass",
        "nickname": "legacy",
        "avatar": "preset:sum",
        "createdAt": "2026-01-01T00:00:00",
    }


def test_register_login_logout(client):
    body = _register(client)
    token = body["token"]
    account_key = body["user"]["accountKey"]
    assert body["user"]["phone"] == PHONE
    assert "uid" not in body["user"] and "password_hash" not in body["user"]
    assert account_key and len(account_key) == 16
    assert account_key != f"u-{PHONE}"

    res = client.post("/api/auth/login", json={"method": "password", "phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"
    assert res.json()["user"]["nickname"].startswith("MG用户_")
    assert store.find_user_by_phone(PHONE)[1].get("lastActiveAt")
    assert res.json()["user"]["accountKey"] == account_key

    res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert store.resolve_token(token) is None


def test_register_sets_shared_cookie_and_session_restores(client):
    """跨子域共享登录:注册即下发 HttpOnly Cookie,session 端点免 Bearer 恢复登录。"""
    res = client.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200
    cookie = res.headers.get("set-cookie", "")
    assert auth.COOKIE_NAME in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    # 方案 B:Cookie 记 30 天(真正有效期由 token 的滑动续期决定)
    assert f"max-age={auth.COOKIE_MAX_AGE}" in cookie.lower()
    assert auth.COOKIE_MAX_AGE == 30 * 24 * 3600

    restored = client.get("/api/auth/session")
    assert restored.status_code == 200
    assert restored.json()["user"]["phone"] == PHONE

    # 登出只靠 Cookie 也必须生效:共享凭据在服务端被吊销
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/session").status_code == 401


def test_expired_token_closes_session(client, monkeypatch):
    """token 过期且没有更新的 Cookie 时必须 401(不能靠旧凭据继续登录)。"""
    now = [1_000_000.0]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    assert client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).status_code == 200
    assert client.get("/api/auth/session").status_code == 200

    now[0] += store.TOKEN_TTL_HOURS * 3600 + 1
    assert client.get("/api/auth/session").status_code == 401


def test_session_does_not_rotate_fresh_token(client):
    """新签发的 token 不轮换:否则每次启动都写库,且旧标签页会莫名换凭据。"""
    body = client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).json()
    token = body["token"]

    res = client.get("/api/auth/session", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "token" not in res.json()
    # Cookie 里仍是同一个 token,且被刷新了有效期
    assert f"{auth.COOKIE_NAME}={token}" in res.headers.get("set-cookie", "")


def test_session_rotates_token_near_expiry(client, monkeypatch):
    """剩余寿命不足 20% 时轮换:新 token 可用,旧 token 不吊销(多标签页不踢人)。"""
    body = client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).json()
    old = body["token"]

    now = [time.time()]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    # 24h 的 80% = 19.2h;推到 19.5h 即触发轮换
    now[0] += store.TOKEN_TTL_HOURS * 3600 * auth.RENEW_AFTER_RATIO + 0.5 * 3600

    res = client.get("/api/auth/session", headers={"Authorization": f"Bearer {old}"})
    assert res.status_code == 200
    new = res.json()["token"]
    assert new and new != old
    assert f"{auth.COOKIE_NAME}={new}" in res.headers.get("set-cookie", "")

    assert store.resolve_token(new) is not None
    # 不吊销:另一个标签页/长连接可能还拿着旧 token,它靠自己 24h 到期退出
    assert store.resolve_token(old) is not None


def test_renewal_is_throttled(client, monkeypatch, temp_store):
    """客户端不写回新 token 时,不能在每次 session() 都签发一个(否则 token 表被刷大)。"""
    body = client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).json()
    old = body["token"]
    uid = temp_store.find_user_by_phone(PHONE)[0]

    now = [time.time()]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    now[0] += store.TOKEN_TTL_HOURS * 3600 * auth.RENEW_AFTER_RATIO + 0.5 * 3600

    headers = {"Authorization": f"Bearer {old}"}
    first = client.get("/api/auth/session", headers=headers)
    second = client.get("/api/auth/session", headers=headers)
    assert "token" in first.json()
    assert "token" not in second.json(), "5 分钟内不应重复轮换"

    owned = [k for k, v in temp_store.tokens_snapshot().items() if v["uid"] == uid]
    assert len(owned) == 2, f"注册 1 条 + 轮换 1 条,实际 {len(owned)}"


def test_stale_bearer_falls_back_to_cookie(client, temp_store):
    """旧 Bearer 失效但 Cookie 是新的(别的标签页已轮换)时,仍应判定为已登录。"""
    body = client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).json()
    stale = body["token"]
    uid = temp_store.find_user_by_phone(PHONE)[0]
    fresh = temp_store.issue_token(uid)
    temp_store.revoke_token(stale)  # 模拟旧 token 已退役
    client.cookies.set(auth.COOKIE_NAME, fresh)

    res = client.get("/api/auth/session", headers={"Authorization": f"Bearer {stale}"})
    assert res.status_code == 200
    assert res.json()["user"]["phone"] == PHONE


def test_logout_revokes_bearer_and_cookie_tokens(client, temp_store):
    """登出要把 Bearer 与 Cookie 两个凭据都清掉,否则"已登出"的 Cookie 还能用。"""
    body = client.post(
        "/api/auth/register", json={"phone": PHONE, "password": PASSWORD}
    ).json()
    header_token = body["token"]
    uid = temp_store.find_user_by_phone(PHONE)[0]
    cookie_token = temp_store.issue_token(uid)
    client.cookies.set(auth.COOKIE_NAME, cookie_token)

    res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {header_token}"})
    assert res.status_code == 200
    assert temp_store.resolve_token(header_token) is None
    assert temp_store.resolve_token(cookie_token) is None


def test_login_errors(client):
    _register(client)
    assert client.post("/api/auth/login", json={
        "method": "password", "phone": PHONE, "password": "wrong123"}).status_code == 401
    assert client.post("/api/auth/login", json={
        "method": "password", "phone": "13900139000", "password": PASSWORD}).status_code == 404
    assert client.post("/api/auth/register", json={
        "phone": PHONE, "password": PASSWORD}).status_code == 409


def test_register_validation(client):
    assert client.post("/api/auth/register", json={"phone": "123", "password": PASSWORD}).status_code == 400
    assert client.post("/api/auth/register", json={"phone": PHONE, "password": "123"}).status_code == 400
    assert client.post("/api/auth/register", json={
        "phone": PHONE, "password": "x" * (auth.PASSWORD_MAX + 1)}).status_code == 400
    assert client.post("/api/auth/register", json={"phone": PHONE, "password": 123456}).status_code == 400


def test_malformed_body_is_400(client):
    assert client.post("/api/auth/login", content=b"{not json",
                       headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/api/auth/login", json=[]).status_code == 400


def test_body_size_limit_is_413(client, monkeypatch):
    monkeypatch.setattr(http_utils, "MAX_BODY_BYTES", 32)
    res = client.post("/api/auth/register", json={"phone": PHONE, "password": "x" * 100})
    assert res.status_code == 413


def test_demo_code_login_and_guest(client):
    res = client.post("/api/auth/login", json={
        "method": "code", "phone": "13900139000", "code": auth.DEMO_CODE})
    assert res.status_code == 200
    assert res.json()["user"]["authMethod"] == "phone-code"

    res = client.post("/api/auth/login", json={
        "method": "code", "phone": "13900139000", "code": "000000"})
    assert res.status_code == 401

    res = client.post("/api/auth/login", json={
        "method": "wechat", "nickname": "x" * 100, "avatar": "preset:int"})
    assert res.status_code == 200
    assert len(res.json()["user"]["nickname"]) == auth.NICKNAME_MAX


def test_demo_mode_off_rejects_fixed_code_guest_and_open_register(client, temp_store, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    monkeypatch.delenv("MG_INVITE_CODES", raising=False)
    assert client.post("/api/auth/login", json={
        "method": "code", "phone": "13900139000", "code": auth.DEMO_CODE}).status_code == 400
    assert client.post("/api/auth/login", json={"method": "qq"}).status_code == 400
    assert client.post("/api/auth/register", json={
        "phone": PHONE, "password": PASSWORD}).status_code == 400

    # 已有账号的密码登录不受影响(账号由真实验证流程/管理端创建)
    temp_store.create_user(_legacy_user())
    assert client.post("/api/auth/login", json={
        "method": "password", "phone": PHONE, "password": PASSWORD}).status_code == 200


def test_legacy_password_is_upgraded_on_login(client, temp_store):
    temp_store.create_user(_legacy_user())
    res = client.post("/api/auth/login", json={
        "method": "password", "phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200
    spec = temp_store.find_user_by_phone(PHONE)[1]["password_hash"][0]
    assert spec.startswith(store.PBKDF2_PREFIX + "$")
    # 升级后的哈希仍能登录
    assert client.post("/api/auth/login", json={
        "method": "password", "phone": PHONE, "password": PASSWORD}).status_code == 200


def test_logout_clears_session_cache(client):
    body = _register(client)
    uid = store.find_user_by_phone(PHONE)[0]
    session_cache.cache_textbook(uid, 1, "教材" * 50)
    assert session_cache.get_textbook(uid, 1)

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {body['token']}"})
    assert session_cache.get_textbook(uid, 1) == ""


def test_auth_rate_limit(client, monkeypatch):
    monkeypatch.setattr(auth, "_auth_limiter", SlidingWindowLimiter(2, 60))
    for i in range(2):
        _register(client, phone=f"1380013800{i}")
    res = client.post("/api/auth/register", json={
        "phone": "13800138002", "password": PASSWORD})
    assert res.status_code == 429


def test_guest_limit_rejects_when_all_active(client, monkeypatch):
    monkeypatch.setenv("MG_GUEST_MAX", "1")
    assert client.post("/api/auth/login", json={"method": "wechat"}).status_code == 200
    # 第一个游客仍持有有效 token,不能清理;第二个应被上限拒绝
    assert client.post("/api/auth/login", json={"method": "qq"}).status_code == 429


def test_admin_guard(temp_store, monkeypatch):
    async def admin_only(request):
        auth.require_admin(request)
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/admin", admin_only)])
    client = TestClient(app, raise_server_exceptions=False)
    uid = temp_store.create_user(_legacy_user())
    token = temp_store.issue_token(uid)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/admin").status_code == 401
    monkeypatch.delenv("MG_ADMIN_PHONES", raising=False)
    monkeypatch.delenv("MG_ADMIN_UIDS", raising=False)
    assert client.get("/admin", headers=headers).status_code == 403

    monkeypatch.setenv("MG_ADMIN_PHONES", f"13900139000,{PHONE}")
    assert client.get("/admin", headers=headers).status_code == 200

    monkeypatch.setenv("MG_ADMIN_PHONES", "")
    monkeypatch.setenv("MG_ADMIN_UIDS", uid)
    assert client.get("/admin", headers=headers).status_code == 200


def test_export_account_omits_secrets_and_scopes_usage(client, temp_usage):
    body = _register(client)
    uid = store.find_user_by_phone(PHONE)[0]
    temp_usage.record(uid=uid, cmd="提问", prompt_len=10, reply_len=5,
                      role="main", research=False, ts=1.0)
    temp_usage.record(uid="someone-else", cmd="提问", prompt_len=10, reply_len=9,
                      role="main", research=False, ts=2.0)
    doc_id = exercise_history.create_draft(
        uid, {"title": "t", "sections": [], "exercise_meta": {"count": 1}},
        {}, 1, [], "zh", "questions", "t")
    exercise_history.confirm(uid, doc_id)

    res = client.post("/api/account/export", json={},
                      headers={"Authorization": f"Bearer {body['token']}"})
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"
    data = res.json()
    account = data["account"]
    assert account["phone"] == PHONE
    assert account["accountKey"] == body["user"]["accountKey"]
    assert "uid" not in account and "password_hash" not in account and "token" not in account
    assert len(data["usage"]) == 1
    assert [item["id"] for item in data["exerciseDocuments"]] == [doc_id]
    assert "sections" in data["exerciseDocuments"][0]["document"]
    entry = data["usage"][0]
    assert entry["reply_len"] == 5
    assert "phone" not in entry and "user" not in entry and "uid" not in entry


def test_delete_account_requires_password_and_cascades(client, temp_store, temp_usage):
    body = _register(client)
    uid = store.find_user_by_phone(PHONE)[0]
    token = body["token"]
    headers = {"Authorization": f"Bearer {token}"}
    temp_usage.record(uid=uid, cmd="提问", prompt_len=1, reply_len=2,
                      role="main", research=False, ts=1.0)
    temp_usage.record(uid="keep-me", cmd="提问", prompt_len=1, reply_len=3,
                      role="main", research=False, ts=2.0)

    assert client.post("/api/account/delete", json={"password": "wrong123"},
                       headers=headers).status_code == 401
    assert store.find_user_by_phone(PHONE) is not None

    doc_id = exercise_history.create_draft(
        uid, {"title": "t", "sections": []}, {}, 1, [], "zh", "questions", "t")
    exercise_history.confirm(uid, doc_id)

    res = client.post("/api/account/delete", json={"password": PASSWORD}, headers=headers)
    assert res.status_code == 200
    assert exercise_history.list_documents(uid) == []
    assert res.headers.get("cache-control") == "no-store"
    assert store.find_user_by_phone(PHONE) is None
    assert store.resolve_token(token) is None
    assert temp_usage.summary()["calls"] == 1
    assert temp_usage.summary()["users"][0]["uid"] == "keep-me"

    # 注销后旧 token 立即失效,不能继续导出
    assert client.post("/api/account/export", json={}, headers=headers).status_code == 401


def test_delete_account_retries_after_corpus_cleanup_failure(client, monkeypatch):
    body = _register(client)
    uid = store.find_user_by_phone(PHONE)[0]
    headers = {"Authorization": f"Bearer {body['token']}"}
    path = research_corpus.DATA_DIR / uid
    path.mkdir(parents=True)
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise PermissionError("locked")
        patch.setattr(research_corpus.shutil, "rmtree", fail)
        assert client.post("/api/account/delete", json={"password": PASSWORD}, headers=headers).status_code == 500
    assert store.find_user_by_phone(PHONE) is not None
    assert client.post("/api/account/delete", json={"password": PASSWORD}, headers=headers).status_code == 200
    assert store.find_user_by_phone(PHONE) is None
    assert not path.exists()


def test_delete_guest_requires_explicit_confirmation(client):
    res = client.post("/api/auth/login", json={"method": "wechat"})
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.post("/api/account/delete", json={}, headers=headers).status_code == 400
    assert client.post("/api/account/delete", json={"confirm": "DELETE"},
                       headers=headers).status_code == 200
    assert store.resolve_token(token) is None


def test_invite_code_registration_when_demo_off(client, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    monkeypatch.setenv("MG_INVITE_CODES", "eval-alpha,eval-beta")

    assert client.post("/api/auth/register", json={
        "phone": "13900139001", "password": PASSWORD}).status_code == 403
    assert client.post("/api/auth/register", json={
        "phone": "13900139001", "password": PASSWORD,
        "invite": "wrong"}).status_code == 403

    res = client.post("/api/auth/register", json={
        "phone": "13900139001", "password": PASSWORD, "invite": " eval-beta "})
    assert res.status_code == 200
    assert res.json()["user"]["phone"] == "13900139001"

    # 邀请码只影响注册;验证码/游客登录仍然关闭
    assert client.post("/api/auth/login", json={
        "method": "code", "phone": "13900139001", "code": auth.DEMO_CODE}).status_code == 400
    assert client.post("/api/auth/login", json={"method": "wechat"}).status_code == 400


def test_configure_auth_rate_limit_from_env(monkeypatch):
    monkeypatch.setenv("MG_AUTH_RATE_MAX", "25")
    monkeypatch.setenv("MG_AUTH_RATE_WINDOW", "120")
    auth.configure_rate_limit()
    assert auth._auth_limiter.max_hits == 25
    assert auth._auth_limiter.window == 120.0

    # 非法/过小值回退默认,不能把限流关掉
    monkeypatch.setenv("MG_AUTH_RATE_MAX", "0")
    monkeypatch.setenv("MG_AUTH_RATE_WINDOW", "bad")
    auth.configure_rate_limit()
    assert auth._auth_limiter.max_hits == 10
    assert auth._auth_limiter.window == 60.0
