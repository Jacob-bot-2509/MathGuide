"""
MathGuide 后端(RAG 检索增强生成骨架)
启动:python -m uvicorn main:app --host 127.0.0.1 --port 8000
(MG_DEMO_MODE=1 时只允许本机绑定;公网部署先设 MG_DEMO_MODE=0)

接口一览(契约详见各模块注释与 backend/README.md):
    GET  /api/health                         健康检查
    POST /api/auth/register                  注册(手机号 + 密码)
    POST /api/auth/login                     登录(password / code / wechat / qq)
    POST /api/auth/logout                    登出(需 token)
    POST /api/account/export                 导出账号与用量元数据(需 token)
    POST /api/account/delete                 注销账号并级联删除令牌/用量(需 token)
    POST /api/chat/stream                    聊天流式回复(需 token,OpenAI 兼容 SSE)

知识库:knowledge/*.md → rag 切片索引 → 检索 → LLM(未配置则直答)。
"""
import sys

# Windows 控制台默认 GBK:模型输出含 GBK 无法编码的字符(如下标 ₀)时,
# 任何 print 都会抛 UnicodeEncodeError 打断回答链路 —— 启动即强制 UTF-8 + 行缓冲
# (行缓冲保证日志实时落盘,不会因块缓冲攒在内存里看不到)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import asyncio

import store
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route

import auth
import chat
import config
import doc
import rag
import retention
import usage
from security_headers import SecurityHeadersMiddleware

# 先装载本地配置(.env.local,key 不入库),再构造 app/CORS 与数据、知识库。
# 必须早于 app 构造:MG_CORS_ORIGINS 等配置来自 .env.local。
config.load_env()
# 演示模式默认只允许本机;`--host 0.0.0.0` 或公网 CORS 来源会直接拒绝启动
config.assert_safe_demo_mode()
# .env.local 装载后再读限流配置(模块导入时 env 还没加载)
auth.configure_rate_limit()


def _cors_origins() -> list[str]:
    """开发默认只放行本机前端;需要别的来源时用 MG_CORS_ORIGINS 显式列出。"""
    return config.cors_origins()


async def health(request) -> JSONResponse:
    # demo/invite 供登录页隐藏演示通道;不涉及账号或密钥
    return JSONResponse({
        "ok": True,
        "service": "mg-backend",
        "demo": config.demo_mode(),
        "invite": bool(config.invite_codes()),
    })


async def stats(request) -> JSONResponse:
    """用量统计(仅管理员):总调用数 / 总字数 / 按用户 / 按模型角色"""
    auth.require_admin(request)
    # 读取/汇总 JSON 放线程池,避免大文件时阻塞事件循环
    return JSONResponse(await asyncio.to_thread(usage.summary))


routes = [
    Route("/api/health", health),
    Route("/api/auth/register", auth.register, methods=["POST"]),
    Route("/api/auth/login", auth.login, methods=["POST"]),
    Route("/api/auth/logout", auth.logout, methods=["POST"]),
    Route("/api/account/export", auth.export_account, methods=["POST"]),
    Route("/api/account/delete", auth.delete_account, methods=["POST"]),
    Route("/api/chat/stream", chat.chat_stream, methods=["POST"]),
    Route("/api/speech/math", chat.speech_to_math, methods=["POST"]),
    Route("/api/doc/export", doc.export_pdf, methods=["POST"]),
    Route("/api/stats", stats),
]

app = Starlette(
    routes=routes,
    middleware=[
        Middleware(
            CORSMiddleware,
            # 开发默认只放行本机前端(vite 5173 走代理同源,直连调试亦可用);
            # 需要其他来源时在 .env.local 配置 MG_CORS_ORIGINS,不要长期用 "*"。
            allow_origins=_cors_origins(),
            allow_methods=["*"],
            allow_headers=["*"],
        ),
        Middleware(SecurityHeadersMiddleware),
    ],
)

# 再装载数据与知识库(演示单进程足够)
store.init()
# 旧 usage 记录只有 phone/user:启动时换成 uid 并清掉 PII(失败不阻断服务)
try:
    usage.migrate_identity(store.phone_uid_map())
except OSError as exc:
    print(f"[usage] 旧用量身份迁移失败(不影响启动): {exc}")
try:
    pruned = retention.run()
    if pruned["accounts"] or pruned["usage"]:
        print(f"[retention] 已清理账号 {pruned['accounts']} 个、用量 {pruned['usage']} 条")
except OSError as exc:
    print(f"[retention] 留存清理失败(不影响启动): {exc}")
rag.init()
