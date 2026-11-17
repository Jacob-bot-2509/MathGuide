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
- GET  /api/auth/session  (Bearer 或 Cookie) → 200 {user} | 401
- POST /api/auth/logout  (Bearer 或 Cookie) → 200 {ok: true}

双域部署:登录成功同时下发 HttpOnly 会话 Cookie(mg_session,作用域由
MG_COOKIE_DOMAIN 控制);learn/research 两个子域共享登录,浏览器存储仍按
origin 各自隔离。Authorization: Bearer 继续兼容,旧客户端不需要改。
请求鉴权先试 Bearer、失效再退回 Cookie(多标签页轮换后旧 Bearer 不会误判未登录)。

会话有效期(滑动续期):token 硬上限 24h,Cookie 记 30 天;每次
GET /api/auth/session 在 token 剩余寿命不足 20% 时轮换新 token,并把新 token
放在响应体 `token` 字段里(前端写回 localStorage),Cookie 同步换成新的。
结果是「30 天内来过就一直登录」,而长期不用的会话最多 24h 后失效。
轮换不吊销旧 token(表里没有退役时间字段,且多标签页可能仍持有),旧 token
会随自己的 24h 到期被清理,暴露窗口不超过原 TTL。

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

import client_ip
import config
import session_cache
import store
import usage
from http_utils import read_json_object
from log import get_logger
from rate_limit import SlidingWindowLimiter

log = get_logger(__name__)

DEMO_CODE = "123456"

# 跨子域共享登录:Cookie 作用域设为父域(MG_COOKIE_DOMAIN),learn/research
# 两个子域都能读到;localStorage 仍按 origin 各自隔离,数据不会因此串区。
COOKIE_NAME = "mg_session"
# 滑动续期(D1 方案 B):Cookie 记 30 天,真正的有效期看 token。
# token 仍是 24h 硬上限,但每次 /api/auth/session 在剩余寿命不足 20% 时轮换新 token,
# Cookie 同步刷新 —— "30 天内来过就一直是登录态",长期不用则最多 24h 后失效。
COOKIE_MAX_AGE = 30 * 24 * 3600
RENEW_AFTER_RATIO = 0.8  # 已用掉 TTL 的 80%(剩 20%)才轮换,避免每次启动都写库
RENEW_MIN_INTERVAL = 300.0  # 同一账号 5 分钟内不重复轮换(客户端没写回新 token 时防抖)
TOKEN_SCOPE_KEY = "mg.token"  # 请求实际生效的 token,放在 request.scope 里供 session() 复用

DEFAULT_AVATAR = "preset:sum"  # 与前端 AVATAR_PRESETS[0] 对应
NICKNAME_MAX = 40
AVATAR_MAX = 500
PASSWORD_MAX = 1024  # 只防超长输入刷内存/CPU;旧账号可能设置过更长口令,不要误锁
GUEST_MAX_DEFAULT = 500

# 认证接口限流:登录/注册/登出/导出/注销共用,按客户端 IP;演示期也不会误伤正常操作
_AUTH_RATE_MAX = 10
_AUTH_RATE_WINDOW = 60.0
# 双闸(MG_AUTH_DUAL_BUCKET=1,默认关)下 IP 桶的默认上限。它不再是"每个账号能试几次",
# 而是"一个出口 IP 后面整间机房一分钟最多过多少人":40 人同时点登录 ≈ 80 次/分,
# 取 120 留出每人再重试一次的余量。
DUAL_IP_RATE_DEFAULT = 120
_AUTH_IP_RATE_MAX = _AUTH_RATE_MAX  # 双闸关闭时,IP 桶就是唯一那个桶
_AUTH_DUAL = False
_auth_limiter = SlidingWindowLimiter(_AUTH_RATE_MAX, _AUTH_RATE_WINDOW)
# 只在双闸开启时存在(None = 关闭):按手机号 / uid 的账号桶
_auth_id_limiter: SlidingWindowLimiter | None = None


def _env_number(name: str, default: float, minimum: float) -> float:
    """读取数值环境变量;非法/过小回退默认,不让配置错误把限流关掉。

    实现放在 `config.env_number`(chat 的每用户限流用同一套口径,避免两处
    各写一份"坏值怎么办")。
    """
    return config.env_number(name, default, minimum)


def _env_flag(name: str) -> bool:
    """读取布尔开关:只有 1 / true / on / yes 算打开(默认关)。

    与 `config.demo_mode`(默认开、显式关)方向相反,所以不复用那套写法:
    这里的开关一旦漏读就会放宽防护,缺省必须是关。
    """
    return os.getenv(name, "").strip().lower() in ("1", "true", "on", "yes")


def configure_rate_limit() -> None:
    """按环境变量重建认证限流器。

    MG_AUTH_RATE_MAX     单账号(同一手机号/uid)上限,默认 10 次;双闸关闭时就是每 IP 上限
    MG_AUTH_RATE_WINDOW  默认 60 秒
    MG_AUTH_DUAL_BUCKET  1 = 打开「IP 桶 + 账号桶」双闸(默认关)
    MG_AUTH_IP_RATE_MAX  双闸下每个 IP 的上限,默认 120;按「人数 × 3 / 分钟」估

    为什么需要两档:只按 IP,机房(一个出口 IP)会把 40 个学生算成一个人,第 11 个就
    429;只按账号,攻击者换手机号就能继续爆破。双闸各管一头 —— IP 桶当机房天花板,
    账号桶才是爆破防护。默认关:它放宽的是"一个 IP 一分钟能过多少人",不该替所有人
    默认放宽,考试当天加一个环境变量即可(见 docs/DEPLOY_PLAYBOOK.md §五之三)。
    """
    global _AUTH_RATE_MAX, _AUTH_RATE_WINDOW, _AUTH_IP_RATE_MAX, _AUTH_DUAL
    global _auth_limiter, _auth_id_limiter
    _AUTH_RATE_MAX = int(_env_number("MG_AUTH_RATE_MAX", 10, 1))
    _AUTH_RATE_WINDOW = _env_number("MG_AUTH_RATE_WINDOW", 60.0, 1.0)
    _AUTH_DUAL = _env_flag("MG_AUTH_DUAL_BUCKET")
    _AUTH_IP_RATE_MAX = _AUTH_RATE_MAX
    if _AUTH_DUAL:
        _AUTH_IP_RATE_MAX = int(_env_number("MG_AUTH_IP_RATE_MAX", DUAL_IP_RATE_DEFAULT, 1))
        if _AUTH_IP_RATE_MAX < _AUTH_RATE_MAX:
            # 写反了:IP 桶比单账号额度还小,每个人的额度都会被它压住,双闸退化成
            # 一个更小的单桶。按账号上限纠正 —— 配置写错绝不能变成更弱的保护
            log.warning(
                f"[auth] MG_AUTH_IP_RATE_MAX={_AUTH_IP_RATE_MAX} 小于 MG_AUTH_RATE_MAX="
                f"{_AUTH_RATE_MAX}:IP 桶是「整间机房每分钟过多少人」的天花板,不应小于"
                f"单账号额度,已按 {_AUTH_RATE_MAX} 处理"
            )
            _AUTH_IP_RATE_MAX = _AUTH_RATE_MAX
    _auth_limiter = SlidingWindowLimiter(_AUTH_IP_RATE_MAX, _AUTH_RATE_WINDOW)
    _auth_id_limiter = (
        SlidingWindowLimiter(_AUTH_RATE_MAX, _AUTH_RATE_WINDOW) if _AUTH_DUAL else None
    )
    if _AUTH_DUAL:
        log.info(
            f"[auth] 认证限流双闸:IP {_AUTH_IP_RATE_MAX} 次/{_AUTH_RATE_WINDOW:g}s"
            f" + 账号 {_AUTH_RATE_MAX} 次/{_AUTH_RATE_WINDOW:g}s"
            "(同一出口的不同账号互不影响,单账号爆破仍被拦)"
        )


def _demo_mode() -> bool:
    """演示通道开关:默认开启(本机演示);显式设 0/false/off/no 关闭。"""
    return config.demo_mode()


def _guest_max() -> int:
    """游客账号上限;0 表示禁止游客登录。坏值回退默认。"""
    raw = os.getenv("MG_GUEST_MAX", str(GUEST_MAX_DEFAULT)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return GUEST_MAX_DEFAULT


def _client_key(request: Request) -> str:
    """按 IP 限流用的 key:信任链判定统一交给 client_ip(见 docs/DEPLOY_PLAYBOOK.md §一.4)。

    这里不再直接读 request.client.host —— 那个值对不对取决于 uvicorn 参数与反代头
    是否同时正确,配错时会静默变成「全站一个桶」或「伪造 XFF 生效」。client_ip
    会在对端不可信时忽略 XFF,并在塌陷时打一条可执行的 ERROR。
    """
    return client_ip.client_key(request)


def reset_rate_limits() -> None:
    """清空两个桶(测试基座用;`configure_rate_limit` 负责重建它们)。"""
    _auth_limiter.reset()
    if _auth_id_limiter is not None:
        _auth_id_limiter.reset()


def _too_many() -> HTTPException:
    """429 的统一出口,带 Retry-After。

    前端据此提示「稍等 N 秒」而不是「连不上服务器」—— 考场上那条误报会让老师去
    重启后端,把正在答题的人一起掉线(与 chat.py 的 _rate_check 同一口径)。
    """
    return HTTPException(429, "rate limited",
                         headers={"Retry-After": str(int(_AUTH_RATE_WINDOW) or 60)})


def _auth_rate_check(request: Request) -> None:
    """第一个桶:按客户端 IP。双闸关闭时它就是唯一的桶(10 次/60 秒)。"""
    if not _auth_limiter.allow(_client_key(request)):
        raise _too_many()


def _auth_account_check(ident: str) -> None:
    """第二个桶:按账号(手机号 / uid)。只在双闸开启时生效,关闭时是纯 no-op。

    与 IP 桶分开,为的是「同一个出口 IP 后面 40 个学生互不影响」:IP 桶只当天花板
    (MG_AUTH_IP_RATE_MAX),爆破防护落在单账号额度上。没有账号标识的请求(游客登录、
    手机号格式非法)只受 IP 桶约束 —— 调用点自己决定传什么,不要拿原始输入当 key。
    """
    if _auth_id_limiter is None:
        return
    who = (ident or "").strip()
    if not who:
        return
    if not _auth_id_limiter.allow(who):
        log.warning("[auth] 同一账号的认证请求过密,已限流(IP 桶未触及)")
        raise _too_many()


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


def _issue_for(uid: str) -> str:
    """签发 token 并刷新最近活动时间(留存清理依据)。"""
    try:
        store.touch_user(uid)
    except OSError:
        # 用户表只读/占用时不能反过来阻止登录;留存时间下次再更新
        pass
    return store.issue_token(uid)


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
        "lastActiveAt": datetime.now().isoformat(timespec="seconds"),
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


def _tokens_in_play(request: Request) -> list[str]:
    """本次请求可用的凭据列表:Authorization 优先,其次 HttpOnly Cookie。

    两级都试、而不是只认第一个:Bearer 来自 localStorage,可能是上一次轮换前的
    旧 token(另一个标签页已经刷新过 Cookie),只认它会把用户白白踢回登录页。
    """
    tokens: list[str] = []
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            tokens.append(token)
    cookie = request.cookies.get(COOKIE_NAME, "")
    if cookie and cookie not in tokens:
        tokens.append(cookie)
    return tokens


def _bearer_token(request: Request) -> str:
    """当前请求的首选凭据(Bearer 优先);仅用于清理类操作。"""
    tokens = _tokens_in_play(request)
    return tokens[0] if tokens else ""


def _cookie_domain() -> str | None:
    """Cookie 作用域:仅当显式配置 MG_COOKIE_DOMAIN 时跨子域共享。

    空值 = host-only(本机开发/单域部署),不会把凭据扩散到其他服务。
    """
    value = os.getenv("MG_COOKIE_DOMAIN", "").strip()
    return value or None


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return proto == "https" or request.url.scheme == "https"


def _set_session_cookie(response: JSONResponse, token: str, request: Request) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        domain=_cookie_domain(),
        path="/",
    )


def _auth_json(payload: dict, request: Request, token: str) -> JSONResponse:
    """认证成功响应:下发 token(兼容旧客户端)并写共享会话 Cookie。"""
    response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    _set_session_cookie(response, token, request)
    return response


def require_auth(request: Request) -> dict:
    """取当前登录用户;未认证抛 401(Starlette 默认转 JSON {"detail": ...})。

    先试 Bearer、失效再退回 Cookie:轮换后旧标签页手里的 Bearer 会过期,
    但 Cookie 可能已经是新 token,不该因此判定"未登录"。
    """
    for token in _tokens_in_play(request):
        rec = store.resolve_token(token)
        if rec:
            request.scope[TOKEN_SCOPE_KEY] = token
            return rec
    raise HTTPException(401, "unauthorized")


def _valid_phone(phone: str) -> bool:
    return len(phone) == 11 and phone.isdigit()


async def register(request: Request) -> JSONResponse:
    _auth_rate_check(request)
    body = await read_json_object(request)
    if not _demo_mode():
        # 非演示模式:开放注册会允许抢占任意手机号;只放行持测评邀请码的注册。
        codes = config.invite_codes()
        if not codes:
            raise HTTPException(400, "registration disabled")
        invite = body.get("invite")
        supplied = invite.strip() if isinstance(invite, str) else ""
        if not supplied or not any(secrets.compare_digest(supplied, code) for code in codes):
            return JSONResponse({"error": "invite"}, status_code=403)
    phone = body.get("phone", "")
    password = body.get("password", "")
    phone = phone.strip() if isinstance(phone, str) else ""
    if not isinstance(password, str):
        raise HTTPException(400, "invalid password")
    if not _valid_phone(phone):
        raise HTTPException(400, "invalid phone")
    # 双闸:手机号格式合法才建账号桶 —— 拿原始输入当 key 会让随机串撑大 key 空间
    _auth_account_check(phone)
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
    token = _issue_for(uid)
    return _auth_json({"token": token, "user": user_dto(rec)}, request, token)


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
        if _valid_phone(phone):
            # 双闸:只有手机号格式合法才算"某个账号";否则(垃圾输入)只按 IP 计,
            # 避免给每个随手编的字符串都建一个桶
            _auth_account_check(phone)
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
                    log.warning(f"[auth] 密码哈希升级失败(不影响本次登录): {exc}")
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
        token = _issue_for(uid)
        return _auth_json({"token": token, "user": user_dto(rec)}, request, token)

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
        def clean_guest(rec):
            import diagnosis
            import exercise_history
            import research_corpus

            uid = str(rec.get("uid") or "")
            usage.delete_user(uid, str(rec.get("phone") or ""))
            diagnosis.delete_user(uid)
            exercise_history.delete_user(uid)
            research_corpus.delete_user(uid)
            session_cache.clear_user(uid)

        store.prune_guests(max_guests - 1, before_delete=clean_guest)
        if store.guest_count() >= max_guests:
            raise HTTPException(429, "guest limit reached")
        raw_nickname = body.get("nickname", "")
        raw_avatar = body.get("avatar", "")
        nickname = raw_nickname.strip()[:NICKNAME_MAX] if isinstance(raw_nickname, str) else ""
        avatar = raw_avatar.strip()[:AVATAR_MAX] if isinstance(raw_avatar, str) else ""
        uid = f"guest-{method}-{secrets.token_hex(8)}"
        rec = _new_user(uid, None, method, None, nickname or None, avatar or None)
        store.create_user(rec)
        token = _issue_for(uid)
        return _auth_json({"token": token, "user": user_dto(rec)}, request, token)

    raise HTTPException(400, "unknown method")


def _should_renew(token: str) -> bool:
    """剩余寿命不足 20% 时返回 True(见 RENEW_AFTER_RATIO)。

    轮换**不吊销**旧 token:tokens 表没有"退役时间"字段(本轮不改表结构),
    而多标签页与长连接可能仍持有旧 token;它会在自己的 24h 到期时被
    `issue_token` 里的 sweep 清掉,暴露窗口不超过原 TTL。
    """
    age = store.token_age(token)
    if age is None:
        return False
    return age >= store.TOKEN_TTL_HOURS * 3600 * RENEW_AFTER_RATIO


def _renewed_recently(uid: str) -> bool:
    """同一账号刚轮换过就跳过:客户端可能不写回新 token,否则每次启动都会签发一个。"""
    newest = store.newest_token_age(uid)
    return newest is not None and newest < RENEW_MIN_INTERVAL


async def session(request: Request) -> JSONResponse:
    """当前登录态(供跨子域启动时恢复登录):

    - 凭据有效 → 返回 user;接近过期时轮换 token 并在响应体里带回新 token;
    - 只有旧 Bearer token → 补发 Cookie,升级到跨子域登录;
    - 都没有 → 401,前端回登录页。
    """
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    used = str(request.scope.get(TOKEN_SCOPE_KEY) or "")
    payload: dict = {"user": user_dto(rec)}
    response_token = used
    if used and _should_renew(used) and not _renewed_recently(uid):
        try:
            response_token = store.issue_token(uid)
            payload["token"] = response_token
        except OSError as exc:
            # 写库失败不影响本次请求:继续用旧 token,Cookie 也不动
            log.warning(f"[auth] 会话续期失败(本次沿用旧 token): {exc}")
            response_token = used
    response = JSONResponse(payload, headers={"Cache-Control": "no-store"})
    if response_token:
        _set_session_cookie(response, response_token, request)
    return response


async def logout(request: Request) -> JSONResponse:
    # 登出与登录共用同一套按 IP 限流:否则伪造 token 刷这里可以无限触发
    # store 的写盘路径(即使 revoke_token 已改成「没删到不写」,也没有理由白跑)
    # 双闸下这里只走 IP 桶,不加账号桶:登出没有账号可爆破,而「下课全班同时登出」
    # 恰恰需要 IP 桶足够大(MG_AUTH_IP_RATE_MAX 就是那个天花板)。
    _auth_rate_check(request)
    # Bearer 与 Cookie 都清:轮换后两者可能不是同一个 token,只删一个会留下
    # 仍然可用的凭据(用户以为已登出,Cookie 还能继续用)
    rec = None
    for token in _tokens_in_play(request):
        found = store.resolve_token(token)
        store.revoke_token(token)
        rec = rec or found
    if rec:
        # 会话级教材/摘要缓存按 uid 存,登出即清理,避免残留
        session_cache.clear_user(rec.get("uid"))
    response = JSONResponse({"ok": True})
    # 共享登录 Cookie 一并失效;Bearer token 删除逻辑保持不变
    response.delete_cookie(COOKIE_NAME, domain=_cookie_domain(), path="/")
    return response


async def export_account(request: Request) -> JSONResponse:
    """导出后端持有的账号与用量元数据(学习正文在浏览器,由前端合并导出)。"""
    _auth_rate_check(request)
    rec = require_auth(request)
    # 双闸:导出的成本比登录高,双闸开启后 IP 桶放宽到「机房天花板」,这里改用
    # 账号桶(uid)兜住"登录一次后无限导出"
    _auth_account_check(str(rec.get("uid") or ""))
    uid = str(rec.get("uid") or "")
    phone = str(rec.get("phone") or "")
    account = user_dto(rec)
    if rec.get("createdAt"):
        account["createdAt"] = rec["createdAt"]
    # 诊断记录与用量同口径:随账号导出,注销时级联删除(局部导入避免循环依赖)
    import diagnosis
    import exercise_history
    import research_corpus
    import research_tables

    return JSONResponse({
        "exportedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "account": account,
        "usage": usage.for_user(uid, phone),
        "diagnoses": diagnosis.for_user(uid),
        "exerciseDocuments": exercise_history.documents_for_export(uid),
        "researchDocs": research_corpus.docs_for_export(uid),
        "researchProjects": research_corpus.projects_for_export(uid),
        "researchTables": research_tables.tables_for_export(uid),
        "note": "学习会话、归纳本与待办保存在浏览器本地,导出文件会由前端一并合并。",
    }, headers={"Cache-Control": "no-store"})


async def delete_account(request: Request) -> JSONResponse:
    """注销账号:校验后删除后端账号、全部 token 与该账号用量记录。

    - 手机号密码账号:必须再输一次当前密码,避免 token 被借用后一键注销;
    - 验证码/微信/QQ 账号没有密码:输入 DELETE / 注销 作为二次确认。
    本机学习数据由前端注销流程清理。
    """
    _auth_rate_check(request)
    rec = require_auth(request)
    _auth_account_check(str(rec.get("uid") or ""))
    body = await read_json_object(request)
    stored_password = rec.get("password_hash")
    if stored_password:
        password = body.get("password")
        if not isinstance(password, str) or not _password_matches(password, stored_password)[0]:
            return JSONResponse({"error": "wrong"}, status_code=401)
    else:
        confirm = body.get("confirm")
        if confirm not in ("DELETE", "注销"):
            raise HTTPException(400, "confirmation required")

    uid = str(rec.get("uid") or "")
    phone = str(rec.get("phone") or "")
    if not uid:
        raise HTTPException(400, "invalid account")
    # 先删用量再删账号:用量写盘失败时账号仍在,用户可以重试,不会留下孤儿日志
    usage.delete_user(uid, phone)
    import diagnosis

    diagnosis.delete_user(uid)
    import exercise_history

    exercise_history.delete_user(uid)
    # 科研文档/项目/表格随账号一并删除,避免留下孤儿数据
    import research_corpus

    research_corpus.delete_user(uid)
    store.delete_user(uid)
    session_cache.clear_user(uid)
    response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
    response.delete_cookie(COOKIE_NAME, domain=_cookie_domain(), path="/")
    return response
