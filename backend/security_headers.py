"""API 响应安全头。

CSP 属于前端静态资源的部署配置(deploy/),这里只放所有 API 都适用的
基础头;HSTS 只在确认走 HTTPS 时发送,避免本机 HTTP 被浏览器记住。
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

_HTTPS_VALUES = {"https"}
_HSTS_TRUE = {"1", "true", "yes", "on"}


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme in _HTTPS_VALUES or proto in _HTTPS_VALUES


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        headers = response.headers

        def setdefault(name: str, value: str) -> None:
            if name not in headers:
                headers[name] = value

        setdefault("X-Content-Type-Options", "nosniff")
        setdefault("Referrer-Policy", "no-referrer")
        setdefault("X-Frame-Options", "DENY")
        setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=(self)")
        if _is_https(request) or os.getenv("MG_ENABLE_HSTS", "").strip().lower() in _HSTS_TRUE:
            setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
