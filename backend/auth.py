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

user DTO: {nickname, avatar, authMethod: "phone-pass"|"phone-code"|"wechat"|"qq", phone?}
"""
import secrets
from datetime import datetime

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import store

DEMO_CODE = "123456"

DEFAULT_AVATAR = "preset:sum"  # 与前端 AVATAR_PRESETS[0] 对应


def user_dto(rec: dict) -> dict:
    """user DTO:剔除 uid / password_hash 等内部字段"""
    dto = {
        "nickname": rec["nickname"],
        "avatar": rec["avatar"],
        "authMethod": rec["authMethod"],
    }
    if rec.get("phone"):
        dto["phone"] = rec["phone"]
    return dto


def _new_user(uid: str, phone: str | None, method: str, password: str | None,
              nickname: str | None, avatar: str | None) -> dict:
    return {
        "uid": uid,
        "phone": phone,
        "password_hash": password,  # (salt, digest) 或 None(验证码/第三方用户)
        "authMethod": method,
        "nickname": nickname or f"MG用户_{uid[-4:]}",
        "avatar": avatar or DEFAULT_AVATAR,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
    }


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


async def register(request: Request) -> JSONResponse:
    body = await request.json()
    phone = str(body.get("phone", "")).strip()
    password = str(body.get("password", ""))
    if len(phone) != 11 or not phone.isdigit():
        raise HTTPException(400, "invalid phone")
    if len(password) < 6:
        raise HTTPException(400, "weak password")
    if store.find_user_by_phone(phone):
        return JSONResponse({"error": "exists"}, status_code=409)

    salt, digest = store.hash_password(password)
    uid = f"u-{phone}"
    rec = _new_user(uid, phone, "phone-pass", (salt, digest), None, None)
    store.create_user(rec)
    return JSONResponse({"token": store.issue_token(uid),
                         "user": user_dto(rec)})


async def login(request: Request) -> JSONResponse:
    body = await request.json()
    method = body.get("method", "password")

    # ---- 手机号 + 密码 / 验证码 ----
    if method in ("password", "code"):
        phone = str(body.get("phone", "")).strip()
        found = store.find_user_by_phone(phone)

        if method == "password":
            if not found:
                return JSONResponse({"error": "notfound"}, status_code=404)
            uid, rec = found
            # 验证码/第三方创建的账户没有密码:按"密码错误"处理,而不是 500
            ph = rec.get("password_hash")
            if not ph or ph[1] != store.hash_password(str(body.get("password", "")), ph[0])[1]:
                return JSONResponse({"error": "wrong"}, status_code=401)
        else:  # code
            if str(body.get("code", "")) != DEMO_CODE:
                return JSONResponse({"error": "wrong"}, status_code=401)
            if not found:
                # 验证码登录:未注册自动创建账户(与 /register 一致的手机号校验)
                if len(phone) != 11 or not phone.isdigit():
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
        uid = f"guest-{method}-{secrets.token_hex(3)}"
        rec = _new_user(uid, None, method, None,
                        str(body.get("nickname", "")).strip() or None,
                        str(body.get("avatar", "")).strip() or None)
        store.create_user(rec)
        return JSONResponse({"token": store.issue_token(uid), "user": user_dto(uid, rec)})

    raise HTTPException(400, "unknown method")


async def logout(request: Request) -> JSONResponse:
    token = _bearer_token(request)
    if token:
        store.revoke_token(token)
    return JSONResponse({"ok": True})
