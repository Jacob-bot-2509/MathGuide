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
- 公式手册第一步(澄清标记)→ 只询问想查哪个具体知识点,不检索、不收纳(澄清提问带独立复核);
- 研究型提问 → 跨论文库深度搜索 → LLM 综合 + 后端拼装引用区;
- 其余 → 检索知识片段 → 有 LLM 则组装 system prompt 流式输出,
  未配置 LLM 则知识库直答,知识库未命中再按「数学题 / 闲聊」分流。
"""
import asyncio
import json
import random
import re
import time
from collections import OrderedDict

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

import config
import rag
import research_corpus
import research_tables
import usage
from auth import require_auth
from http_utils import read_json_object
from rag.research.types import SearchHit
from rate_limit import SlidingWindowLimiter
from session_cache import (
    TEXTBOOK_CAP,
    bump_tick,
    cache_textbook,
    get_summary,
    get_textbook,
    set_summary,
    valid_session_id,
    valid_workspace,
)

CHUNK = 6          # 直答模式每帧字符数(配合浏览器端 ~24ms 渲染节流)
FRAME_MS = 0.02    # 帧间隔(秒),模拟真实模型逐字输出
_DONE = "data: [DONE]\n\n"  # SSE 收尾标记(由 _sse 统一补,生成器不再各自 yield)

WELCOME_ZH = (
    "**欢迎回到 MATHGUIDE · 学习辅助**\n\n"
    "我是 MG,你的高等数学学习与研究助手。直接提问即可,或用下方指令:"
    "概念动画演示 / 章节知识导航 / 问题记录 / 公式查询手册 / 待办清单。\n\n"
    "问题的**板块我会自动识别**,先给严谨的专业表述,再给形象化理解,并带上公式推演;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Learn. You can also ask in English, e.g. \"explain limits with intuition\".)"
)

WELCOME_RESEARCH_ZH = (
    "**欢迎回到 MATHGUIDE · 科学研究**\n\n"
    "我是 MG,你的科研工作区助手。本区会话、研究档案与检索范围与学习辅助完全独立,"
    "可直接提问,或用下方指令:研究档案 / 搜索范围 / 待办清单。\n\n"
    "提出研究型问题时,我会按选定的**搜索范围**跨文献库检索,并给出带编号引用的综合解答;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Research. This workspace is isolated from Learn; ask in English if you prefer.)"
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
    print(f"[chat] 角色路由 {role} | 问题长度 {len(question)}")
    return role


# 教材缓存:章节导航列表生成时按「用户 + 会话」暂存教材文本,后续章节指引按
# (uid, sessionId) 取用,点击章节只发章节名即可(服务重启缓存失效,指引自动降级为通用知识作答)。
# 键必须带 uid:sessionId 是客户端自增的小整数,跨用户必然撞号(见 session_cache)。


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


# 会话滚动摘要:每 8 次请求压缩一次旧对话(便宜模型,失败静默),长对话保持早期上下文。
# 与教材缓存一样按 (uid, workspace, sid) 隔离,避免客户端自增的 sessionId 跨用户/跨区撞号。
async def _update_summary(uid: str, sid: int, old_turns: list[dict], prev: str,
                          workspace: str = "learn") -> None:
    system = (
        "你是对话摘要助手。把以下更早的对话压缩成简短摘要(要点式,200 字内),"
        "保留数学概念、未解决问题与用户偏好。只输出摘要本身。"
    )
    base = f"{prev}\n\n" if prev else ""
    user = base + "\n".join(
        f"{'用户' if t['role'] == 'user' else 'MG'}: {t['content']}" for t in old_turns)
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, user, role="main", fallback=False,
                                               thinking=False):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 400:
                break
    except Exception:  # noqa: BLE001 摘要失败静默跳过,不影响主回答
        return
    text = "".join(parts).strip()
    if text:
        set_summary(uid, sid, text, workspace=workspace)
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
_RESEARCH_ANSWER: OrderedDict[str, tuple[float, str]] = OrderedDict()
_RESEARCH_TTL = 600.0   # 秒
_RESEARCH_MAX = 32


def _clean_scope(raw: object) -> list[str] | None:
    """请求体里的搜索范围(平台名列表)→ 干净的字符串列表;None/空/非列表 = 全平台"""
    if not isinstance(raw, list):
        return None
    out = [str(s)[:30] for s in raw][:12]
    return [s for s in out if s] or None


def _research_cache_key(question: str, scope: list[str] | None = None,
                        uid: str = "") -> str:
    """范围与用户参与缓存键:同一问题换了检索平台、或换了人的论文库,
    必须重新检索/综合。用户语料是私有的,不能复用别人的答案。"""
    tag = "all" if not scope else ",".join(sorted(scope))
    return f"{uid}|{tag}|{question.strip().lower()}"


# ---------- 安全与用量(测试期防护) ----------

PROMPT_MAX = 32000  # 服务端输入上限(字符):覆盖长文档教材(3万字)+ 指令前缀,超出静默截断

# 限流:每用户滑动窗口(防脚本刷接口烧 token 费;正常学习节奏碰不到上限)。
# 公共实现会清理不活跃 key,游客登录不断产生新 uid 也不会让内存无界增长。
_RATE_LIMIT_MAX = 6
_RATE_WINDOW = 60.0
_rate_limiter = SlidingWindowLimiter(_RATE_LIMIT_MAX, _RATE_WINDOW)


def _rate_check(uid: str) -> None:
    if not _rate_limiter.allow(uid or "anonymous"):
        raise HTTPException(429, "rate limited")


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


def _meter(resp: StreamingResponse, rec: dict, prompt_len: int, cmd: str,
           meta: dict) -> StreamingResponse:
    """用量电表:统计回复字数并落盘 usage.jsonl(流结束才记账,客户端中途断开不记)。
    注意:必须先捕获原迭代器再替换 body_iterator,否则新生成器会自引用死锁。
    记账是同步文件写,放线程池执行,避免长记录时阻塞事件循环。"""
    original = resp.body_iterator

    async def counted():
        chars = 0
        async for frame in original:
            chars += _frame_text_len(frame)
            yield frame
        try:
            await asyncio.to_thread(
                _record, rec, cmd=cmd, prompt_len=prompt_len, reply_len=chars,
                role=meta["role"], research=meta["research"],
                workspace=meta.get("workspace", "learn"))
        except Exception as exc:  # noqa: BLE001 记账失败不能反过来打断已完成的回答
            print(f"[chat] 用量记账失败(不影响回答): {exc}")

    resp.body_iterator = counted()
    return resp


def _record(rec: dict, *, cmd: str, prompt_len: int, reply_len: int,
            role: str, research: bool, workspace: str = "learn") -> None:
    """用量记账统一入口(聊天链路与语音转写共用,字段口径不会各写各的)。

    只写 uid:手机号/昵称属于身份信息,成本日志不需要。
    workspace 区分学习辅助与科学研究;语音转写始终记 learn。
    """
    usage.record(
        uid=str(rec.get("uid") or "anonymous"),
        cmd=cmd,
        prompt_len=prompt_len,
        reply_len=reply_len,
        role=role,
        research=research,
        ts=time.time(),
        workspace=workspace,
    )


async def _gen_research(question: str, outcome: rag.research.SearchOutcome, zh: bool,
                        ck: str | None = None, extra: str = ""):
    """研究型 LLM 综合:正文流式 + 引用区(后端拼装,不经过模型);
    模型失败自动降级为来源列表;ck 非空时全文入库缓存供重复问题秒回"""
    full: list[str] = []
    try:
        async for delta in rag.research.synthesize.synthesize_stream(
                question, outcome.hits, zh, role=rag.llm.pick("deep"),
                extra=extra):
            full.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 研究综合失败,降级为来源列表: {exc}")
        if full:
            # 已经流出一部分:不能再回放来源列表(用户会看到「半截正文 + 完整兜底」)
            note = ("\n\n⚠ 综合生成中断,以上内容可能不完整。"
                    if zh else "\n\n⚠ Synthesis interrupted; the text above may be incomplete.")
            yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
            return
        async for frame in _frames(_research_reply(outcome, zh)):
            yield frame
        return
    citations = (rag.research.synthesize.citations_block(outcome.hits, zh)
                 if outcome.hits else "")
    if citations:
        full.append(citations)
        async for frame in _frames(citations, pace=False):
            yield frame
    if ck:
        _RESEARCH_ANSWER[ck] = (time.monotonic(), "".join(full))
        _RESEARCH_ANSWER.move_to_end(ck)
        while len(_RESEARCH_ANSWER) > _RESEARCH_MAX:
            _RESEARCH_ANSWER.popitem(last=False)


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
        async for delta in rag.llm.stream_chat(system, user, role=role, thinking=False):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 300:
                break
    except Exception:  # noqa: BLE001 复核失败静默跳过,不影响主回答
        return None
    text = "".join(parts).strip()
    return text[:200] or None


async def _gen_llm(prompt: str, cmd: str | None, chunks: list[tuple[rag.Chunk, float]],
                   history: list[dict] | None = None, role: str = "main", verify: bool = False,
                   summary: str = "", sid: int | None = None, uid: str = "",
                   workspace: str = "learn"):
    """LLM 流式:模型增量原样转发(带多轮历史);调用失败自动降级为直答,不让前端假死。
    verify=True 时解答完成后用另一角色复核,结论追加在末尾(复核失败静默跳过);
    summary 为更早对话的滚动摘要(附在 system 中),回答结束后异步推进摘要(每 8 轮一次)。
    已经流出一部分后再失败时不回放直答,只追加中断提示,避免答案被拼接两遍。"""
    zh = _is_chinese(prompt)
    answer: list[str] = []
    try:
        system = rag.build_system(chunks, cmd, zh=zh)
        if workspace == "research":
            # 科研区收紧为纯 RAG:只依据【资料】作答,不用模型自身知识补充;
            # 资料不足必须明说,避免把通识猜测包装成文献结论
            system += (
                "\n\n【科研模式】只依据上方【资料】回答;"
                "每条关键结论注明资料编号,如【资料1】;"
                "资料不足以回答时,直接说明「现有资料不足以回答」,"
                "不得用模型自身知识补充,不得编造引用。"
                if zh else
                "\n\n[Research mode] Answer ONLY from the sources above. "
                "Cite source numbers such as [Source 1] for every key claim. "
                "If the sources are insufficient, say so directly; do not use "
                "outside knowledge and do not fabricate citations."
            )
        if summary:
            system += f"\n\n【更早对话摘要】\n{summary}"
        async for delta in rag.llm.stream_chat(system, prompt, history=history, role=role):
            answer.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
        if verify:
            # 解答者与复核者错开模型保证独立:deep 解答 → main 复核;main 解答 → deep 复核
            vrole = "main" if role == "deep" else rag.llm.pick("deep")
            verdict = await _verify_answer(prompt, "".join(answer), vrole)
            if verdict:
                print(f"[chat] 复核({vrole}): {len(verdict)} 字")
                yield f"data: {json.dumps(f'\n\n> 🔍 复核({vrole}): {verdict}', ensure_ascii=False)}\n\n"
            # 解答完询问是否收录进问题记录(归纳本):前端渲染为「是/否」按钮。
            # 科研区不设问题归纳,不追加该入口。
            if workspace == "learn":
                nb = ("\n\n[是](cmd://nb/yes) [否](cmd://nb/no)" if zh
                      else "\n\n[Yes](cmd://nb/yes) [No](cmd://nb/no)")
                yield f"data: {json.dumps(nb, ensure_ascii=False)}\n\n"
        if sid is not None and history and len(history) >= 16:
            # 每 8 次请求异步压缩一次更早的对话(不阻塞本次响应;失败静默)
            tick = bump_tick(uid, sid, workspace=workspace)
            if tick % 8 == 0:
                asyncio.create_task(
                    _update_summary(uid, sid, history[:-8],
                                    get_summary(uid, sid, workspace=workspace),
                                    workspace=workspace))
    except Exception as exc:  # noqa: BLE001 模型侧错误不区分类型,统一降级
        print(f"[chat] LLM 调用失败,降级为知识库直答: {exc}")
        if answer:
            note = ("\n\n⚠ 模型连接中断,以上回答可能不完整。"
                    if zh else "\n\n⚠ Model connection lost; the answer above may be incomplete.")
            yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
            return
        note = "⚠ 模型调用失败,以下为知识库直答内容:\n\n"
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        async for frame in _frames(_compose_direct(prompt, chunks)):
            yield frame
        return


async def _gen_continue(question: str, partial: str, zh: bool):
    """续写被用户中断的回答:只输出后续内容,不重复已有部分,不重复检索/复核。

    前端把已生成正文放在 partial;这里只取末尾 24000 字(续写最依赖靠近中断点的
    上下文),并保留原问题帮助模型保持同一题意。
    """
    system = (
        "你是 MathGuide。用户中断了你上一条回答,现在要求从断点继续。"
        "只输出续写的后续内容:不要重复已生成的内容,不要重写开头,不要解释,"
        "不要输出「继续」「好的」等元话语。保持原回答的语言、语气和数学格式。"
        if zh else
        "You are MathGuide. The user interrupted your previous answer and now asks "
        "you to continue. Output ONLY the continuation: do not repeat generated "
        "content, do not restart, do not explain, and do not add meta phrases such "
        "as 'continuing'. Keep the original language, tone and math formatting."
    )
    tail = partial.strip()[-24000:]
    user = (
        f"原问题:\n{question[:2000]}\n\n已生成内容:\n{tail}\n\n请从中断处继续。"
    )
    role = _pick_role(question)
    try:
        async for delta in rag.llm.stream_chat(system, user, role=role):
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 续写失败只提示,不改动已有内容
        print(f"[chat] 续写失败: {exc}")
        note = ("⚠ 续写失败,请稍后重试。" if zh
                else "⚠ Continuation failed. Please try again.")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"


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
    emitted = False
    try:
        async for delta in rag.llm.stream_chat(_nav_system(), question[:TEXTBOOK_CAP], role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 章节导航调用失败: {exc}")
        zh = _is_chinese(question)
        text = (("⚠ 章节导航中断,以上列表可能不完整。" if emitted
                 else "⚠ 章节导航调用失败,请稍后重试。") if zh else
                ("⚠ Chapter navigation interrupted; the list above may be incomplete." if emitted
                 else "⚠ Chapter navigation failed. Please try again."))
        yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
        return


async def _gen_nav_guide(question: str, tb: str = ""):
    """章节指引:用户点击章节后给出该章大概知识指引,末尾附「返回」按钮行;
    tb 为按会话缓存的教材文本,缓存失效时按通用知识作答该章"""
    prompt = question[:2000]
    if tb:
        prompt += f"\n\n<教材文本>:\n{tb}"
    else:
        prompt += "\n\n(教材内容缓存已失效,请按通用知识作答该章)"
    emitted = False
    try:
        async for delta in rag.llm.stream_chat(_nav_guide_system(), prompt, role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 章节指引调用失败: {exc}")
        zh = _is_chinese(question)
        text = (("⚠ 章节指引中断,以上内容可能不完整。" if emitted
                 else "⚠ 章节指引调用失败,请稍后重试。") if zh else
                ("⚠ Chapter guidance interrupted; the text above may be incomplete." if emitted
                 else "⚠ Chapter guidance failed. Please try again."))
        yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
        return
    yield f"data: {json.dumps('\n\n[返回](cmd://back)', ensure_ascii=False)}\n\n"


async def _gen_attach_llm(name: str, body: str, zh: bool):
    """粘贴导入的文本文件:正文交 LLM 阅读理解,概括主题并引导提问;失败降级为接收回执"""
    system = (
        "用户通过复制粘贴导入了一个文本文件「{name}」。请阅读内容后简短回应:"
        "先用一两句话概括文件主题,再告诉用户可以针对内容提问(如总结、讲解、翻译)。"
        "不要搜索外部资料,不要编造文件里没有的内容;用与文件内容相同的语言回应。"
    ).format(name=name)
    emitted = False
    try:
        async for delta in rag.llm.stream_chat(system, body[:TEXTBOOK_CAP], role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 模型侧错误统一降级,不让前端假死
        print(f"[chat] 粘贴文本 LLM 调用失败,降级为接收回执: {exc}")
        if emitted:
            note = ("⚠ 文件解读中断,以上内容可能不完整。" if zh
                    else "⚠ File reading interrupted; the text above may be incomplete.")
        else:
            note = (ATTACH_FILE_ZH if zh else ATTACH_FILE_EN).format(name=name, size="—")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        return


# 公式手册第一步的澄清标记(与前端 i18n 双语模板固定子串成契约):
# 命中即走澄清分支——不检索知识库、不触发复核与问题记录收纳
_CLARIFY_ZH = "请先询问我想查哪个具体知识点"
_CLARIFY_EN = "Please first ask me which specific topic"


def _is_formula_clarify(question: str, cmd: str | None) -> bool:
    """公式手册两步流程的第一步:指令命中且提问带澄清标记"""
    return cmd == "公式查询手册" and (_CLARIFY_ZH in question or _CLARIFY_EN in question)


def _is_formula_followup(history: list[dict] | None) -> bool:
    """公式手册两步流程的第二步:上一条用户消息带澄清标记 → 本轮是
    「说出知识点」的作答轮,双角色复核必须开启(即使检索未命中)"""
    for h in reversed(history or []):
        if h.get("role") != "user":
            continue
        return _CLARIFY_ZH in h.get("content", "") or _CLARIFY_EN in h.get("content", "")
    return False


async def _verify_clarify(question: str, answer: str, role: str) -> str | None:
    """澄清步骤独立复核:另一角色核查是否只询问了知识点、没有提前列出公式
    (失败返回 None,不打断澄清提问)"""
    system = (
        "你是公式查询手册的澄清复核员。核查以下用户请求与助手回复:"
        "回复是否只询问用户想查哪个具体知识点,没有列出任何公式、没有展开讲解。"
        "只输出一行结论(符合要求 / 不符合要求)和一句依据,不要输出其他内容。"
    )
    user = f"用户请求:{question[:300]}\n\n助手回复:\n{answer[:600]}"
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, user, role=role, thinking=False):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 300:
                break
    except Exception:  # noqa: BLE001 复核失败静默跳过,不打断澄清提问
        return None
    text = "".join(parts).strip()
    return text[:200] or None


async def _gen_formula_clarify(question: str):
    """公式手册第一次点击:只输出澄清提问(询问想查哪个具体知识点,可举例),
    不列公式、不展开讲解;澄清提问由另一角色独立复核(是否只问了知识点、
    没提前列公式),复核失败静默跳过;LLM 未配置/失败降级为静态澄清语,
    面板点击绝不无回应"""
    system = (
        "用户正在使用「公式查询手册」,想查询某一数学领域的公式和定理。"
        "请只用一两句自然、有温度的话询问用户想查哪个具体知识点,"
        "并举该领域 3~5 个常见知识点为例;不要列出任何公式,不要展开讲解,"
        "等用户说出具体知识点后再作答。回答语言跟随用户语言。"
    )
    answer: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, question[:300], role="main"):
            answer.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        print(f"[chat] 公式手册澄清调用失败,降级为静态提示: {exc}")
        zh = _is_chinese(question)
        if answer:
            text = ("⚠ 澄清提问中断,以上内容可能不完整。" if zh
                    else "⚠ Clarification interrupted; the text above may be incomplete.")
            yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
            return
        text = ("好的!你想查该领域哪个具体知识点呢?告诉我具体名称"
                "(比如你最近学到的某个概念或定理),我马上给你对应的公式与定理。") if zh else (
                "Sure! Which specific topic in this section are you looking for? "
                "Name it (e.g. a concept or theorem you just learned) and I'll fetch the formulas.")
        yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
        return
    # 双角色复核:main 出澄清提问 → deep 独立核查(与解答复核同款模式,角色错开)
    vrole = rag.llm.pick("deep")
    verdict = await _verify_clarify(question, "".join(answer), vrole)
    if verdict:
        print(f"[chat] 公式手册澄清复核({vrole}): {len(verdict)} 字")
        yield f"data: {json.dumps(f'\n\n> 🔍 复核({vrole}): {verdict}', ensure_ascii=False)}\n\n"


async def chat_stream(request: Request) -> StreamingResponse | JSONResponse:
    """聊天入口(安全外壳):认证 → 输入上限 → 限流 → 路由 → 用量记账"""
    rec = require_auth(request)  # 401: {"detail": "unauthorized"}

    body = await read_json_object(request)
    prompt = str(body.get("prompt", "")).strip()
    cmd = str(body.get("cmd", ""))[:50] if body.get("cmd") else None
    # 工作区:学习辅助 / 科学研究。两区会话、教材缓存、检索链路互不相通,
    # 只共享同一套后端服务与用户库。
    # 双域部署时以 Host 为准(learn.* / research.*),服务端固定工作区,
    # 客户端改请求体也跨不了区;单域/本机开发退回请求体字段(未知值按 learn)。
    host_workspace = config.workspace_from_host(request.headers.get("host"))
    workspace = host_workspace or valid_workspace(body.get("workspace"))

    # 服务端输入上限:前端限制之外的最后保险(超出静默截断,防误传大文本烧 token 费)
    if len(prompt) > PROMPT_MAX:
        prompt = prompt[:PROMPT_MAX]

    # 限流:每用户滑动窗口,仅对非空提问计次(新会话问候不占用额度)
    if prompt:
        _rate_check(str(rec.get("uid") or rec.get("phone") or ""))

    meta = {"role": "main", "research": False, "workspace": workspace}
    resp = await _route_chat(prompt, cmd, body, rec, meta, workspace)
    if not isinstance(resp, StreamingResponse):
        return resp
    resp = _meter(resp, rec, len(prompt), cmd or "", meta)
    return _with_meta(resp, meta)


async def speech_to_math(request: Request) -> StreamingResponse:
    """语音识别文本 → 数学符号转写(SSE 流式:首帧即上屏,前端逐帧替换输入框,
    不用等模型收尾,感知延迟 ≈ 首 token 时间)。
    一字未出时回放原文帧,不阻断语音输入;已输出半截则主动中断流(前端
    complete=false 回退原文,避免半截转写混进缓存);计入限流与用量统计"""
    rec = require_auth(request)
    body = await read_json_object(request)
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
        except Exception:  # noqa: BLE001
            if parts:
                # 已经输出半截:让流异常结束(前端 complete=false 会回退原文)。
                # 若在这里补发原文,前端会把「半截转写 + 原文」拼在一起写进缓存。
                raise
            # 一字未出:回放原文,不阻断语音输入
            yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
            return
        try:
            await asyncio.to_thread(
                _record, rec, cmd="语音转写", prompt_len=len(text),
                reply_len=sum(len(p) for p in parts), role="main", research=False)
        except Exception as exc:  # noqa: BLE001 记账失败不影响转写结果
            print(f"[chat] 语音转写记账失败: {exc}")

    return _sse(gen())


async def _route_chat(prompt: str, cmd: str | None, body: dict, rec: dict, meta: dict,
                      workspace: str = "learn"):
    """业务路由(与安全外壳分离):欢迎语 / 附件 / 章节导航 / 研究 / LLM / 直答"""
    uid = str(rec.get("uid") or "")
    paper_id = ""
    raw_paper = body.get("paperId")
    if workspace == "research" and isinstance(raw_paper, str) and raw_paper:
        candidate = raw_paper[:64]
        try:
            doc = research_corpus._doc_row(uid, candidate)
            if doc and not doc["deletedAt"]:
                paper_id = candidate
        except Exception:  # noqa: BLE001 文档校验失败不影响普通对话
            paper_id = ""

    # 数据表上下文:从数据表页「在对话中分析」带入,只在本用户科研工作区生效。
    # 表格是用户自己的数据,原文进上下文,数值仍由服务端计算,模型只解读。
    table_context = ""
    table_stamp = ""
    raw_table = body.get("tableId")
    if workspace == "research" and isinstance(raw_table, str) and raw_table:
        candidate = raw_table[:64]
        try:
            table = await asyncio.to_thread(research_tables._get_table, uid, candidate)
            if table:
                table_context = research_tables.context_text(table)
                table_stamp = f"{candidate}:{int(table.get('updatedAt') or 0)}"
        except Exception as exc:  # noqa: BLE001 表格校验失败不影响普通对话
            print(f"[chat] 数据表上下文读取失败(忽略): {exc}")

    # 前端新会话会以空 prompt 触发欢迎问候;两区文案按工作区区分
    if not prompt:
        return _stream_text(WELCOME_RESEARCH_ZH if workspace == "research" else WELCOME_ZH)

    # 用户点「回复」续写被中断的回答:只用原问题 + 已生成正文,不重新检索/复核
    if body.get("resume"):
        partial = str(body.get("partial", "")).strip()
        if not partial:
            return _stream_text("没有可续写的内容。" if _is_chinese(prompt) else "Nothing to continue.")
        question = _strip_meta(prompt, cmd)
        zh = _is_chinese(question or partial)
        meta["role"] = _pick_role(question)
        return _sse(_gen_continue(question, partial, zh))

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
            # 教材入库,后续点击只发章节名;缓存键带 workspace,两区同号 sessionId 不串档
            cache_textbook(uid, body.get("sessionId"), question, workspace=workspace)
            gen = _gen_nav_list(question)
        else:
            gen = _gen_nav_guide(question, tb=get_textbook(uid, body.get("sessionId"),
                                                          workspace=workspace))
        meta["role"] = "long"
        return _sse(gen)

    # 公式手册两步流程:第一步(澄清标记)只询问想查哪个具体知识点,
    # 不检索知识库、不触发问题记录收纳(澄清提问仍带双角色复核);
    # 用户说出知识点后走常规链路
    if _is_formula_clarify(question, cmd):
        return _sse(_gen_formula_clarify(question))

    # P0/P1 路由:研究型提问优先于知识直答
    # (「泰勒展开的最新研究进展」虽命中知识库,意图是查文献 → 走跨论文库深度搜索)
    # 必须先判意图、后检索:深度搜索内部自会检索知识库,
    # 这里若先检一遍,研究型提问就要白付一份 embedding 开销(结果还被丢掉)
    # 只允许科学研究工作区进入该链路:学习辅助区不跨区查文献
    if workspace == "research" and (
            paper_id or table_context or rag.route.is_research_intent(question)):
        meta["research"] = True
        # 搜索范围(前端勾选的平台;缺省/空 = 全平台);非法名白名单校验在 deep_search 内
        scope = _clean_scope(body.get("sources"))
        ck = _research_cache_key(question, scope,
                                 f"{uid}|{research_corpus.corpus_stamp(uid)}|{paper_id}|{table_stamp}")
        cached = _RESEARCH_ANSWER.get(ck)
        if cached and time.monotonic() - cached[0] < _RESEARCH_TTL:
            _RESEARCH_ANSWER.move_to_end(ck)  # 命中即刷新 LRU 顺序
            print(f"[chat] 研究综合缓存命中(问题 {len(question)} 字)")
            meta["role"] = "deep"
            return _stream_text(cached[1])
        outcome = await rag.research.deep_search(question, top_k=3, scope=scope)
        # 用户自己的论文库排在外部来源之前:个人语料与问题最对口,
        # 也是引用页码的唯一来源。语料库为空时行为不变。
        try:
            local = await asyncio.to_thread(
                research_corpus.chat_hits, uid, question, 4, paper_id or None)
        except Exception as exc:  # noqa: BLE001 语料检索失败不阻断外部检索
            print(f"[chat] 科研语料检索失败(继续外部来源): {exc}")
            local = []
        if local:
            outcome.hits = [
                SearchHit("我的论文",
                          f'{h["docName"]} · {h["section"]} · 第 {h["pageStart"]}-{h["pageEnd"]} 页',
                          h["snippet"], "", 0, "", 0)
                for h in local
            ] + outcome.hits
            outcome.sources["我的论文"] = len(local)
        # P2c:LLM 已配置 → 综合解答 + 编号引用 + 后端拼装引用区;
        # 未配置 → 来源列表(现有行为)。只有数据表上下文时也走综合,先解读表内数据。
        if (outcome.any_hit or table_context) and rag.llm.is_configured():
            meta["role"] = "deep"
            return _sse(_gen_research(
                question, outcome, zh, ck=ck, extra=table_context))
        return _stream_text(_research_reply(outcome, zh))

    # 检索含 embedding 请求(同步、冷启动可达数十秒)→ 线程池执行,
    # 不阻塞事件循环(否则这段等待会冻住所有并发会话)
    chunks = await asyncio.to_thread(rag.search, question, 3)

    # 科研区:无论是否命中研究意图,都先查用户自己的论文库。
    # 个人论文是私有且最对口的证据,排在公共知识库之前进入上下文。
    if workspace == "research":
        try:
            local = await asyncio.to_thread(
                research_corpus.chat_hits, uid, question, 4, paper_id or None)
        except Exception as exc:  # noqa: BLE001 语料检索失败不影响主链路
            print(f"[chat] 科研语料检索失败(继续公共知识库): {exc}")
            local = []
        if local:
            chunks = [
                (rag.Chunk(h["nodeId"], h["docName"], "",
                           f'{h["section"]} · 第 {h["pageStart"]}-{h["pageEnd"]} 页',
                           h.get("text") or h["snippet"]), 6.0)
                for h in local
            ] + chunks

    if workspace == "research" and table_context:
        chunks = [
            (rag.Chunk("research-table", "研究数据表", "",
                       "用户当前数据表(数值以此为准)", table_context), 7.0),
        ] + chunks

    if rag.llm.is_configured():
        # 双角色验证仅对数学题(命中知识库或题目措辞)开启;闲聊不浪费复核调用。
        # 公式手册第二步(上一条用户消息带澄清标记)强制开启:公式定理作答必须有独立复核
        role = _pick_role(question)
        meta["role"] = role
        sid = valid_session_id(body.get("sessionId"))
        history = _validated_history(body.get("history"))
        verify = bool(chunks) or rag.is_math_question(question) or _is_formula_followup(history)
        summary = get_summary(uid, sid, workspace=workspace) if sid is not None else ""
        return _sse(_gen_llm(question, cmd, chunks, history=history, role=role, verify=verify,
                             summary=summary, sid=sid, uid=uid, workspace=workspace))
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
