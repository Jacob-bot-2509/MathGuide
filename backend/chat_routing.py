"""聊天路由的纯函数:语言判断、角色选择、问题归一、意图识别。

这里**不发网络请求、不碰存储、不写响应**,只做判定与字符串加工,
因此可以脱离事件循环直接单测。
"""
from __future__ import annotations

import random
import re
import unicodedata

import rag
from chat_prompts import _CLARIFY_EN, _CLARIFY_ZH, FALLBACK_EN, FALLBACK_ZH
from log import get_logger

log = get_logger(__name__)

def _is_chinese(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


# 数学题判定(知识库触发词 + 题目措辞)统一在 rag.is_math_question:
# 正则编译一次缓存复用,评测工具与线上链路同源

# 深答路由触发词:证明 / 竞赛类问题交给 deep 强模型(未配置自动回退 main)

_DEEP_MARKERS = ("证明", "求证", "竞赛", "奥数", "难题", "prove", "proof", "olympiad")
# 多小问标记:一道题里出现 2 个以上,通常比单问计算更吃推理

_MULTI_PART_RE = re.compile(r"[（(]\s*[1-9一二三四五六七八九]\s*[)）]|[①②③④⑤⑥⑦⑧⑨]")

def _pick_role(question: str) -> str:
    """按需路由 LLM 角色:证明/竞赛/多小问/长综合题 → deep,其余 main。
    只按规则路由,不做模型分类:规则离线可解释,且不会把简单题误送贵模型。"""
    q = question.lower()
    parts = len(_MULTI_PART_RE.findall(question))
    hard = (
        any(m in q for m in _DEEP_MARKERS)
        or parts >= 2
        or len(question) >= 300
    )
    role = rag.llm.pick("deep") if hard else "main"
    log.info(f"[chat] 角色路由 {role} | 问题长度 {len(question)} | 小问数 {parts}")
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
        "我能帮你做这些:讲概念、串章节知识、归纳错题、查公式,还能给难题搭解题框架;需要时可以把概念换成直观说法。",
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


# 追问标记:短问句里出现这些指代/承接词时,检索需要带上上一轮的提问。
# 只认「那/它/这个/上述…」这类真正依赖前文的词,不把普通的「为什么/怎么」也算进来。

_FOLLOWUP_RE = re.compile(
    r"^(那|那么|这个|那个|它|其|它们|还有|以及|如果|and|so|then|what about|how about|it|this|that)?"
    r"|(它|这个|那个|上述|前面|刚才|上面|该).*(关系|联系|区别|为什么|怎么|如何|呢|吗)",
    re.IGNORECASE,
)


# 检索专用口语前缀:只影响检索词,不改发给模型的 prompt

_QUERY_FILLER_RE = re.compile(
    r"^(?:请问|请帮我|帮我|麻烦(?:你)?|我想问(?:一下)?|求解一下|解一下)[,，:：\s]*"
)

def _normalize_query(text: str) -> str:
    """检索前归一化:全角转半角、LaTeX 定界命令去噪、空白压缩、去口语前缀。
    只做等价变换,不删题目里的数学内容。"""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"\\(?:left|right)(?![A-Za-z])", "", value)
    value = value.replace("−", "-").replace("–", "-")
    value = re.sub(r"\s+", " ", value).strip()
    value = _QUERY_FILLER_RE.sub("", value)
    return value[:500]

def _retrieval_query(question: str, history: list[dict] | None) -> str:
    """普通问答的检索词:追问时拼上一轮用户问题,避免「它和积分有什么关系」只检索“积分”。

    只影响检索,不改发给模型的 prompt;历史仍按原样交给 LLM。
    """
    question = _normalize_query(question)
    if not history or not _FOLLOWUP_RE.search(question):
        return question
    previous = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user" and m.get("content")),
        "",
    )
    if not previous:
        return question
    return f"{_normalize_query(previous)} {question}"[:500]


# 会话滚动摘要:每 8 次请求压缩一次旧对话(便宜模型,失败静默),长对话保持早期上下文。
# 与教材缓存一样按 (uid, workspace, sid) 隔离,避免客户端自增的 sessionId 跨用户/跨区撞号。

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

_IMPORT_RE = re.compile(
    r"入库|进库|加入.{0,6}(?:论文)?库|导入.{0,6}(?:论文)?库|"
    r"存(?:进|到|入).{0,6}(?:论文)?库|保存.{0,6}(?:论文)?库|"
    r"收(?:进|到).{0,6}(?:论文)?库|放(?:进|到|入).{0,6}(?:论文)?库|"
    r"\bimport\b.{0,20}(?:this|the)?\s*paper|\bimport\b.{0,20}librar|\badd\b.{0,20}librar",
    re.IGNORECASE,
)

def _is_import_request(question: str) -> bool:
    return bool(_IMPORT_RE.search(question or ""))

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

_ANALYSIS_TOPICS = (
    "学习进度", "学习情况", "掌握情况", "学习分析", "知识图谱", "薄弱点",
    "学得怎么样", "学得如何", "艾宾浩斯", "遗忘曲线", "记忆保持", "复习优先级",
)

_ANALYSIS_EN = (
    "my learning progress",
    "analyze my learning",
    "my progress",
    "my mastery",
    "my knowledge graph",
)

def _is_learning_analysis_request(question: str) -> bool:
    """自然语言触发的学习分析:第一人称 + 学习进度语义,避免劫持普通提问。"""
    text = (question or "").strip()
    if not text:
        return False
    if "我的" in text and any(topic in text for topic in _ANALYSIS_TOPICS):
        return True
    lower = text.lower()
    return any(marker in lower for marker in _ANALYSIS_EN)

_FEATURE_TOPICS = (
    "艾宾浩斯", "遗忘曲线", "记忆保持", "复习优先级",
    "学习分析算法", "掌握度算法", "待复核算法",
)

def _is_feature_question(question: str) -> bool:
    """问系统实现而不是问自己的进度:必须按固定事实回答。"""
    text = (question or "").strip()
    if not text or "我的" in text:
        return False
    return any(topic in text for topic in _FEATURE_TOPICS)
