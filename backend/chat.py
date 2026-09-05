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

回复链路(RAG):
- 空 prompt → 欢迎语;
- 已配置 LLM(环境变量 MG_LLM_BASE_URL / MG_LLM_API_KEY)→ 检索知识片段 →
  组装 system prompt → 模型流式输出;
- 未配置 LLM → 知识库直答模式:流式下发检索到的知识片段,全链路仍可演示。
"""
import asyncio
import json
import re

from starlette.requests import Request
from starlette.responses import StreamingResponse

import rag
from auth import require_auth

CHUNK = 6          # 直答模式每帧字符数(配合浏览器端 ~24ms 渲染节流)
FRAME_MS = 0.02    # 帧间隔(秒),模拟真实模型逐字输出

WELCOME_ZH = (
    "**欢迎回到 MATHGUIDE · 学习辅助**\n\n"
    "我是 MG,你的高等数学学习与研究助手。直接提问即可,或用下方指令:"
    "概念动画演示 / 例题精讲 / 章节知识导航 / 错题归纳 / 公式查询手册。\n\n"
    "问题的**板块与难度我会自动识别**,先给严谨的专业表述,再给形象化理解,并带上公式推演;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Learn. You can also ask in English, e.g. \"explain limits with intuition\".)"
)

LEVEL_ZH = {"basic": "基础", "advance": "进阶", "competition": "竞赛"}
LEVEL_EN = {"basic": "basic", "advance": "advanced", "competition": "competition"}


def judge_level(text: str) -> str:
    """按问题措辞自动判断难度(中英文关键词),绝不反问用户。"""
    t = text.lower()
    if any(k in t for k in ("竞赛", "奥数", "imo", "cmo", "难题", "挑战", "压轴", "拔尖", "olympiad")):
        return "competition"
    if any(k in t for k in ("基础", "入门", "初学", "简单", "是什么", "定义", "概念", "为什么", "怎么理解",
                            "通俗", "新手", "what is", "definition", "concept", "beginner", "basic",
                            "introduction", "intuitively")):
        return "basic"
    return "advance"


FALLBACK_ZH = (
    "这个问题我已按措辞自动判定难度为**{level}**。\n\n"
    "**通用三步走(专业表述):** ① 明确对象与条件,把问题转化为标准型(极限式、方程、积分、模型);"
    "② 选择对应工具求解;③ **回代验算**——MG 的「自我验证工作流」会在解答发布前进行一致性检查与符号复验,"
    "低置信度时会主动标注「该解答需进行人工处理」。\n\n"
    "**形象理解:** 解数学题像侦探破案:先锁定案件类型,再盘点物证(条件),"
    "最后用匹配的手法收网;每一步结论都要经得起「代入原题」这关审讯。\n\n"
    "把题目原文(或拍照上传)发给我,我会按上面的框架给出带完整过程的解答。"
)

FALLBACK_EN = (
    "I've read your question and automatically rate its difficulty as **{level}**.\n\n"
    "**Approach (3 steps):** 1) Identify the objects and conditions, and rewrite the problem into a canonical form "
    "(a limit, an equation, an integral, or a model); 2) apply the matching tool; 3) **verify by substitution**. "
    "MG's self-verification workflow runs consistency checks and symbolic re-validation before publishing an answer, "
    "flagging low-confidence ones as \"manual review required\".\n\n"
    "**Intuition:** solving a math problem is like detective work — classify the case, collect the evidence, "
    "close the net with the right method, and cross-examine every conclusion by plugging it back in.\n\n"
    "Paste the full problem (or upload a photo) and I'll work through it step by step."
)

ATTACH_IMAGE_ZH = (
    "已收到你上传的图片 **{name}**。\n\n"
    "当前演示环境会保留图片于会话记录中;接入视觉模型后,MG 将直接识图作答:"
    "拍照的手写题目 → OCR + 版面解析 → 按板块与难度路由。\n\n"
    "**现在你可以:** ① 把题目文字打出来,我照常解答;② 先手动归入对应板块(题目类型判断已生效)。"
)
ATTACH_FILE_ZH = (
    "已收到文件 **{name}**(大小 {size} KB)。\n\n"
    "演示环境仅保存文件元信息;接入后端文件服务后支持 PDF / 讲义解析,"
    "可执行「章节知识导航」与「例题精讲」的整篇喂入。"
)
ATTACH_IMAGE_EN = (
    "Image **{name}** received and kept in this conversation.\n\n"
    "The demo backend stores the preview only; once the vision model is wired up, "
    "MathGuide will read handwritten problems directly from photos. "
    "Meanwhile, type the problem text and I will solve it as usual."
)
ATTACH_FILE_EN = (
    "File **{name}** received (metadata only, {size} KB).\n\n"
    "Document parsing (PDF / lecture notes) arrives with the real file service."
)


def _is_chinese(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _strip_meta(prompt: str, cmd: str | None) -> str:
    """剥离前端可能遗留的 [cmd] 前缀,仅留原始问题"""
    text = re.sub(r"^\[[^\]]*\]\s*", "", prompt)
    if cmd and text.startswith(cmd):
        text = text[len(cmd):].lstrip(": ： ")
    return text.strip()


def _compose_direct(prompt: str, chunks: list[tuple[rag.Chunk, float]]) -> str:
    """知识库直答模式(未配置 LLM):把检索到的知识片段组装成回复文本"""
    zh = _is_chinese(prompt)
    level = judge_level(_strip_meta(prompt, None))
    if not chunks:
        return FALLBACK_ZH.format(level=LEVEL_ZH[level]) if zh else FALLBACK_EN.format(level=LEVEL_EN[level])
    parts = []
    if zh:
        parts.append(f"**难度判定:** {LEVEL_ZH[level]}。当前未配置 LLM,以下为知识库检索到的最相关资料:")
    else:
        parts.append(f"**Level:** {LEVEL_EN[level]}. (LLM not configured — showing the most relevant "
                     "knowledge-base entries, currently in Chinese.)")
    for i, (c, _score) in enumerate(chunks, 1):
        parts.append(f"\n\n**【资料{i}】** {c.title} · {c.section}\n\n{c.text}")
    return "".join(parts)


async def _frames(text: str):
    """按帧切片流式下发一段完整文本(JSON 字符串包裹,含 [DONE] 收尾)"""
    i = 0
    while i < len(text):
        yield f"data: {json.dumps(text[i:i + CHUNK], ensure_ascii=False)}\n\n"
        i += CHUNK
        await asyncio.sleep(FRAME_MS)
    yield "data: [DONE]\n\n"


def _stream_text(text: str) -> StreamingResponse:
    return StreamingResponse(
        _frames(text),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _gen_llm(prompt: str, cmd: str | None, chunks: list[tuple[rag.Chunk, float]]):
    """LLM 流式:模型增量原样转发;调用失败自动降级为直答,不让前端假死"""
    try:
        async for delta in rag.llm.stream_chat(rag.build_system(chunks, cmd), prompt):
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 模型侧错误不区分类型,统一降级
        print(f"[chat] LLM 调用失败,降级为知识库直答: {exc}")
        note = "⚠ 模型调用失败,以下为知识库直答内容:\n\n"
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        async for frame in _frames(_compose_direct(prompt, chunks)):
            yield frame
        return
    yield "data: [DONE]\n\n"


async def chat_stream(request: Request) -> StreamingResponse:
    require_auth(request)  # 401: {"detail": "unauthorized"}

    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    cmd = body.get("cmd")

    # 前端新会话会以空 prompt 触发欢迎问候
    if not prompt:
        return _stream_text(WELCOME_ZH)

    # 附件消息(前缀契约 [attach:image|file]文件名)
    m = re.match(r"^\[attach:(image|file)\](.+)$", prompt)
    if m:
        kind, name = m.group(1), m.group(2).strip()
        if _is_chinese(prompt):
            text = (ATTACH_IMAGE_ZH if kind == "image" else ATTACH_FILE_ZH).format(name=name, size="—")
        else:
            text = ATTACH_IMAGE_EN if kind == "image" else ATTACH_FILE_EN
        return _stream_text(text)

    # RAG:检索知识片段 → LLM 或直答
    question = _strip_meta(prompt, cmd)
    chunks = rag.search(question, top_k=3)
    if rag.llm.is_configured():
        return StreamingResponse(
            _gen_llm(question, cmd, chunks),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return _stream_text(_compose_direct(question, chunks))
