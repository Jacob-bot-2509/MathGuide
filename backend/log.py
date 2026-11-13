"""统一日志入口。

为什么不用裸 `print`:

- 级别:启动/清理是 INFO,降级回退是 WARNING,吞掉的异常是 ERROR;print 分不出来;
- 定位:每条日志带模块名与 request_id,一次回答链路的十几条日志能串起来;
- 生产:可换成 JSON handler 或接到 journald,不用改 30 个模块。

保守约束(与现有 usage 记账口径一致):
- **不记录** prompt / 回答正文 / 手机号 / 论文正文,只记 uid、长度、耗时、模型角色;
- 输出仍走 stdout(保留 main.py 里的 UTF-8 + line_buffering 修复,Windows 控制台才不会
  因为 ₀ 这类下标字符抛 UnicodeEncodeError)。

用法:

    from log import get_logger
    log = get_logger(__name__)
    log.info("[chat] role=%s len=%d", role, len(prompt))
"""
from __future__ import annotations

import contextvars
import logging
import os
import sys
import uuid

_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)-16s %(message)s"

# 一次请求一个 id:SSE 流里散落的十几条日志靠它串起来。
# 用 ContextVar 而不是全局变量,并发请求不会互相覆盖。
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("mg_request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def current_request_id() -> str:
    return _REQUEST_ID.get()


class _RequestIdFilter(logging.Filter):
    """把当前上下文的 request_id 塞进 LogRecord,供 format 使用。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID.get()
        return True


class RequestIdMiddleware:
    """纯 ASGI 中间件(不用 BaseHTTPMiddleware,避免影响 SSE 流式输出)。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        token = _REQUEST_ID.set(new_request_id())
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST_ID.reset(token)


def _level() -> int:
    """MG_LOG_LEVEL=DEBUG/INFO/WARNING/ERROR;非法值回退 INFO。"""
    raw = os.getenv("MG_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO) if isinstance(getattr(logging, raw, None), int) else logging.INFO


def configure() -> None:
    """装一次 handler;重复调用无副作用(pytest 会反复导入模块)。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, datefmt="%H:%M:%S"))
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger("mg")
    root.handlers = [handler]
    root.setLevel(_level())
    # 不向上冒泡:避免 uvicorn 自己的 handler 再打一遍
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """按模块名取 logger,统一挂在 `mg.` 命名空间下。"""
    configure()
    short = name.rsplit(".", 1)[-1] or "app"
    return logging.getLogger(f"mg.{short}")
