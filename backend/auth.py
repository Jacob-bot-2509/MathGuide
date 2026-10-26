"""
认证路由:注册 / 登录 / 登出。

契约(与 frontend/src/api/types.ts 对齐):
- POST /api/auth/register {phone, password}
    200 {token, user} | 409 {error: "exists"}
- POST /api/auth/login
    {method: "password", phone, password}
        200 {token, user} | 404 {error: "notfound"} | 401 {error: "wrong"}
    {method: "code", phone, code}
        code 需为演示码 123456;手机号未注册则自动创建账户
    {method: "wechat" | "qq", nickname?, avatar?}
        访客式登录(演示:模拟与设备账号授权交接),创建 guest 用户
    统一返回 200 {token, user}
- POST /api/auth/logout  (需 Bearer token) → 200 {ok: true}

演示模式:MG_DEMO_MODE 默认 1,允许固定验证码、访客登录与开放注册;设为 0/off 后
这些演示通道与 /register 直接拒绝,真实部署必须关闭。认证接口按客户端 IP 限流。

user DTO: {nickname, avatar, authMethod: "phone-pass"|"phone-code"|"wechat"|"qq", phone?}
"""
import hashlib
import os
import secrets
from datetime import datetime

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import session_cache
import store
from http_utils import read_json_object
from rate_limit import SlidingWindowLimiter

DEMO_CODE = "123456"

DEFAULT_AVATAR = "preset:sum"  # 与前端 AVATAR_PRESETS[0] 对应
NICKNAME_MAX = 40
AVATAR_MAX = 500
PASSWORD_MAX = 1024  # 只防超长输入刷内存/CPU;旧账号可能设置过更长口令,不要误锁
GUEST_MAX_DEFAULT = 500

# 认证接口限流:登录/注册共用,按客户端 IP;演示期也不会误伤正常操作
_AUTH_RATE_MAX = 10
_AUTH_RATE_WINDOW = 60.0
_auth_limiter = SlidingWindowLimiter(_AUTH_RATE_MAX, _AUTH_RATE_WINDOW)


def _demo_mode() -> bool:
    """演示通道开关:默认开启(本机演示);显式设 0/false/off/no 关闭。"""
    return os.getenv("MG_DEMO_MODE", "1").strip().lower() not in ("0", "false", "off", "no")


def _guest_max() -> int:
    """游客账号上限;0 表示禁止游客登录。坏值回退默认。"""
    raw = os.getenv("MG_GUEST_MAX", str(GUEST_MAX_DEFAULT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return GUEST_MAX_DEFAULT


def _client_key(request: Request) -> str:
    client = request.client
    return client.host if client and client.host else "unknown"


def _auth_rate_check(request: Request) -> None:
    if not _auth_limiter.allow(_client_key(request)):
        raise HTTPException(429, "rate limited")


def is_admin(rec: dict) -> bool:
    """管理员判定:手机号或 uid 在环境变量白名单内(逗号分隔)。"""
    phones = {p.strip() for p in os.getenv("MG_ADMIN_PHONES", "").split(",") if p.strip()}
    uids = {u.strip() for u in os.getenv("MG_ADMIN_UIDS", "").split(",") if u.strip()}
    phone = str(rec.get("phone") or "")
    uid = str(rec.get("uid") or "")
    return bool((phone and phone in phones) or (uid and uid in uids))


def require_admin(request: Request) -> dict:
    """管理员接口守卫:未登录 401,非管理员 403。"""
    rec = require_auth(request)
    if not is_admin(rec):
        raise HTTPException(403, "forbidden")
    return rec


def user_dto(rec: dict) -> dict:
    """user DTO:剔除 uid / password_hash 等内部字段。

    accountKey 是 uid 的不可逆哈希,仅用于前端判断「本机学习数据属于哪个账号」;
    换账号登录时据此清理上一位用户的数据,同时不暴露内部 uid。
    """
    dto = {
        "nickname": rec["nickname"],
        "avatar": rec["avatar"],
        "authMethod": rec["authMethod"],
        "accountKey": hashlib.sha256(str(rec.get("uid") or "").encode("utf-8")).hexdigest()[:16],
    }
    if rec.get("phone"):
        dto["phone"] = rec["phone"]
    return dto


def _new_user(uid: str, phone: str | None, method: str, password: tuple[str, str] | None,
              nickname: str | None, avatar: str | None) -> dict:
    return {
        "uid": uid,
        "phone": phone,
        "password_hash": password,
        "authMethod": method,
        "nickname": nickname or f"MG用户_{uid[-4:]}",
        "avatar": avatar or DEFAULT_AVATAR,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }


def _password_matches(password: str, stored: object) -> tuple[bool, bool]:
    """校验密码,返回 (是否匹配, 是否为旧格式)。

    旧格式(单轮 sha256)在登录成功后由调用方升级为 PBKDF2;
    比较用 secrets.compare_digest,避免逐字节计时差异。
    """
    if not isinstance(stored, (list, tuple)) or len(stored) != 2:
        return False, False
    salt_spec, digest = stored
    if not isinstance(salt_spec, str) or not isinstance(digest, str):
        return False, False
    expected = store.hash_password(password, salt_spec)[1]
    return secrets.compare_digest(expected, digest), store.is_legacy_hash(salt_spec)


def _bearer_token(request: Request) -> str:
    """从 Authorization 头提取 Bearer token(require_auth 与 logout 共用,解析规则不重复)"""
    header = request.headers.get("authorization", "")
    return header[7:] if header.lower().startswith("bearer ") else ""


def require_auth(request: Request) -> dict:
    """取当前登录用户;未认证抛 401(Starlette 默认转 JSON {"detail": ...})"""
    token = _bearer_token(request)
    rec = store.resolve_token(token) if token else None
    if not rec:
        raise HTTPException(401, "unauthorized")
    return rec


def _valid_phone(phone: str) -> bool:
    return len(phone) == 11 and phone.isdigit()


async def register(request: Request) -> JSONResponse:
    _auth_rate_check(request)
    if not _demo_mode():
        # 没有真实短信校验前,开放注册等于允许抢占任意手机号;
        # 非演示模式应由真实验证流程/管理端创建账号
        raise HTTPException(400, "registration disabled")
    body = await read_json_object(request)
    phone = body.get("phone", "")
    password = body.get("password", "")
    phone = phone.strip() if isinstance(phone, str) else ""
    if not isinstance(password, str):
        raise HTTPException(400, "invalid password")
    if not _valid_phone(phone):
        raise HTTPException(400, "invalid phone")
    if len(password) < 6:
        raise HTTPException(400, "weak password")
    if len(password) > PASSWORD_MAX:
        raise HTTPException(400, "password too long")
    if store.find_user_by_phone(phone):
        return JSONResponse({"error": "exists"}, status_code=409)

    salt, digest = store.hash_password(password)
    uid = f"u-{phone}"
    rec = _new_user(uid, phone, "phone-pass", (salt, digest), None, None)
    store.create_user(rec)
    return JSONResponse({"token": store.issue_token(uid),
                         "user": user_dto(rec)})


async def login(request: Request) -> JSONResponse:
    _auth_rate_check(request)
    body = await read_json_object(request)
    method = body.get("method", "password")
    if not isinstance(method, str):
        raise HTTPException(400, "unknown method")

    # ---- 手机号 + 密码 / 验证码 ----
    if method in ("password", "code"):
        raw_phone = body.get("phone", "")
        phone = raw_phone.strip() if isinstance(raw_phone, str) else ""
        found = store.find_user_by_phone(phone)

        if method == "password":
            password = body.get("password", "")
            if not isinstance(password, str):
                raise HTTPException(400, "invalid password")
            if len(password) > PASSWORD_MAX:
                raise HTTPException(400, "password too long")
            if not found:
                return JSONResponse({"error": "notfound"}, status_code=404)
            uid, rec = found
            # 验证码/第三方创建的账户没有密码:按"密码错误"处理,而不是 500
            ok, legacy = _password_matches(password, rec.get("password_hash"))
            if not ok:
                return JSONResponse({"error": "wrong"}, status_code=401)
            if legacy:
                # 旧格式登录成功即升级;写盘失败不影响本次登录
                try:
                    store.update_password_hash(uid, store.hash_password(password))
                except OSError as exc:
                    print(f"[auth] 密码哈希升级失败(不影响本次登录): {exc}")
        else:  # code
            if not _demo_mode():
                raise HTTPException(400, "code login disabled")
            if str(body.get("code", "")) != DEMO_CODE:
                return JSONResponse({"error": "wrong"}, status_code=401)
            if not found:
                # 验证码登录:未注册自动创建账户(与 /register 一致的手机号校验)
                if not _valid_phone(phone):
                    raise HTTPException(400, "invalid phone")
                uid = f"u-{phone}"
                rec = _new_user(uid, phone, "phone-code", None, None, None)
                store.create_user(rec)
            else:
                uid, rec = found
        return JSONResponse({"token": store.issue_token(uid),
                             "user": user_dto(rec)})

    # ---- 微信 / QQ(guest 登录,昵称与头像由前端模拟授权后提供)----
    if method in ("wechat", "qq"):
        if not _demo_mode():
            raise HTTPException(400, "guest login disabled")
        # 游客账号会不断累积:先腾出一个位置(只清理没有有效 token 的最旧记录),
        # 腾不出来才拒绝。prune 的目标必须是 max-1:若按 max 清理,刚好满额时
        # excess=0 永远不会删人,攒满 500 个游客后微信/QQ 登录会永久 429。
        max_guests = _guest_max()
        if max_guests <= 0:
            # 上限 0 = 禁止游客登录:直接拒绝。不要走 prune —— 被拒的请求
            # 不该产生写副作用(否则会顺手删掉现存的游客账号)
            raise HTTPException(429, "guest limit reached")
        store.prune_guests(max_guests - 1)
        if store.guest_count() >= max_guests:
            raise HTTPException(429, "guest limit reached")
        raw_nickname = body.get("nickname", "")
        raw_avatar = body.get("avatar", "")
        nickname = raw_nickname.strip()[:NICKNAME_MAX] if isinstance(raw_nickname, str) else ""
        avatar = raw_avatar.strip()[:AVATAR_MAX] if isinstance(raw_avatar, str) else ""
        uid = f"guest-{method}-{secrets.token_hex(8)}"
        rec = _new_user(uid, None, method, None, nickname or None, avatar or None)
        store.create_user(rec)
        return JSONResponse({"token": store.issue_token(uid), "user": user_dto(rec)})

    raise HTTPException(400, "unknown method")


async def logout(request: Request) -> JSONResponse:
    # 登出与登录共用同一套按 IP 限流:否则伪造 token 刷这里可以无限触发
    # store 的写盘路径(即使 revoke_token 已改成「没删到不写」,也没有理由白跑)
    _auth_rate_check(request)
    token = _bearer_token(request)
    if token:
        rec = store.resolve_token(token)
        store.revoke_token(token)
        if rec:
            # 会话级教材/摘要缓存按 uid 存,登出即清理,避免残留
            session_cache.clear_user(rec.get("uid"))
    return JSONResponse({"ok": True})
