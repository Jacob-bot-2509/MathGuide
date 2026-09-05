"""
聊天路由:POST /api/chat/stream(需 Bearer token)。

契约(与 frontend/src/api/types.ts ChatRequest 对齐):
请求体 { prompt: string, cmd?: string, sessionId?: number, categoryKey?: string }

响应为 OpenAI 兼容 SSE,每帧 payload 为 JSON 字符串(正文换行经转义,
帧内无裸换行,data 行不会因正文被拆碎而丢字):
    data: "文本增量"
    ...
    data: [DONE]
前端 postSSE 逐行解析,JSON 解析失败回退纯文本,遇 [DONE] 结束。
"""
import asyncio
import json

from starlette.requests import Request
from starlette.responses import StreamingResponse

import mockllm
from auth import require_auth

CHUNK = 6          # 每帧字符数(配合浏览器端 ~24ms 渲染节流)
FRAME_MS = 0.02    # 帧间隔(秒),模拟真实模型逐字输出(约 300 字/秒,演示更跟手)


async def chat_stream(request: Request) -> StreamingResponse:
    require_auth(request)  # 401: {"detail": "unauthorized"}

    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    cmd = body.get("cmd")

    # sessionId / categoryKey 已随契约接收;当前骨架为无状态单轮回复,
    # 多会话上下文栈由前端维护。接入真模型时在此注入历史上下文。
    # 前端新会话会以空 prompt 触发欢迎问候。
    reply = mockllm.welcome_reply() if not prompt else mockllm.build_reply(prompt, cmd)

    async def gen():
        i = 0
        while i < len(reply):
            # payload 用 JSON 字符串包裹:正文中的换行转义为 \\n,
            # 帧内不出现裸换行,避免 SSE data 行被拆碎丢字(OpenAI 同款格式)
            yield f"data: {json.dumps(reply[i:i + CHUNK], ensure_ascii=False)}\n\n"
            i += CHUNK
            await asyncio.sleep(FRAME_MS)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
