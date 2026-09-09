"""
MathGuide 后端(RAG 检索增强生成骨架)
启动:python -m uvicorn main:app --host 0.0.0.0 --port 8000

接口一览(契约详见各模块注释与 backend/README.md):
    GET  /api/health                         健康检查
    POST /api/auth/register                  注册(手机号 + 密码)
    POST /api/auth/login                     登录(password / code / wechat / qq)
    POST /api/auth/logout                    登出(需 token)
    POST /api/chat/stream                    聊天流式回复(需 token,OpenAI 兼容 SSE)

知识库:knowledge/*.md → rag 切片索引 → 检索 → LLM(未配置则直答)。
"""
import sys

# Windows 控制台默认 GBK:模型输出含 GBK 无法编码的字符(如下标 ₀)时,
# 任何 print 都会抛 UnicodeEncodeError 打断回答链路 —— 启动即强制 UTF-8 + 行缓冲
# (行缓冲保证日志实时落盘,不会因块缓冲攒在内存里看不到)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import store
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import chat
import config
import rag
import usage


async def health(request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "mg-backend"})


async def stats(request) -> JSONResponse:
    """用量统计(需登录):总调用数 / 总字数 / 按用户 / 按模型角色"""
    auth.require_auth(request)
    return JSONResponse(usage.summary())


routes = [
    Route("/api/health", health),
    Route("/api/auth/register", auth.register, methods=["POST"]),
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/chat/stream", chat.chat_stream, methods=["POST"]),
    Route("/api/speech/math", chat.speech_to_math, methods=["POST"]),
    Route("/api/stats", stats),
]

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            # 开发期放行所有来源(前端 5173 走 vite 代理同源,直连调试亦可用)
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)

# 先装载本地配置(.env.local,key 不入库),再装载数据与知识库(演示单进程足够)
config.load_env()
store.init()
rag.init()
