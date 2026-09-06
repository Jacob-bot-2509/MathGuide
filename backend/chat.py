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
import random
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


# 确切数学问题的措辞标记(与知识库触发词共同判定;命中才走答题框架)
_MATH_EXTRA_WORDS = (
    "求", "证明", "计算", "求解", "求导", "求证", "这道", "这题", "例题", "题目", "公式", "定理", "数学",
    "怎么做", "怎么算", "如何求", "如何证",
    "solve", "prove", "compute", "evaluate", "show that", "theorem", "equation", "problem", "math",
)


def _math_re() -> re.Pattern:
    """由知识库触发词 + 题目措辞组成数学问题识别正则(CJK 子串匹配,英文按词边界)。
    裸「求」加否定回溯,排除「请求/要求」这类日常用词。"""
    terms = set(rag.terms()) | set(_MATH_EXTRA_WORDS)
    zh = sorted((t for t in terms if not t.isascii()), key=len, reverse=True)
    en = sorted((t for t in terms if t.isascii() and len(t) >= 3), key=len, reverse=True)
    zh_parts = [re.escape(t) if t != "求" else r"(?<![请要])求" for t in zh]
    pattern = "|".join(zh_parts + [r"\b" + re.escape(t) + r"\b" for t in en])
    return re.compile(pattern, re.IGNORECASE)


# 会话大脑:同类多条随机轮换,避免机械重复;语气自然、有温度
CHITCHAT_SETS_ZH: dict[str, list[str]] = {
    "greet": [
        "你好呀!我是 MG。今天想一起攻克哪块数学?",
        "嗨!很高兴见到你~ 有数学问题尽管说,想闲聊也欢迎。",
        "你好你好!我在呢,随时可以开始。",
    ],
    "thanks": [
        "不客气!能帮上忙我就很开心。",
        "应该的!有新的问题随时回来。",
        "不用谢~ 一起把数学啃下来,就是对我最好的感谢。",
    ],
    "bye": [
        "再见!下次遇到数学问题,我随叫随到。",
        "拜拜~ 学累了就休息一下,咱们下次再战。",
        "好,下次见!祝你一切顺利。",
    ],
    "praise": [
        "谢谢夸奖!我继续加油,争取每次解答都让你满意。",
        "哈哈,被你夸得有点不好意思了。咱们继续?",
        "过奖啦,真正厉害的是坚持提问的你。",
    ],
    "intro": [
        "我是 MG,MathGuide 的高等数学学习助手。概念讲解、例题精讲、章节导航、错题归纳、公式查询,都是我的拿手活。",
        "我叫 MG,专攻高等数学的学习与科研辅助。你可以直接丢给我一道题,或者问我某个概念怎么理解。",
    ],
    "ability": [
        "我能帮你做这些:讲概念(带形象理解)、串章节知识、归纳错题、查公式,还能给难题搭解题框架。",
        "我的主战场是高等数学:概念讲解、例题精讲、错题归纳、公式查询,还能陪你梳理章节脉络。",
    ],
    "usage": [
        "直接在输入框提问就行,比如「什么是泰勒展开」;下面指令栏的按钮可以一键切到例题精讲、公式查询等模式。",
        "用法很简单:输入问题回车即可。想要例题点「例题精讲」,想查公式点「公式查询手册」。",
    ],
    "mood": [
        "听起来你有点低落?数学解不出来的挫败感我懂。要不先聊两句,或者换一道简单题找回手感?",
        "抱抱~ 学习压力大的时候,允许自己休息一下。想倾诉我听着,想做题我陪着。",
    ],
    "agree": [
        "好嘞!",
        "收到~",
        "嗯嗯,明白。",
    ],
    "generic": [
        "明白你的意思了~ 这个话题我可能不专业,但数学相关的问题我随叫随到。",
        "哈哈,记下了。闲聊我也挺喜欢的,不过别忘了,我是你身边最能打的数学搭子。",
        "收到!虽然我的主场是数学,但陪你聊聊天完全没问题。",
    ],
}
CHITCHAT_SETS_EN: dict[str, list[str]] = {
    "greet": [
        "Hi there! I'm MG, your advanced-math study buddy. What shall we tackle today?",
        "Hey! Great to see you. Got a math question, or just want to chat?",
        "Hello hello! I'm here — ready whenever you are.",
    ],
    "thanks": [
        "You're very welcome! Glad I could help.",
        "Anytime! Come back whenever a question pops up.",
        "No problem at all — tackling math together is the best thanks.",
    ],
    "bye": [
        "See you! I'll be here whenever a math problem shows up.",
        "Bye! Take a break when you need one — we'll pick it up next time.",
        "Until next time! Good luck with everything.",
    ],
    "praise": [
        "Thank you! I'll keep it up — aiming to make every answer satisfying.",
        "Haha, you're making me blush. Shall we keep going?",
        "You're too kind — the real credit goes to you for asking.",
    ],
    "intro": [
        "I'm MG, MathGuide's assistant for advanced mathematics: concept explanations, worked examples, chapter navigation, mistake reviews, and formula lookup.",
        "I'm MG — I help with learning and research in higher math. Send me a problem, or ask how to understand a concept.",
    ],
    "ability": [
        "Here's what I do: explain concepts with intuition, walk through chapters, review mistakes, look up formulas, and scaffold solutions for hard problems.",
        "My home turf is higher mathematics: concept explanations, worked examples, mistake reviews, formula lookup, and chapter navigation.",
    ],
    "usage": [
        "Just type your question and hit Enter — try \"what is Taylor expansion?\". The command bar below switches modes like worked examples or formula lookup.",
        "Easy: type a question and press Enter. For examples tap \"Worked Examples\", for formulas tap \"Formula Lookup\".",
    ],
    "mood": [
        "Sounds like you're feeling a bit down? I know how frustrating math can be. Want to talk, or maybe switch to an easier problem to get your confidence back?",
        "Hugs — it's okay to rest when studying gets heavy. I'm here to listen, or to work through problems if you prefer.",
    ],
    "agree": [
        "Sure thing!",
        "Got it.",
        "Okay, understood.",
    ],
    "generic": [
        "Got what you mean! This topic might be outside my specialty, but I'm always here for math.",
        "Haha, noted. I enjoy chatting too — but remember, I'm your toughest math buddy.",
        "Received! Math is my home turf, but chatting with you is always welcome.",
    ],
}


def _chitchat_kind(text: str) -> str | None:
    """识别会话类型(寒暄/感谢/告别/夸奖/自我介绍/能力/用法/情绪/应和);未识别返回 None"""
    t = text.lower().strip()
    if re.search(r"^(喂|你好|您好|嗨|哈喽|在吗|在不在)|(hi|hello|hey|hiya|how are you)\b", t):
        return "greet"
    if re.search(r"谢谢|感谢|thanks|thank you|thx", t):
        return "thanks"
    if re.search(r"再见|拜拜|byebye|bye", t):
        return "bye"
    if re.search(r"厉害|真棒|太强了|牛逼|牛啊|不错嘛|干得漂亮|great|awesome|amazing|well done", t):
        return "praise"
    if re.search(r"你是谁|你叫什么|介绍一下你|自我介绍|what are you|who are you|about yourself", t):
        return "intro"
    if re.search(r"你会什么|能做什么|有什么功能|功能|what can you do", t):
        return "ability"
    if re.search(r"怎么用|如何使用|使用说明|帮助|help", t):
        return "usage"
    if re.search(r"难过|烦|焦虑|心情|压力|学不会|太难了|不想学|崩溃|tired|stressed|anxious|sad", t):
        return "mood"
    if re.fullmatch(r"(好的|好|嗯|哦|行|可以|ok|okay|fine|yes|no)", t):
        return "agree"
    return None


def _conversational_reply(text: str, zh: bool, kind: str | None) -> str:
    """会话应答:同类多条随机轮换,语气自然"""
    sets = CHITCHAT_SETS_ZH if zh else CHITCHAT_SETS_EN
    return random.choice(sets[kind or "generic"])


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
        system = rag.build_system(chunks, cmd, zh=_is_chinese(prompt))
        async for delta in rag.llm.stream_chat(system, prompt):
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
    zh = _is_chinese(question)
    chunks = rag.search(question, top_k=3)

    if rag.llm.is_configured():
        return StreamingResponse(
            _gen_llm(question, cmd, chunks),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    # 直答模式:
    # ① 检索到相关知识 → 知识直答(专业问询专业回答);
    # ② 未命中但检测为确切数学题(触发词/题目措辞)→ 方法论框架(含难度判定);
    # ③ 其余(寒暄/感谢/告别/夸奖/介绍/情绪/应和/一般对话)→ 像人一样对话,不检索、不判难度
    if chunks:
        return _stream_text(_compose_direct(question, chunks))
    if _math_re().search(question):
        level = judge_level(question)
        return _stream_text(FALLBACK_ZH.format(level=LEVEL_ZH[level]) if zh
                           else FALLBACK_EN.format(level=LEVEL_EN[level]))
    return _stream_text(_conversational_reply(question, zh, _chitchat_kind(question)))
