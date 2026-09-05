"""
MathGuide 后端骨架(演示环境)
启动:python -m uvicorn main:app --host 0.0.0.0 --port 8000

接口一览(契约详见各模块注释与 backend/README.md):
    GET  /api/health                         健康检查
    POST /api/auth/register                  注册(手机号 + 密码)
    POST /api/auth/login                     登录(password / code / wechat / qq)
    POST /api/auth/logout                    登出(需 token)
    POST /api/chat/stream                    聊天流式回复(需 token,OpenAI 兼容 SSE)
"""
import store
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import chat


async def health(request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "mg-backend"})


routes = [
    Route("/api/health", health),
    Route("/api/auth/register", auth.register, methods=["POST"]),
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/chat/stream", chat.chat_stream, methods=["POST"]),
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

# 新版 starlette 无 on_startup 参数:进程启动即装载数据文件(演示单进程足够)
store.init()
