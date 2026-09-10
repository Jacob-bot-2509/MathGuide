"""
聊天路由:POST /api/chat/stream(需 Bearer token)。

契约(与 frontend/src/api/types.ts ChatRequest 对齐):
请求体 { prompt: string, cmd?: string, sessionId?: number,
        categoryKey?: string, history?: [], sources?: string[] }
categoryKey 是前端板块预判,后端不消费(四路裁决见 rag/route.py),仅作契约预留;
sources 是研究型提问的检索范围(平台名白名单在 rag/research)。

响应为 OpenAI 兼容 SSE,每帧 payload 为 JSON 字符串(正文换行经转义,
帧内无裸换行,data 行不会因正文被拆碎而丢字):
    data: "文本增量"
    ...
    data: [DONE]
前端 postSSE 逐行解析,JSON 解析失败回退纯文本,遇 [DONE] 结束。

回复链路(顺序即优先级,裁决口径见 rag/route.py):
- 空 prompt → 欢迎语;附件前缀 → 接收回执 / 交长文模型阅读;
- 章节导航指令 → 划分章节列表 / 输出该章指引;
- 研究型提问 → 跨论文库深度搜索 → LLM 综合 + 后端拼装引用区;
- 其余 → 检索知识片段 → 有 LLM 则组装 system prompt 流式输出,
  未配置 LLM 则知识库直答,知识库未命中再按「数学题 / 闲聊」分流。
"""
import asyncio
import json
import random
import re
import time

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

import rag
import usage
from auth import require_auth

CHUNK = 6          # 直答模式每帧字符数(配合浏览器端 ~24ms 渲染节流)
FRAME_MS = 0.02    # 帧间隔(秒),模拟真实模型逐字输出

WELCOME_ZH = (
    "**欢迎回到 MATHGUIDE · 学习辅助**\n\n"
    "我是 MG,你的高等数学学习与研究助手。直接提问即可,或用下方指令:"
    "概念动画演示 / 章节知识导航 / 问题记录 / 公式查询手册 / 搜索范围。\n\n"
    "问题的**板块我会自动识别**,先给严谨的专业表述,再给形象化理解,并带上公式推演;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Learn. You can also ask in English, e.g. \"explain limits with intuition\".)"
)

FALLBACK_ZH = (
    "这个问题我按通用方法论给你搭分析框架。\n\n"
    "**通用三步走(专业表述):** ① 明确对象与条件,把问题转化为标准型(极限式、方程、积分、模型);"
    "② 选择对应工具求解;③ **回代验算**——MG 的「自我验证工作流」会在解答发布前进行一致性检查与符号复验,"
    "低置信度时会主动标注「该解答需进行人工处理」。\n\n"
    "**形象理解:** 解数学题像侦探破案:先锁定案件类型,再盘点物证(条件),"
    "最后用匹配的手法收网;每一步结论都要经得起「代入原题」这关审讯。\n\n"
    "把题目原文(或拍照上传)发给我,我会按上面的框架给出带完整过程的解答。"
)

FALLBACK_EN = (
    "Here is a general framework I can apply to this problem.\n\n"
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
    "文本/PDF 教材已读取正文,可执行「章节知识导航」一键划分章节;"
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


# 数学题判定(知识库触发词 + 题目措辞)统一在 rag.is_math_question:
# 正则编译一次缓存复用,评测工具与线上链路同源

# 深答路由触发词:证明 / 竞赛类问题交给 deep 强模型(未配置自动回退 main)
_DEEP_MARKERS = ("证明", "求证", "竞赛", "奥数", "难题", "prove", "proof", "olympiad")


def _pick_role(question: str) -> str:
    """按需路由 LLM 角色:证明/竞赛 → deep,其余 main(节省成本,好钢用在刀刃上)"""
    q = question.lower()
    role = rag.llm.pick("deep") if any(m in q for m in _DEEP_MARKERS) else "main"
    print(f"[chat] 角色路由 {role} | {question[:20]}")
    return role


# 教材缓存:章节导航列表生成时按会话暂存教材文本,后续章节指引按 sessionId 取用,
# 点击章节只发章节名即可(服务重启缓存失效,指引自动降级为通用知识作答)
_TEXTBOOKS: dict[int, str] = {}
_TEXTBOOK_MAX = 16
_TEXTBOOK_CAP = 30000  # 长文档教材上限(与前端 FILE_TEXT_MAX 一致,走 long 角色)


def _cache_textbook(session_id: object, text: str) -> None:
    if not isinstance(session_id, int) or not session_id or len(text) < 80:
        return
    _TEXTBOOKS[session_id] = text[:_TEXTBOOK_CAP]
    if len(_TEXTBOOKS) > _TEXTBOOK_MAX:
        _TEXTBOOKS.pop(next(iter(_TEXTBOOKS)))


def _get_textbook(session_id: object) -> str:
    return _TEXTBOOKS.get(session_id) if isinstance(session_id, int) else ""


# 会话大脑:同类多条随机轮换,避免机械重复;语气自然、有温度
CHITCHAT_SETS_ZH: dict[str, list[str]] = {
    "greet": [
        "你好呀!我是 MG。今天想一起攻克哪块数学?",
        "嗨!很高兴见到你~ 我是 MG,有数学问题尽管说,想闲聊也欢迎。",
        "你好你好!MG 在呢,随时可以开始。",
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
        "我是 MG,MathGuide 的高等数学学习助手。概念讲解、章节导航、问题记录、公式查询,都是我的拿手活。",
        "我叫 MG,专攻高等数学的学习与科研辅助。你可以直接丢给我一道题,或者问我某个概念怎么理解。",
    ],
    "ability": [
        "我能帮你做这些:讲概念(带形象理解)、串章节知识、归纳错题、查公式,还能给难题搭解题框架。",
        "我的主战场是高等数学:概念讲解、问题记录、公式查询,还能陪你梳理章节脉络。",
    ],
    "usage": [
        "直接在输入框提问就行,比如「什么是泰勒展开」;下面指令栏的按钮可以一键切到章节导航、公式查询等模式。",
        "用法很简单:输入问题回车即可。想回顾收纳过的题目点「问题记录」,想查公式点「公式查询手册」。",
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
    if not chunks:
        return FALLBACK_ZH if zh else FALLBACK_EN
    parts = []
    if zh:
        parts.append("以下为知识库检索到的最相关资料:")
    else:
        parts.append("Here are the most relevant entries from the knowledge base "
                     "(currently in Chinese):")
    for i, (c, _score) in enumerate(chunks, 1):
        # 英文提问用英文标题(正文仍为中文资料时,标题至少可读)
        title = c.title_en if not zh else c.title
        parts.append(f"\n\n**【资料{i}】** {title} · {c.section}\n\n{c.text}")
    return "".join(parts)


def _validated_history(raw: object) -> list[dict]:
    """校验并截断前端传来的历史消息(条数/长度双保险,异常值直接丢弃)。
    上限 16 条:超出部分由滚动摘要压缩(_update_summary),早期上下文不丢失"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:16]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        out.append({"role": role, "content": content.strip()[:400]})
    return out


# 会话滚动摘要:每 8 次请求压缩一次旧对话(便宜模型,失败静默),长对话保持早期上下文
_SUMMARIES: dict[int, str] = {}
_SUM_TICK: dict[int, int] = {}


async def _update_summary(sid: int, old_turns: list[dict], prev: str) -> None:
    system = (
        "你是对话摘要助手。把以下更早的对话压缩成简短摘要(要点式,200 字内),"
        "保留数学概念、未解决问题与用户偏好。只输出摘要本身。"
    )
    base = f"{prev}\n\n" if prev else ""
    user = base + "\n".join(
        f"{'用户' if t['role'] == 'user' else 'MG'}: {t['content']}" for t in old_turns)
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, user, role="main", fallback=False):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 400:
                break
    except Exception:  # noqa: BLE001 摘要失败静默跳过,不影响主回答
        return
    text = "".join(parts).strip()
    if text:
        _SUMMARIES[sid] = text
        print(f"[chat] 会话 {sid} 摘要已更新({len(text)} 字)")


def _research_reply(outcome: rag.research.SearchOutcome, zh: bool) -> str:
    """研究型回复的降级形态(未配置 LLM 或综合失败时用):按相关度列出高置信来源
    (标题/作者/年份/摘要/链接),来源统计与失败源如实呈现。
    正常链路是 _gen_research 的「综合解答 + 引用」,本函数只作兜底"""
    if not outcome.any_hit:
        if zh:
            why = f"(本次不可达:{'、'.join(outcome.errors)})" if outcome.errors else "(网络或限额)"
            return (f"跨论文库检索暂未找到高置信来源{why},建议稍后再试,"
                    "或把问题描述得更具体一些。")
        why = f" (unreachable: {', '.join(outcome.errors)})" if outcome.errors else " (network or rate limits)"
        return (f"No high-confidence sources found right now{why}. "
                "Try again later or rephrase the question more specifically.")

    # 统计口径必须与下方列表一致:outcome.sources 是各源"抓到的候选数",
    # 这里的 hits 是去重排序后"真正入选的条数",混用会出现「3 条(arXiv 8 · ...)」这种自相矛盾
    picked: dict[str, int] = {}
    for h in outcome.hits:
        picked[h.source] = picked.get(h.source, 0) + 1
    stats = " · ".join(f"{name} {n}" for name, n in picked.items())
    lines = [f"已检索到 {len(outcome.hits)} 条高置信来源({stats}),按相关度排序:"] if zh else \
        [f"Found {len(outcome.hits)} relevant sources ({stats}), ranked by relevance:"]
    for i, h in enumerate(outcome.hits, 1):
        meta = []
        if h.authors:
            meta.append(h.authors)
        if h.year:
            meta.append(str(h.year))
        meta.append(h.source)
        lines.append(f"\n**{i}. {h.title}** — {' · '.join(meta)}(相关度 {h.score:.1f})")
        if h.snippet:
            lines.append(f"{h.snippet[:260]}")
        lines.append(f"🔗 {h.url}" if h.url else "📚 来源:本地知识库")
    if outcome.errors:
        lines.append(f"\n(注:以下来源本次不可达已跳过:{'、'.join(outcome.errors)})")
    return "\n".join(lines)


# 研究型综合结果缓存:同问题 TTL 内直接回放已综合全文(跳过搜索与 LLM,省时省钱)
_RESEARCH_ANSWER: dict[str, tuple[float, str]] = {}
_RESEARCH_TTL = 600.0   # 秒
_RESEARCH_MAX = 32


def _clean_scope(raw: object) -> list[str] | None:
    """请求体里的搜索范围(平台名列表)→ 干净的字符串列表;None/空/非列表 = 全平台"""
    if not isinstance(raw, list):
        return None
    out = [str(s)[:30] for s in raw][:12]
    return [s for s in out if s] or None


def _research_cache_key(question: str, scope: list[str] | None = None) -> str:
    """范围参与缓存键:同一问题换了检索平台必须重新检索"""
    tag = "all" if not scope else ",".join(sorted(scope))
    return f"{tag}|{question.strip().lower()}"


# ---------- 安全与用量(测试期防护) ----------

PROMPT_MAX = 32000  # 服务端输入上限(字符):覆盖长文档教材(3万字)+ 指令前缀,超出静默截断

# 限流:每用户滑动窗口(防脚本刷接口烧 token 费;正常学习节奏碰不到上限)
_RATE_LIMIT_MAX = 6
_RATE_WINDOW = 60.0
_rate_log: dict[str, list[float]] = {}


def _rate_check(uid: str) -> None:
    now = time.monotonic()
    hits = [t for t in _rate_log.get(uid, []) if now - t < _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT_MAX:
        raise HTTPException(429, "rate limited")
    hits.append(now)
    _rate_log[uid] = hits


def _meter(resp: StreamingResponse, rec: dict, prompt_len: int, cmd: str,
           meta: dict) -> StreamingResponse:
    """用量电表:统计回复字数并落盘 usage.json(流结束才记账,客户端中途断开不记)。
    注意:必须先捕获原迭代器再替换 body_iterator,否则新生成器会自引用死锁"""
    original = resp.body_iterator

    async def counted():
        chars = 0
        async for frame in original:
            chars += len(frame) if isinstance(frame, str) else len(frame.decode("utf-8", "ignore"))
            yield frame
        _record(rec, cmd=cmd, prompt_len=prompt_len, reply_len=chars,
                role=meta["role"], research=meta["research"])

    resp.body_iterator = counted()
    return resp


def _record(rec: dict, *, cmd: str, prompt_len: int, reply_len: int,
            role: str, research: bool) -> None:
    """用量记账统一入口(聊天链路与语音转写共用,字段口径不会各写各的)"""
    usage.record(
        user=str(rec.get("nickname") or rec.get("uid") or "访客"),
        phone=str(rec.get("phone") or ""),
        cmd=cmd,
        prompt_len=prompt_len,
        reply_len=reply_len,
        role=role,
        research=research,
        ts=time.time(),
    )


async def _gen_research(question: str, outcome: rag.research.SearchOutcome, zh: bool,
                        ck: str | None = None):
    """研究型 LLM 综合:正文流式 + 引用区(后端拼装,不经过模型);
    模型失败自动降级为来源列表;ck 非空时全文入库缓存供重复问题秒回"""
    full: list[str] = []
    try:
        async for delta in rag.research.synthesize.synthesize_stream(
                question, outcome.hits, zh, role=rag.llm.pick("deep")):
            full.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 研究综合失败,降级为来源列表: {exc}")
        async for frame in _frames(_research_reply(outcome, zh)):
            yield frame
        return
    citations = rag.research.synthesize.citations_block(outcome.hits, zh)
    full.append(citations)
    async for frame in _frames(citations, pace=False):
        yield frame
    if ck:
        _RESEARCH_ANSWER[ck] = (time.monotonic(), "".join(full))
        if len(_RESEARCH_ANSWER) > _RESEARCH_MAX:
            _RESEARCH_ANSWER.pop(next(iter(_RESEARCH_ANSWER)))


async def _frames(text: str, pace: bool = True):
    """按帧切片流式下发一段完整文本(JSON 字符串包裹,含 [DONE] 收尾);
    pace=False 用于引用区等附属内容:不做人工逐字拟态,即时下发"""
    i = 0
    while i < len(text):
        yield f"data: {json.dumps(text[i:i + CHUNK], ensure_ascii=False)}\n\n"
        i += CHUNK
        if pace:
            await asyncio.sleep(FRAME_MS)
    yield "data: [DONE]\n\n"


def _sse(gen) -> StreamingResponse:
    """SSE 响应统一构造:媒体类型与反缓冲头只写一处
    (散在五处时,漏一个头就会被中间代理缓冲,流式变一次性吐出)"""
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stream_text(text: str) -> StreamingResponse:
    return _sse(_frames(text))


async def _verify_answer(question: str, answer: str, role: str) -> str | None:
    """双角色验证:解答生成后用另一角色复核,返回一句复核结论(失败返回 None,不打断主回答)"""
    system = (
        "你是数学解答复核员。请核查用户问题与给出的解答:判断结论是否正确"
        "(结论:正确 / 有误 / 需人工复核),并用一句话说明依据。"
        "不要重算过程,不要输出除结论和一句话依据以外的任何内容。"
    )
    user = f"问题:{question[:300]}\n\n解答:\n{answer[:1500]}"
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, user, role=role):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 300:
                break
    except Exception:  # noqa: BLE001 复核失败静默跳过,不影响主回答
        return None
    text = "".join(parts).strip()
    return text[:200] or None


async def _gen_llm(prompt: str, cmd: str | None, chunks: list[tuple[rag.Chunk, float]],
                   history: list[dict] | None = None, role: str = "main", verify: bool = False,
                   summary: str = "", sid: int | None = None):
    """LLM 流式:模型增量原样转发(带多轮历史);调用失败自动降级为直答,不让前端假死。
    verify=True 时解答完成后用另一角色复核,结论追加在末尾(复核失败静默跳过);
    summary 为更早对话的滚动摘要(附在 system 中),回答结束后异步推进摘要(每 8 轮一次)"""
    try:
        system = rag.build_system(chunks, cmd, zh=_is_chinese(prompt))
        if summary:
            system += f"\n\n【更早对话摘要】\n{summary}"
        answer: list[str] = []
        async for delta in rag.llm.stream_chat(system, prompt, history=history, role=role):
            answer.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
        if verify:
            # 解答者与复核者错开模型保证独立:deep 解答 → main 复核;main 解答 → deep 复核
            vrole = "main" if role == "deep" else rag.llm.pick("deep")
            verdict = await _verify_answer(prompt, "".join(answer), vrole)
            if verdict:
                print(f"[chat] 复核({vrole}): {verdict[:60]}")
                yield f"data: {json.dumps(f'\n\n> 🔍 复核({vrole}): {verdict}', ensure_ascii=False)}\n\n"
            # 解答完询问是否收录进问题记录(归纳本):前端渲染为「是/否」按钮
            nb = ("\n\n[是](cmd://nb/yes) [否](cmd://nb/no)" if _is_chinese(prompt)
                  else "\n\n[Yes](cmd://nb/yes) [No](cmd://nb/no)")
            yield f"data: {json.dumps(nb, ensure_ascii=False)}\n\n"
        if sid is not None and history and len(history) >= 16:
            # 每 8 次请求异步压缩一次更早的对话(不阻塞本次响应;失败静默)
            tick = _SUM_TICK.get(sid, 0) + 1
            _SUM_TICK[sid] = tick
            if tick % 8 == 0:
                asyncio.create_task(_update_summary(sid, history[:-8], _SUMMARIES.get(sid, "")))
    except Exception as exc:  # noqa: BLE001 模型侧错误不区分类型,统一降级
        print(f"[chat] LLM 调用失败,降级为知识库直答: {exc}")
        note = "⚠ 模型调用失败,以下为知识库直答内容:\n\n"
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        async for frame in _frames(_compose_direct(prompt, chunks)):
            yield frame
        return
    yield "data: [DONE]\n\n"


# 章节链接契约:[章节名](cmd://chapter/<名称>) —— 前端 MathText 渲染为可点击章节;
# 「返回」按钮 [返回](cmd://back) 由后端拼装(不经过模型,防止格式漂移)
def _nav_system():
    return (
        "你是教材章节导航助手。用户上传了一本教材,教材内容已随提问给出。"
        "请只输出该教材的章节划分列表:每一章单独一行,格式严格为 "
        "[第N章 章节名](cmd://chapter/第N章章节名),链接地址内不要含空格、括号或标点。"
        "不要展示任何章节内容,不要解释,不要输出列表以外的任何文字。"
        "若文本不像一本教材,按其内容结构推断章节并同样只输出章节列表。"
    )


def _nav_guide_system():
    return (
        "你是教材章节导航助手。教材内容与用户点击的章节已随提问给出。"
        "请针对该章节输出大概知识指引:该章学什么(核心概念)、重点与难点、"
        "与前后章节的联系、学习建议。条目式回答,与用户提问同语言,控制在 150 字以内。"
    )


async def _gen_nav_list(question: str):
    """章节导航:只输出教材章节划分列表(不展示内容);失败时给出明确提示"""
    try:
        async for delta in rag.llm.stream_chat(_nav_system(), question[:_TEXTBOOK_CAP], role=rag.llm.pick("long")):
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 章节导航调用失败: {exc}")
        yield f"data: {json.dumps('⚠ 章节导航调用失败,请稍后重试。', ensure_ascii=False)}\n\n"
        return
    yield "data: [DONE]\n\n"


async def _gen_nav_guide(question: str, tb: str = ""):
    """章节指引:用户点击章节后给出该章大概知识指引,末尾附「返回」按钮行;
    tb 为按会话缓存的教材文本,缓存失效时按通用知识作答该章"""
    prompt = question[:2000]
    if tb:
        prompt += f"\n\n<教材文本>:\n{tb}"
    else:
        prompt += "\n\n(教材内容缓存已失效,请按通用知识作答该章)"
    try:
        async for delta in rag.llm.stream_chat(_nav_guide_system(), prompt, role=rag.llm.pick("long")):
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 章节指引调用失败: {exc}")
        yield f"data: {json.dumps('⚠ 章节指引调用失败,请稍后重试。', ensure_ascii=False)}\n\n"
        return
    yield f"data: {json.dumps('\n\n[返回](cmd://back)', ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _gen_attach_llm(name: str, body: str, zh: bool):
    """粘贴导入的文本文件:正文交 LLM 阅读理解,概括主题并引导提问;失败降级为接收回执"""
    system = (
        "用户通过复制粘贴导入了一个文本文件「{name}」。请阅读内容后简短回应:"
        "先用一两句话概括文件主题,再告诉用户可以针对内容提问(如总结、讲解、翻译)。"
        "不要搜索外部资料,不要编造文件里没有的内容;用与文件内容相同的语言回应。"
    ).format(name=name)
    try:
        async for delta in rag.llm.stream_chat(system, body[:_TEXTBOOK_CAP], role=rag.llm.pick("long")):
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 模型侧错误统一降级,不让前端假死
        print(f"[chat] 粘贴文本 LLM 调用失败,降级为接收回执: {exc}")
        note = (ATTACH_FILE_ZH if zh else ATTACH_FILE_EN).format(name=name, size="—")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        return
    yield "data: [DONE]\n\n"


async def chat_stream(request: Request) -> StreamingResponse | JSONResponse:
    """聊天入口(安全外壳):认证 → 输入上限 → 限流 → 路由 → 用量记账"""
    rec = require_auth(request)  # 401: {"detail": "unauthorized"}

    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    cmd = str(body.get("cmd", ""))[:50] if body.get("cmd") else None

    # 服务端输入上限:前端限制之外的最后保险(超出静默截断,防误传大文本烧 token 费)
    if len(prompt) > PROMPT_MAX:
        prompt = prompt[:PROMPT_MAX]

    # 限流:每用户滑动窗口,仅对非空提问计次(新会话问候不占用额度)
    if prompt:
        _rate_check(str(rec.get("uid") or rec.get("phone") or ""))

    meta = {"role": "main", "research": False}
    resp = await _route_chat(prompt, cmd, body, rec, meta)
    if not isinstance(resp, StreamingResponse):
        return resp
    return _meter(resp, rec, len(prompt), cmd or "", meta)


async def speech_to_math(request: Request) -> StreamingResponse:
    """语音识别文本 → 数学符号转写(SSE 流式:首帧即上屏,前端逐帧替换输入框,
    不用等模型收尾,感知延迟 ≈ 首 token 时间)。
    失败时回放原文帧,绝不阻断语音输入;计入限流与用量统计"""
    rec = require_auth(request)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:6000]
    if not text:
        return _stream_text("")
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))

    system = (
        "你是数学语音转写助手。把用户语音识别出的口语数学文本转写为规范数学表达式:"
        "能用 Unicode 数学符号(如 ² ³ ⁿ √ ∫ π → ∞ ≤ ≥ × ÷ ≈)就直接用,"
        "复杂结构用简洁 LaTeX(如 x_0、\\frac{b}{a}、\\sum_{i=1}^{n});"
        "文本中已是大写的字母是用户指定的,必须保留大写;"
        "小写字母按数学惯例自动判断:逆/转置/行列式/迹/秩/张量积/直和的对象按矩阵用大写(A、B、M),"
        "期望/方差/分布的对象按随机变量用大写(X、Y),其余参数与函数名保持小写(f、g、x、y);"
        "输出尽量使用 Unicode 上标/下标(如 x²、Aᵀ、A⁻¹、x₀),"
        "仅在没有对应 Unicode 形式时才用 ^/_ 或 LaTeX 记号;"
        "只输出转写结果,不要解释、不要补充。若文本不含数学内容,原样返回。"
    )

    async def gen():
        parts: list[str] = []
        try:
            async for delta in rag.llm.stream_chat(system, text, role="main", fallback=True,
                                                   max_tokens=400):
                parts.append(delta)
                yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
        except Exception:  # noqa: BLE001 转写失败回放原文,不阻断输入
            yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
            return
        _record(rec, cmd="语音转写", prompt_len=len(text),
                reply_len=sum(len(p) for p in parts), role="main", research=False)
        yield "data: [DONE]\n\n"

    return _sse(gen())


async def _route_chat(prompt: str, cmd: str | None, body: dict, rec: dict, meta: dict):
    """业务路由(与安全外壳分离):欢迎语 / 附件 / 章节导航 / 研究 / LLM / 直答"""

    # 前端新会话会以空 prompt 触发欢迎问候
    if not prompt:
        return _stream_text(WELCOME_ZH)

    # 附件消息(前缀契约 [attach:image|file]文件名;粘贴导入的文本文件带正文:
    # [attach:file]名\n\n内容 —— 正文交给 LLM 阅读理解,旧格式仍走接收回执)
    m = re.match(r"^\[attach:(image|file)\]([^\n]+)(?:\n\n([\s\S]+))?$", prompt)
    if m:
        kind, name, body = m.group(1), m.group(2).strip(), (m.group(3) or "").strip()
        if body and rag.llm.is_configured():
            meta["role"] = "long"
            return _sse(_gen_attach_llm(name, body, zh=_is_chinese(prompt)))
        if _is_chinese(prompt):
            text = (ATTACH_IMAGE_ZH if kind == "image" else ATTACH_FILE_ZH).format(name=name, size="—")
        else:
            text = (ATTACH_IMAGE_EN if kind == "image" else ATTACH_FILE_EN).format(name=name, size="—")
        return _stream_text(text)

    # RAG:检索知识片段 → 路由 → LLM 或直答
    question = _strip_meta(prompt, cmd)
    zh = _is_chinese(question)

    # 章节导航(教材正文随提示词携带):不检索知识库、不走研究路由
    if cmd in ("章节知识导航", "章节知识指引"):
        if not rag.llm.is_configured():
            return _stream_text("章节导航需要已配置 LLM,当前未配置。")
        if cmd == "章节知识导航":
            _cache_textbook(body.get("sessionId"), question)  # 教材入库,后续点击只发章节名
            gen = _gen_nav_list(question)
        else:
            gen = _gen_nav_guide(question, tb=_get_textbook(body.get("sessionId")))
        meta["role"] = "long"
        return _sse(gen)

    # P0/P1 路由:研究型提问优先于知识直答
    # (「泰勒展开的最新研究进展」虽命中知识库,意图是查文献 → 走跨论文库深度搜索)
    # 必须先判意图、后检索:深度搜索内部自会检索知识库,
    # 这里若先检一遍,研究型提问就要白付一份 embedding 开销(结果还被丢掉)
    if rag.route.is_research_intent(question):
        meta["research"] = True
        # 搜索范围(前端勾选的平台;缺省/空 = 全平台);非法名白名单校验在 deep_search 内
        scope = _clean_scope(body.get("sources"))
        ck = _research_cache_key(question, scope)
        cached = _RESEARCH_ANSWER.get(ck)
        if cached and time.monotonic() - cached[0] < _RESEARCH_TTL:
            print(f"[chat] 研究综合缓存命中: {question[:24]}")
            meta["role"] = "deep"
            return _stream_text(cached[1])
        outcome = await rag.research.deep_search(question, top_k=3, scope=scope)
        # P2c:LLM 已配置 → 综合解答 + 编号引用 + 后端拼装引用区;
        # 未配置 → 来源列表(现有行为)
        if outcome.any_hit and rag.llm.is_configured():
            meta["role"] = "deep"
            return _sse(_gen_research(question, outcome, zh, ck=ck))
        return _stream_text(_research_reply(outcome, zh))

    # 检索含 embedding 请求(同步、冷启动可达数十秒)→ 线程池执行,
    # 不阻塞事件循环(否则这段等待会冻住所有并发会话)
    chunks = await asyncio.to_thread(rag.search, question, 3)

    if rag.llm.is_configured():
        # 双角色验证仅对数学题(命中知识库或题目措辞)开启;闲聊不浪费复核调用
        verify = bool(chunks) or rag.is_math_question(question)
        role = _pick_role(question)
        meta["role"] = role
        sid = body.get("sessionId")
        history = _validated_history(body.get("history"))
        summary = _SUMMARIES.get(sid, "") if isinstance(sid, int) else ""
        return _sse(_gen_llm(question, cmd, chunks, history=history, role=role, verify=verify,
                             summary=summary, sid=sid if isinstance(sid, int) else None))
    # 直答模式:
    # ① 检索到相关知识 → 知识直答(专业问询专业回答);
    # ② 未命中但检测为确切数学题(触发词/题目措辞)→ 方法论框架;
    # ③ 其余(寒暄/感谢/告别/夸奖/介绍/情绪/应和/一般对话)→ 像人一样对话,不检索
    # 裁决口径与 rag.route.decide 一致(评测工具跑的就是这条链)
    if chunks:
        return _stream_text(_compose_direct(question, chunks))
    if rag.is_math_question(question):
        return _stream_text(FALLBACK_ZH if zh else FALLBACK_EN)
    return _stream_text(_conversational_reply(question, zh, _chitchat_kind(question)))
