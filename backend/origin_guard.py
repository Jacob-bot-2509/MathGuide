"""写操作的来源校验(CSRF 纵深防御)。

已有防护是会话 Cookie 的 `SameSite=Lax`,它挡住绝大多数跨站 POST。这里再收一道,
原因很具体:

- 双域部署下 Cookie 作用域是父域(`MG_COOKIE_DOMAIN=.example.com`),
  **任一子域被 XSS 就等于全站可写**;
- 演示/测评期可能临时配 `MG_CORS_ORIGINS` 放宽来源,来源校验能兜住误配。

规则(只作用于 POST / PUT / PATCH / DELETE):

1. 有 `Origin`:其 `scheme://host` 必须与请求 Host 同源,或在允许列表里;
2. 没有 `Origin` 但有 `Referer`:按 `Referer` 的来源判断;
3. 两者都没有:**放行** —— 非浏览器客户端(curl / 脚本 / 测试)天生不受 CSRF 影响,
   拦了它们只会误伤自动化。

实现为纯 ASGI 中间件(不用 BaseHTTPMiddleware):后者会把流式响应包一层,
对 SSE 有已知的缓冲/取消延迟问题。
"""
from __future__ import annotations

from urllib.parse import urlsplit

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_FORBIDDEN_BODY = b'{"detail":"cross-origin request blocked"}'
_SKIP_PATHS = frozenset({"/api/auth/login", "/api/auth/register"})


def _origin_of(value: str) -> str:
    """把 Origin/Referer 归一成 `scheme://netloc`;无法解析返回空串。"""
    if not value:
        return ""
    parts = urlsplit(value.strip())
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower()


def _netloc_of(origin: str) -> str:
    return urlsplit(origin).netloc.lower()


class OriginGuardMiddleware:
    """写方法 + 跨站来源 → 403。"""

    def __init__(self, app, allowed_origins: list[str] | None = None):
        self.app = app
        self.allowed = {o for o in (_origin_of(item) for item in (allowed_origins or [])) if o}

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http" or str(scope.get("method", "GET")).upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        if str(scope.get("path", "")) in _SKIP_PATHS:
            # 登录/注册页面可能是别的站点跳转过来的(比如测评说明页),不能拦
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in (scope.get("headers") or [])
        }
        host = headers.get("host", "")
        origin = _origin_of(headers.get("origin", "")) or _origin_of(headers.get("referer", ""))
        if origin and not self._allowed(origin, host):
            await self._reject(send)
            return
        await self.app(scope, receive, send)

    def _allowed(self, origin: str, host: str) -> bool:
        if origin in self.allowed:
            return True
        # 只比 netloc:反代可能把 scheme 改写成 http,但 Host 头仍是用户看到的那一个
        return bool(host) and _netloc_of(origin) == host.split(",")[0].strip().lower()

    async def _reject(self, send) -> None:
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_FORBIDDEN_BODY)).encode()),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": _FORBIDDEN_BODY})
