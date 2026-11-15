"""SSE 帧协议:统一的帧格式、逐字节奏与收尾标记。

从 chat.py 拆出:纯协议层,不依赖业务,便于单独测试。
"""
from __future__ import annotations

import asyncio
import json

from starlette.responses import StreamingResponse

CHUNK = 6          # 直答模式每帧字符数(配合浏览器端 ~24ms 渲染节流)

FRAME_MS = 0.02    # 帧间隔(秒),模拟真实模型逐字输出

_DONE = "data: [DONE]\n\n"  # SSE 收尾标记(由 _sse 统一补,生成器不再各自 yield)

def _frame_text_len(frame: str | bytes) -> int:
    """只统计正文帧的字符数:跳过 [DONE]、meta 帧与非 data 帧。

    旧实现按整帧长度记账,把 `data: "`、JSON 引号/转义和结尾换行都算进
    「回复字数」,成本报表会虚高数倍。帧格式由 `_frames`/`_sse` 统一约定,
    这里按同一契约解包。
    """
    raw = frame if isinstance(frame, str) else frame.decode("utf-8", "ignore")
    if raw == _DONE or not raw.startswith("data:"):
        return 0
    payload = raw[5:].strip()
    try:
        value = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return len(payload)
    return len(value) if isinstance(value, str) else 0

def _with_meta(resp: StreamingResponse, meta: dict) -> StreamingResponse:
    """在流最前附一帧元信息(JSON 对象帧):前端据此识别研究型回答
    (导出入口只对研究消息显示)。包在 _meter 之外,meta 帧不计入用量长度"""
    original = resp.body_iterator

    async def prefixed():
        yield f"data: {json.dumps({'mg_meta': meta}, ensure_ascii=False)}\n\n"
        async for frame in original:
            yield frame

    resp.body_iterator = prefixed()
    return resp

async def _frames(text: str, pace: bool = True):
    """按帧切片流式下发一段完整文本(JSON 字符串包裹);收尾标记由 _sse 统一补。
    pace=False 用于引用区等附属内容:不做人工逐字拟态,即时下发"""
    i = 0
    while i < len(text):
        yield f"data: {json.dumps(text[i:i + CHUNK], ensure_ascii=False)}\n\n"
        i += CHUNK
        if pace:
            await asyncio.sleep(FRAME_MS)

def _sse(gen) -> StreamingResponse:
    """SSE 响应统一构造:媒体类型与反缓冲头只写一处
    (散在五处时,漏一个头就会被中间代理缓冲,流式变一次性吐出)。

    收尾的 [DONE] 也由这里统一补。先前是每个生成器各自记得 yield 一行,
    结果四个降级分支(章节导航 / 章节指引 / 粘贴文本 / 语音转写)提前 return 时全漏了:
    前端收不到收尾标记,就没法区分「后端正常降级」和「连接被掐断」,
    只能把半截回答当成完整回答存进历史。契约收进这一层,新生成器想漏也漏不掉。
    生成器里若自带 [DONE] 会在此丢弃,保证一条流恰好一个收尾。"""
    async def terminated():
        async for frame in gen:
            if frame != _DONE:
                yield frame
        # 只有生成器正常跑完才走得到这里;客户端中途断开时本协程被取消,不会补发
        yield _DONE

    return StreamingResponse(
        terminated(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

def _stream_text(text: str) -> StreamingResponse:
    return _sse(_frames(text))
