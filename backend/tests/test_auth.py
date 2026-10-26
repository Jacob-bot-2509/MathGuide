"""auth.py:注册/登录/登出、演示模式、PBKDF2 升级、管理员守卫与限流。"""
from __future__ import annotations

import hashlib

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import http_utils
import session_cache
import store
from rate_limit import SlidingWindowLimiter

PHONE = "13800138000"
PASSWORD = "secret123"


@pytest.fixture()
def client(temp_store, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/auth/login", auth.login, methods=["POST"]),
        Route("/api/auth/logout", auth.logout, methods=["POST"]),
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
    assert res.json()["user"]["nickname"].startswith("MG用户_")
    assert res.json()["user"]["accountKey"] == account_key

    res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert store.resolve_token(token) is None


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
    spec = temp_store._users["u-1"]["password_hash"][0]
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
