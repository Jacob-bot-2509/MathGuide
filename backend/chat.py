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
import hashlib
import json
import re
import secrets
import time
from collections import OrderedDict

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

import analysis_client
import config
import diagnosis
import diagram_metrics
import learning_analysis
import quota
import rag
import research_actions
import research_corpus
import research_diagrams
import research_tables
import usage
from auth import require_auth

# ---- 从 chat.py 拆出的三块(M3-1):协议 / 提示词 / 纯路由函数 ----
# 整组导入并标注 F401 豁免:外部(main.py 与 tests)仍按 `chat._sse`、
# `chat.WELCOME_ZH`、`chat._pick_role` 取用,改名会打断它们。
from chat_prompts import (  # noqa: F401
    _CLARIFY_EN,
    _CLARIFY_ZH,
    _INTUITION_SYSTEM_EN,
    _INTUITION_SYSTEM_ZH,
    ATTACH_FILE_EN,
    ATTACH_FILE_ZH,
    ATTACH_IMAGE_EN,
    ATTACH_IMAGE_ZH,
    FALLBACK_EN,
    FALLBACK_ZH,
    WELCOME_RESEARCH_ZH,
    WELCOME_ZH,
    _nav_guide_system,
    _nav_system,
)
from chat_routing import (  # noqa: F401
    _ANALYSIS_EN,
    _ANALYSIS_TOPICS,
    _DEEP_MARKERS,
    _FEATURE_TOPICS,
    _FOLLOWUP_RE,
    _IMPORT_RE,
    _MULTI_PART_RE,
    _QUERY_FILLER_RE,
    _chitchat_kind,
    _clean_scope,
    _compose_direct,
    _conversational_reply,
    _is_chinese,
    _is_feature_question,
    _is_formula_clarify,
    _is_formula_followup,
    _is_import_request,
    _is_learning_analysis_request,
    _normalize_query,
    _pick_role,
    _research_cache_key,
    _retrieval_query,
    _strip_meta,
    _validated_history,
)
from chat_sse import (  # noqa: F401
    _DONE,
    CHUNK,
    FRAME_MS,
    _frame_text_len,
    _frames,
    _sse,
    _stream_text,
    _with_meta,
)
from http_utils import read_json_object
from log import get_logger
from rag.research.types import SearchHit
from rate_limit import NullLimiter, SlidingWindowLimiter
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

log = get_logger(__name__)


def _answer_is_zh(text: str, history: list[dict] | None = None) -> bool:
    """回答语言:有汉字→中文;有拉丁字母且无汉字→英文;
    纯数字/符号(如 "1+1=?")→沿用最近一条带语言的历史,没有则默认中文。"""
    if _is_chinese(text):
        return True
    if re.search(r"[A-Za-z]", text or ""):
        return False
    for item in reversed(history or []):
        content = str(item.get("content") or "")
        if _is_chinese(content):
            return True
        if re.search(r"[A-Za-z]", content):
            return False
    return True

DIAGRAM_TIMEOUT = 45.0  # 单张图规划上限(秒);3D 采样较慢,但不能无限拖住回答
# 普通问答检索条数:前 3 条在 prompt 里标「重点」,后 2 条标「备选」。
# top5 比 top3 多召回金标(旧 48 题:0.667→0.75),但不会全部当同等依据。
RETRIEVAL_TOP_K = 5























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
        log.info(f"[chat] 会话 {sid} 摘要已更新({len(text)} 字)")


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





PROMPT_MAX = 210_000  # 服务端输入上限(字符):覆盖单章教材(20 万字)+ 指令前缀,超出静默截断
ATTACH_READ_CAP = 30_000  # 上传时的文本附件只让模型读前 3 万字,避免上传即产生长上下文费用
PAPER_CONTEXT_CHARS = 20000  # 当前论文问答带入的正文上限:足够覆盖摘要+方法+结果,不挤爆上下文

# 限流:每用户滑动窗口(防脚本刷接口烧 token 费;正常学习节奏碰不到上限)。
# 公共实现会清理不活跃 key,游客登录不断产生新 uid 也不会让内存无界增长。
# 数值可配(MG_CHAT_RATE_MAX / MG_CHAT_RATE_WINDOW),默认 6 次/60 秒不变;
# 0 = 关闭,只给压测「测天花板」用(见 configure_rate_limit 的说明)。
_RATE_LIMIT_MAX = 6
_RATE_WINDOW = 60.0
_rate_limiter: SlidingWindowLimiter | NullLimiter = SlidingWindowLimiter(_RATE_LIMIT_MAX, _RATE_WINDOW)


def configure_rate_limit() -> None:
    """按环境变量重建每用户限流器(main.py 在 env 装载后调用,与 auth 同一口径)。

    MG_CHAT_RATE_MAX     默认 6 次;0 = 关闭限流
    MG_CHAT_RATE_WINDOW  默认 60 秒

    为什么允许 0:这条限流在**贵的活之前**判定(chat 入口、导出入口都是),
    默认 6 次/分时,同一账号发 7 个并发请求,第 7 个撞到的是 `rate limited`,
    不是导出闸门的 `pdf export busy` —— 也就是说**限流会先于并发闸门触发,
    量到的是限流口径而不是机器上限**。压测要测容量时先把它关掉,测完立刻恢复:

        MG_CHAT_RATE_MAX=0  →  量 QPS / 延迟 / 闸门拒绝率(= 天花板)
        恢复默认 6           →  验证保护是否按预期咬住(别让 0 留在生产)

    坏值(拼错、负数)回退默认 6,不会意外关闭。
    """
    global _RATE_LIMIT_MAX, _RATE_WINDOW, _rate_limiter
    _RATE_LIMIT_MAX = int(config.env_number("MG_CHAT_RATE_MAX", 6, 0))
    _RATE_WINDOW = config.env_number("MG_CHAT_RATE_WINDOW", 60.0, 1.0)
    _rate_limiter = (
        SlidingWindowLimiter(_RATE_LIMIT_MAX, _RATE_WINDOW)
        if _RATE_LIMIT_MAX > 0
        else NullLimiter()
    )


def _rate_check(uid: str) -> None:
    if not _rate_limiter.allow(uid or "anonymous"):
        # Retry-After 与导出闸门同一口径:客户端/压测脚本据此把两种 429 分开
        # (限流 = 测法太密,闸门 = 容量上限),见 tools/locustfile.py 的分类计数
        raise HTTPException(429, "rate limited",
                            headers={"Retry-After": str(int(_RATE_WINDOW) or 60)})




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
            log.warning(f"[chat] 用量记账失败(不影响回答): {exc}")

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


def _diagram_requested(body: dict) -> bool:
    """研究综述图解必须显式开启;缺省不插图。"""
    return isinstance(body, dict) and body.get("diagrams") is True


def _regression_summary(result: dict, stale: bool) -> str:
    """把服务端回归结果压成一行上下文;模型只引用,不重算。"""
    parts = [
        f"model={result.get('model') or 'ols'}",
        f"n={result.get('n') or 0}",
        f"equation={result.get('equation') or ''}",
        f"R²={result.get('r2') if result.get('r2') is not None else '—'}",
    ]
    coefficients = result.get("coefficients") or []
    coef_text = "；".join(
        f"{item.get('term')} estimate={item.get('estimate')} "
        f"p={item.get('p') if item.get('p') is not None else '—'}"
        for item in coefficients[:6] if isinstance(item, dict))
    if coef_text:
        parts.append(coef_text)
    warnings = [str(item) for item in (result.get("warnings") or []) if item]
    if warnings:
        parts.append("warnings=" + ",".join(warnings))
    prefix = "table_changed: " if stale else ""
    return prefix + "; ".join(parts)[:2000]


async def _gen_research(question: str, outcome: rag.research.SearchOutcome, zh: bool,
                        ck: str | None = None, extra: str = "",
                        diagrams: bool = False, request_id: str = ""):
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
        log.warning(f"[chat] 研究综合失败,降级为来源列表: {exc}")
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
    if diagrams:
        text = "".join(full)
        try:
            diagram = await research_diagrams.plan_diagram(
                question, text, [], "", mode="research", table_context=extra)
            if diagram:
                anchor = len(text.encode("utf-16-le")) // 2
                frame = research_diagrams.diagram_event(
                    diagram, request_id or secrets.token_hex(8),
                    f"research-{secrets.token_hex(4)}", anchor)
                if frame:
                    yield frame
        except Exception as exc:  # noqa: BLE001 图解失败不影响综述
            log.warning(f"[chat] 研究综述图解失败(忽略): {exc}")
    if ck:
        _RESEARCH_ANSWER[ck] = (time.monotonic(), "".join(full))
        _RESEARCH_ANSWER.move_to_end(ck)
        while len(_RESEARCH_ANSWER) > _RESEARCH_MAX:
            _RESEARCH_ANSWER.popitem(last=False)










async def _verify_answer(question: str, answer: str, role: str, zh: bool = True) -> dict | None:
    """双角色验证:解答生成后用另一角色复核。
    返回 {"verdict": correct|wrong|uncertain, "issue": ..., "correction": ...};
    复核不可用时返回 None,不打断主回答。"""
    if zh:
        system = (
            "你是数学解答复核员。请核查用户问题与给出的解答,只输出一个 JSON 对象,"
            "不要 Markdown、不要解释。字段:\n"
            '{"verdict":"correct|wrong|uncertain","issue":"一句话指出问题或依据",'
            '"correction":"若 verdict=wrong,给出可替换的更正解答;否则留空"}\n'
            "判断以题目条件和数学定义为准;过程省略但结论正确也算 correct;"
            "不确定时用 uncertain,不要强行判错。"
        )
        user = f"问题:{question[:500]}\n\n解答:\n{answer[:4000]}"
    else:
        system = (
            "You are a math answer reviewer. Check the user's question and the proposed answer. "
            "Output exactly one JSON object, with no Markdown and no extra prose. Fields:\n"
            '{"verdict":"correct|wrong|uncertain","issue":"one sentence on the problem or basis",'
            '"correction":"if verdict=wrong, give a replacement answer; otherwise leave empty"}\n'
            "Judge against the problem conditions and mathematical definitions; a correct "
            "conclusion with omitted steps still counts as correct; use uncertain rather than "
            "forcing a verdict. Write both issue and correction entirely in English."
        )
        user = f"Question: {question[:500]}\n\nAnswer:\n{answer[:4000]}"
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(
                system, user, role=role, thinking=False, max_tokens=1600,
                temperature=0):
            parts.append(delta)
            if sum(len(p) for p in parts) >= 4000:
                break
    except Exception:  # noqa: BLE001 复核失败静默跳过,不影响主回答
        return None
    text = "".join(parts).strip()
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            verdict = str(data.get("verdict", "")).strip().lower()
            if verdict not in {"correct", "wrong", "uncertain"}:
                verdict = "uncertain"
            return {
                "verdict": verdict,
                "issue": str(data.get("issue", "")).strip()[:300],
                "correction": str(data.get("correction", "")).strip()[:4000],
            }
    # 兼容模型只给一句话的情况:不把它当判错
    return {"verdict": "uncertain", "issue": text[:300], "correction": ""}


async def _diagram_verified(question: str, context: str, diagram: dict) -> bool:
    """异源模型判断图是否对题;校验不可用时放行(不因质检故障丢图)。"""
    if not research_diagrams.verify_enabled():
        return True
    try:
        verdict = await asyncio.wait_for(
            research_diagrams.verify_diagram(question, context, diagram), timeout=6.0)
    except Exception:  # noqa: BLE001 校验失败不拦图
        diagram_metrics.record("verify", False, "error")
        return True
    if verdict is None:
        diagram_metrics.record("verify", False, "unknown")
        return True
    diagram_metrics.record("verify", verdict, "ok" if verdict else "mismatch")
    return verdict


async def _gen_llm(prompt: str, cmd: str | None, chunks: list[tuple[rag.Chunk, float]],
                   history: list[dict] | None = None, role: str = "main", verify: bool = False,
                   summary: str = "", sid: int | None = None, uid: str = "",
                   workspace: str = "learn", paper_mode: bool = False,
                   diagram_mode: bool = False, diagram_allowed: bool = True,
                   diagram_question: str = "",
                   diagram_excerpts: list[dict] | None = None,
                   diagram_request_id: str = "",
                   temperature: float | None = None):
    """LLM 流式:模型增量原样转发(带多轮历史);调用失败自动降级为直答,不让前端假死。
    verify=True 时解答完成后用另一角色复核,结论追加在末尾(复核失败静默跳过);
    summary 为更早对话的滚动摘要(附在 system 中),回答结束后异步推进摘要(每 8 轮一次)。
    已经流出一部分后再失败时不回放直答,只追加中断提示,避免答案被拼接两遍。"""
    zh = _answer_is_zh(prompt, history)
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
        if paper_mode:
            # 论文窗口动作已由服务端规划、前端执行;模型不要在正文里否认能力,
            # 也不要重复输出动作清单,只解释内容并指出页码/章节。
            system += (
                "\n\n【论文窗口】系统已自动根据你的规划完成定位、跳页、高亮"
                "和批注动作;不要说“我无法操作文档/无法高亮”。"
                "回答时直接解释论文内容,并说明依据的页码和章节。"
                if zh else
                "\n\n[Paper window] The system has already executed the planned "
                "locate, jump, highlight and annotation actions. Never claim you "
                "cannot operate the document or highlight text. Explain the content "
                "directly and cite the page and section."
            )
        if summary:
            system += f"\n\n【更早对话摘要】\n{summary}"
        if diagram_mode and not diagram_allowed:
            system += (
                "\n\n【本轮不画图】用户已经明确要求当前阶段不要生成图解。"
                "只输出文字讲解,不要输出任何 [[MG_DIAGRAM:...]] 标记,"
                "也不要主动提到图解、配图、示意图或“需要看图”。"
                if zh else
                "\n\n[No diagram this turn] The user explicitly asked not to "
                "generate a diagram for now. Answer in text only. Do not output "
                "any [[MG_DIAGRAM:...]] marker and do not mention diagrams, "
                "figures or visual aids."
            )
        elif diagram_mode:
            system += (
                "\n\n【图解·边讲边画】讲解到需要看图才能讲清的步骤时,"
                "在该段结束、下一段开始之前,单独一行输出隐藏标记 "
                "[[MG_DIAGRAM:<type>]],<type> 换成实际类型。"
                "要求:"
                "① 按讲课节奏一步一图:有明确步骤就按步骤来,每张只图解刚讲完的这一小步;"
                "步骤不要过细,把连续的代入/整理/化简合并,每步是一个完整的关键动作,"
                "通常 2–5 步;只为关键步骤配图,不要机械地一步一图铺满;"
                "没有明确步骤时,只在内容确实需要具象化的地方标记,不要每段都标,也不要为凑数;"
                "② 自主选择 2D/3D:一元函数及其导数用 2D;多元函数、偏导数、曲面、梯度用 3D;"
                "平面几何、函数曲线、二维关系用 2D;空间对象、立体结构用 3D;"
                "用户没指定维度时按内容权重判断,不要默认 2D;能用 2D 讲清就不要硬上 3D;"
                "③ 用户明确说“用三维图/画图/几何直观”等表示方式时,"
                "直接按要求画,不要改画思维导图;"
                "④ 抽象概念要化抽象为具体:先用一个具体类比物把它实体化"
                "(如把梯度想成山坡最陡的上坡方向),再画出来;"
                "⑤ 标记前先用一两句话告诉用户这张图看什么,再继续讲解;"
                "⑥ 寒暄、系统介绍、功能列表、简单事实、短答案不标记;"
                "标记独占一行,不要解释标记;"
                "⑦ 不要向用户解释图解类型、权重、评分或选型依据,直接画图并讲内容。"
                if zh else
                "\n\n[Diagram - draw while teaching] When a step needs a picture "
                "to be understood, insert a hidden marker on its own line after "
                "that paragraph, for example [[MG_DIAGRAM:surface3d]] (replace the "
                "type; allowed: tree/relation/flow/geometry2d/plot2d/geometry3d/"
                "surface3d). Requirements: (1) one diagram per teaching step; if the "
                "answer has explicit steps, follow them; keep steps coarse — merge "
                "consecutive substitution/simplification fragments, usually 2–5 key "
                "steps, and diagram only the key steps rather than every step; "
                "otherwise mark only where a picture genuinely helps, not every "
                "paragraph; (2) choose 2D or 3D "
                "yourself: one-variable functions and their derivatives -> 2D; "
                "multivariable functions, partial derivatives, surfaces and "
                "gradients -> 3D; planar geometry, curves and 2D relations -> 2D; "
                "spatial objects -> 3D; if the user gives no dimension, judge by "
                "the content weights and never default to 2D; do not force 3D when "
                "2D explains it; (3) when the user explicitly asks for a 3D drawing "
                "or a picture, draw exactly that instead of a mind map; (4) make "
                "abstractions concrete through a visible analogy; (5) say in one or "
                "two sentences what to look at before the marker, then continue "
                "teaching; (6) never for greetings, system introductions, feature "
                "lists, simple facts, or short answers; the marker must be on its "
                "own line; (7) never explain the diagram "
                "type, weights, scores or selection rationale to the user; just "
                "draw the figure and teach the content."
            )
        markers = research_diagrams.MarkerStream(
            diagram_request_id or secrets.token_hex(8)) if diagram_mode else None
        diagram_tasks: list[tuple[research_diagrams.DiagramMarker, asyncio.Task]] = []
        auto_context: dict[str, str] = {}
        pending_verify: list[tuple[research_diagrams.DiagramMarker, dict,
                                    asyncio.Task]] = []
        scheduled_diagrams = 0
        kept_anchors: list[int] = []
        stepwise_hint = research_diagrams.is_step_text(diagram_question or prompt)
        explicit_requested = research_diagrams.explicit_type(
            diagram_question or prompt)
        total_points = 0
        total_bytes = 0

        async def drain_verified(force: bool = False):
            """语义校验在后台跑,不阻塞正文;完成且通过才发图。"""
            for item in list(pending_verify):
                marker, diagram, task = item
                if not force and not task.done():
                    continue
                pending_verify.remove(item)
                try:
                    ok = await task
                except Exception:  # noqa: BLE001 校验异常放行
                    ok = True
                if not ok:
                    diagram_metrics.record("drop", False, "verify")
                    continue
                frame = diagram_frame(diagram, marker)
                if frame:
                    yield frame

        def diagram_frame(diagram: dict,
                          marker: research_diagrams.DiagramMarker) -> str:
            nonlocal total_points, total_bytes
            points, size = research_diagrams.diagram_cost(diagram)
            if (total_points + points > research_diagrams.MAX_TOTAL_POINTS
                    or total_bytes + size > research_diagrams.MAX_TOTAL_BYTES):
                diagram_metrics.record("drop", False, "budget", points=points)
                return ""
            total_points += points
            total_bytes += size
            diagram_metrics.record("emit", True, "ok", points=points)
            return research_diagrams.diagram_event(
                diagram, markers.request_id,
                marker.anchor_id, marker.anchor_index)
        stream_kwargs = {"history": history, "role": role}
        if temperature is not None:
            stream_kwargs["temperature"] = temperature
        if markers is None:
            async for delta in rag.llm.stream_chat(system, prompt, **stream_kwargs):
                answer.append(delta)
                yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
        else:
            excerpt_items = diagram_excerpts
            if excerpt_items is None:
                excerpt_items = [
                    {"section": chunk.section, "text": chunk.text}
                    for chunk, _score in chunks
                ]
            async for delta in rag.llm.stream_chat(system, prompt, **stream_kwargs):
                clean = markers.feed(delta)
                if clean:
                    answer.append(clean)
                    yield f"data: {json.dumps(clean, ensure_ascii=False)}\n\n"
                for marker in markers.drain():
                    if not diagram_allowed:
                        diagram_metrics.record("drop", False, "user_disabled")
                        continue
                    if scheduled_diagrams >= research_diagrams.MAX_DIAGRAMS:
                        diagram_metrics.record("drop", False, "cap")
                        continue
                    if research_diagrams.is_meta_question(
                            diagram_question or prompt):
                        diagram_metrics.record("drop", False, "meta")
                        continue
                    if (research_diagrams.is_relation_question(
                            diagram_question or prompt)
                            and scheduled_diagrams >= 1):
                        diagram_metrics.record("drop", False, "relation_single")
                        continue
                    full_text = "".join(answer)
                    stepwise = stepwise_hint or research_diagrams.is_step_text(full_text)
                    # 非步骤回答:标记前 400 字里没提到图,视为装饰性图,直接丢。
                    # 步骤讲解按惯例一步一图,保留;用户明确要图也不拦。
                    if not stepwise and not explicit_requested:
                        mentioned = research_diagrams.slice_utf16(
                            full_text, marker.anchor_index)
                        if not research_diagrams.references_diagram(mentioned):
                            diagram_metrics.record("drop", False, "unreferenced")
                            continue
                    # 模型标记也要过重要度/独立性闸门:不重要的片段不画。
                    if (not explicit_requested
                            and not research_diagrams.wants_visual(
                                diagram_question or prompt)):
                        prefix = research_diagrams.slice_utf16(
                            full_text, marker.anchor_index)
                        parts = [part.strip() for part in re.split(
                            r"\n\s*\n", prefix) if part.strip()]
                        segment = " ".join(parts[-2:])
                        if research_diagrams.is_step_text(segment):
                            if research_diagrams.visual_cue_score(segment) < 1.2:
                                diagram_metrics.record("drop", False, "visual")
                                continue
                        else:
                            terms = tuple(research_diagrams._topic_terms(
                                diagram_question or prompt, full_text))
                            if research_diagrams.importance_score(
                                    segment, terms) < 1.8:
                                diagram_metrics.record("drop", False, "importance")
                                continue
                    # 非步骤内容最多 2 张,且锚点间隔 >=400 字,避免同一主题连续堆图。
                    if not stepwise and scheduled_diagrams >= 2:
                        diagram_metrics.record("drop", False, "density")
                        continue
                    if not stepwise and any(
                            abs(marker.anchor_index - anchor) < 400
                            for anchor in kept_anchors):
                        diagram_metrics.record("drop", False, "spacing")
                        continue
                    kept_anchors.append(marker.anchor_index)
                    scheduled_diagrams += 1
                    # 用户没指定类型时不让标记类型绑架选型:交给权重 + 规划器判断 2D/3D。
                    planned_kind = explicit_requested or ""
                    task = asyncio.create_task(research_diagrams.plan_diagram_auto(
                        diagram_question or prompt, "".join(answer),
                        excerpt_items, planned_kind, "main", strict=False,
                        local_hint=True))
                    diagram_tasks.append((marker, task))
                for item in list(diagram_tasks):
                    marker, task = item
                    if not task.done():
                        continue
                    diagram_tasks.remove(item)
                    try:
                        diagram = task.result()
                    except Exception:  # noqa: BLE001
                        diagram = None
                    if diagram:
                        pending_verify.append((marker, diagram, asyncio.create_task(
                            _diagram_verified(
                                diagram_question or prompt,
                                "".join(answer)[-800:], diagram))))
                async for frame in drain_verified():
                    yield frame
            async for frame in drain_verified(force=True):
                yield frame
            tail = markers.finish()
            if tail:
                answer.append(tail)
                yield f"data: {json.dumps(tail, ensure_ascii=False)}\n\n"
            # 模型漏标时按内容兜底:有步骤按步骤,没步骤按关键词权重扫描全文。
            # 非步骤内容若模型已经标过图,不再追加,避免同一概念堆图。
            stepwise = stepwise_hint or research_diagrams.is_step_text("".join(answer))
            remaining = research_diagrams.MAX_DIAGRAMS - scheduled_diagrams
            if remaining > 0 and diagram_allowed and (
                    scheduled_diagrams == 0 or stepwise):
                covered = list(kept_anchors)
                segments = research_diagrams.select_segments(
                    diagram_question or prompt, "".join(answer), covered, remaining)
                for index, segment in enumerate(segments, start=1):
                    marker = research_diagrams.DiagramMarker(
                        anchor_id=f"{markers.request_id}-auto-{index}",
                        kind=segment.kind,
                        anchor_index=segment.anchor_index)
                    auto_context[marker.anchor_id] = segment.text
                    kept_anchors.append(marker.anchor_index)
                    task = asyncio.create_task(research_diagrams.plan_diagram_auto(
                        diagram_question or prompt, segment.text,
                        excerpt_items, segment.kind, "main", strict=False))
                    diagram_tasks.append((marker, task))
            if diagram_tasks:
                results = await asyncio.gather(*(
                    asyncio.wait_for(task, timeout=DIAGRAM_TIMEOUT)
                    for _marker, task in diagram_tasks
                ), return_exceptions=True)
                for (marker, _task), diagram in zip(diagram_tasks, results):
                    if isinstance(diagram, dict):
                        if not await _diagram_verified(
                                diagram_question or prompt,
                                auto_context.get(marker.anchor_id, ""), diagram):
                            diagram_metrics.record("drop", False, "verify")
                            continue
                        frame = diagram_frame(diagram, marker)
                        if frame:
                            yield frame
        if verify:
            # 解答者与复核者错开模型保证独立:deep 解答 → main 复核;main 解答 → deep 复核
            vrole = "main" if role == "deep" else rag.llm.pick("deep")
            verdict = await _verify_answer(prompt, "".join(answer), vrole, zh)
            if verdict:
                if zh:
                    label = {"correct": "正确", "wrong": "有误",
                             "uncertain": "需人工复核"}.get(verdict["verdict"], "需人工复核")
                    prefix = "复核"
                else:
                    label = {"correct": "correct", "wrong": "needs correction",
                             "uncertain": "needs review"}.get(
                                 verdict["verdict"], "needs review")
                    prefix = "Review"
                log.info(f"[chat] 复核({vrole}): {label} | {len(verdict['issue'])} 字")
                correction = verdict.get("correction", "")
                if verdict["verdict"] == "wrong" and correction:
                    # 更正放在复核行之前:_clean_answer 只剥末尾复核行,更正会保留给评测
                    title = "**更正**" if zh else "**Correction**"
                    yield (f"data: {json.dumps(f'{title}\n\n{correction}', ensure_ascii=False)}\n\n")
                issue = verdict.get("issue", "")
                suffix = f":{issue}" if issue else ""
                head = f"🔍 {prefix}({vrole})" if zh else f"🔍 Review ({vrole})"
                yield f"data: {json.dumps(f'\n\n> {head}:{label}{suffix}', ensure_ascii=False)}\n\n"
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
    except asyncio.CancelledError:
        for _marker, task in diagram_tasks:
            if not task.done():
                task.cancel()
        for _marker, _diagram, task in pending_verify:
            if not task.done():
                task.cancel()
        raise
    except Exception as exc:  # noqa: BLE001 模型侧错误不区分类型,统一降级
        for _marker, task in diagram_tasks:
            if not task.done():
                task.cancel()
        for _marker, _diagram, task in pending_verify:
            if not task.done():
                task.cancel()
        log.warning(f"[chat] LLM 调用失败,降级为知识库直答: {exc}")
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


def _paper_actions_frame(actions: list[dict], request_id: str, doc_id: str) -> str:
    if not actions:
        return ""
    return "data: " + json.dumps({
        "mg_event": "paper_actions",
        "requestId": request_id,
        "docId": doc_id,
        "actions": actions,
    }, ensure_ascii=False) + "\n\n"


async def _gen_paper_llm(question: str, cmd: str | None,
                         chunks: list[tuple[rag.Chunk, float]], *,
                         history: list[dict] | None = None,
                         summary: str = "", sid: int | None = None,
                         uid: str = "", workspace: str = "research",
                         uid_for_actions: str = "", doc_id: str = "",
                         request_id: str = "",
                         excerpts: list[dict] | None = None,
                         planner_history: list[dict] | None = None):
    """论文回答与窗口动作并行:回答边生成,动作规划完成即下发 meta 帧。

    先启动回答流和动作规划两路;谁先完成就先处理谁。这样模型不会为了
    等批注规划而延迟第一个字,同时动作仍能在回答过程中到达前端。
    """
    answer = _gen_llm(
        question, cmd, chunks, history=history, role=_pick_role(question),
        verify=False, summary=summary, sid=sid, uid=uid, workspace=workspace,
        paper_mode=True, diagram_mode=True, diagram_question=question,
        diagram_excerpts=excerpts, diagram_request_id=request_id)
    iterator = answer.__aiter__()
    planner = asyncio.create_task(research_actions.plan_actions(
        uid_for_actions, doc_id, question, excerpts, planner_history))
    next_frame = asyncio.create_task(iterator.__anext__())
    actions_sent = False
    try:
        while True:
            waiting = {next_frame} if actions_sent else {next_frame, planner}
            done, _ = await asyncio.wait(
                waiting, return_when=asyncio.FIRST_COMPLETED)
            if not actions_sent and planner in done:
                actions_sent = True
                try:
                    actions = planner.result()
                except Exception as exc:  # noqa: BLE001
                    log.warning(f"[chat] 论文窗口动作规划失败(忽略): {exc}")
                    actions = []
                if actions:
                    frame = _paper_actions_frame(actions, request_id, doc_id)
                    if frame:
                        yield frame
            if next_frame not in done:
                continue
            try:
                frame = next_frame.result()
            except StopAsyncIteration:
                # 回答先结束:动作规划还没回来时等它一下,保证批注/高亮
                # 仍然在本次流结束前送达,而不是被取消。
                if not actions_sent:
                    actions_sent = True
                    try:
                        actions = await asyncio.wait_for(planner, timeout=15)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(f"[chat] 论文窗口动作规划超时/失败(忽略): {exc}")
                        actions = []
                    if actions:
                        frame = _paper_actions_frame(actions, request_id, doc_id)
                        if frame:
                            yield frame
                break
            yield frame
            next_frame = asyncio.create_task(iterator.__anext__())
    except asyncio.CancelledError:
        raise
    finally:
        if not planner.done():
            planner.cancel()
        if not next_frame.done():
            next_frame.cancel()






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
        log.warning(f"[chat] 续写失败: {exc}")
        note = ("⚠ 续写失败,请稍后重试。" if zh
                else "⚠ Continuation failed. Please try again.")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"


# 章节链接契约:[章节名](cmd://chapter/<名称>) —— 前端 MathText 渲染为可点击章节;
# 「返回」按钮 [返回](cmd://back) 由后端拼装(不经过模型,防止格式漂移)




async def _gen_nav_list(question: str):
    """章节导航:只输出教材章节划分列表(不展示内容);失败时给出明确提示"""
    emitted = False
    try:
        async for delta in rag.llm.stream_chat(_nav_system(), question[:TEXTBOOK_CAP], role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[chat] 章节导航调用失败: {exc}")
        zh = _is_chinese(question)
        text = (("⚠ 章节导航中断,以上列表可能不完整。" if emitted
                 else "⚠ 章节导航调用失败,请稍后重试。") if zh else
                ("⚠ Chapter navigation interrupted; the list above may be incomplete." if emitted
                 else "⚠ Chapter navigation failed. Please try again."))
        yield f"data: {json.dumps(text, ensure_ascii=False)}\n\n"
        return


async def _gen_nav_guide(question: str, tb: str = ""):
    """章节指引:用户点击章节后给出该章大概知识指引,末尾附「返回」按钮行;
    tb 为按会话缓存的教材文本,缓存失效时按通用知识作答该章。
    新链路(目录优先)由前端把本章切片内联在 question 里,不再重复拼缓存。"""
    prompt = question[:PROMPT_MAX]
    if tb and "<教材文本>" not in question:
        prompt += f"\n\n<教材文本>:\n{tb}"
    elif not tb and "<教材文本>" not in question:
        prompt += "\n\n(教材内容缓存已失效,请按通用知识作答该章)"
    emitted = False
    try:
        async for delta in rag.llm.stream_chat(_nav_guide_system(), prompt, role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[chat] 章节指引调用失败: {exc}")
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
        async for delta in rag.llm.stream_chat(system, body[:ATTACH_READ_CAP], role=rag.llm.pick("long"),
                                               thinking=False):
            emitted = True
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 模型侧错误统一降级,不让前端假死
        log.warning(f"[chat] 粘贴文本 LLM 调用失败,降级为接收回执: {exc}")
        if emitted:
            note = ("⚠ 文件解读中断,以上内容可能不完整。" if zh
                    else "⚠ File reading interrupted; the text above may be incomplete.")
        else:
            note = (ATTACH_FILE_ZH if zh else ATTACH_FILE_EN).format(name=name, size="—")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        return


# 公式手册第一步的澄清标记(与前端 i18n 双语模板固定子串成契约):
# 命中即走澄清分支——不检索知识库、不触发复核与问题记录收纳






async def _verify_clarify(question: str, answer: str, role: str, zh: bool = True) -> str | None:
    """澄清步骤独立复核:另一角色核查是否只询问了知识点、没有提前列出公式
    (失败返回 None,不打断澄清提问)"""
    if zh:
        system = (
            "你是公式查询手册的澄清复核员。核查以下用户请求与助手回复:"
            "回复是否只询问用户想查哪个具体知识点,没有列出任何公式、没有展开讲解。"
            "只输出一行结论(符合要求 / 不符合要求)和一句依据,不要输出其他内容。"
        )
        user = f"用户请求:{question[:300]}\n\n助手回复:\n{answer[:600]}"
    else:
        system = (
            "You are the clarification reviewer for the Formula Reference. Check the user "
            "request and the assistant reply: did the reply only ask which specific topic the "
            "user wants, without listing any formulas or explaining anything? "
            "Output one line with the conclusion (valid / invalid) and one sentence of basis, "
            "nothing else. Write in English."
        )
        user = f"User request: {question[:300]}\n\nAssistant reply:\n{answer[:600]}"
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
    zh = _is_chinese(question)
    if zh:
        system = (
            "用户正在使用「公式查询手册」,想查询某一数学领域的公式和定理。"
            "请只用一两句自然、有温度的话询问用户想查哪个具体知识点,"
            "并举该领域 3~5 个常见知识点为例;不要列出任何公式,不要展开讲解,"
            "等用户说出具体知识点后再作答。回答语言跟随用户语言。"
        )
    else:
        system = (
            "The user is using the Formula Reference and wants formulas and theorems from a "
            "mathematical area. In one or two natural sentences, ask which specific topic they "
            "want to look up and give 3-5 common examples from that area; do not list any "
            "formulas and do not explain anything yet. Answer entirely in English."
        )
    answer: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, question[:300], role="main"):
            answer.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001
        log.warning(f"[chat] 公式手册澄清调用失败,降级为静态提示: {exc}")
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
    verdict = await _verify_clarify(question, "".join(answer), vrole, zh)
    if verdict:
        log.info(f"[chat] 公式手册澄清复核({vrole}): {len(verdict)} 字")
        head = f"复核({vrole})" if zh else f"Review ({vrole})"
        yield f"data: {json.dumps(f'\n\n> 🔍 {head}: {verdict}', ensure_ascii=False)}\n\n"


# ---------- 直观解释:按需生成 + 服务端缓存 ----------

_INTUITION_TTL = 1800.0
_INTUITION_MAX = 64
# 直观解释缓存:按 (问题, 回答哈希) 命中,LRU 淘汰。属于运行期状态,留在本模块。
_INTUITION_CACHE: OrderedDict[tuple[str, str], tuple[float, str]] = OrderedDict()


async def _gen_intuition(question: str, answer: str, zh: bool):
    system = _INTUITION_SYSTEM_ZH if zh else _INTUITION_SYSTEM_EN
    user = f"要解释的问题:{question}" if zh else f"Question: {question}"
    if answer:
        user += ((f"\n\n原解答摘要(只用于理解上下文,不要复述):\n{answer[:800]}")
                 if zh else (f"\n\nAnswer excerpt (context only, do not repeat):\n{answer[:800]}"))
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(
                system, user, role=rag.llm.pick("main"), fallback=True,
                thinking=False, max_tokens=600):
            parts.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 失败不伪造内容
        log.warning(f"[chat] 直观解释生成失败: {exc}")
        note = ("⚠ 直观解释生成失败,请稍后重试。" if zh
                else "⚠ Could not generate an intuitive explanation. Please try again.")
        yield f"data: {json.dumps(note, ensure_ascii=False)}\n\n"
        return
    text = "".join(parts).strip()
    if text:
        key = (question.strip().lower(), answer[:400])
        _INTUITION_CACHE[key] = (time.monotonic(), text)
        _INTUITION_CACHE.move_to_end(key)
        while len(_INTUITION_CACHE) > _INTUITION_MAX:
            _INTUITION_CACHE.popitem(last=False)


async def intuition(request: Request) -> StreamingResponse | JSONResponse:
    """按需生成直观解释;默认命中缓存,refresh=true 时重写(用户点「换个说法」)。"""
    rec = require_auth(request)
    quota.check(str(rec.get("uid") or ""))
    body = await read_json_object(request)
    question = str(body.get("question", "")).strip()[:2000]
    answer = str(body.get("answer", "")).strip()[:4000]
    refresh = bool(body.get("refresh"))
    if not question:
        return JSONResponse({"detail": "question required"}, status_code=400)
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))
    key = (question.strip().lower(), answer[:400])
    if not refresh:
        hit = _INTUITION_CACHE.get(key)
        if hit and time.monotonic() - hit[0] < _INTUITION_TTL:
            _INTUITION_CACHE.move_to_end(key)
            return _stream_text(hit[1])
    return _sse(_gen_intuition(question, answer, _is_chinese(question)))


async def chat_stream(request: Request) -> StreamingResponse | JSONResponse:
    """聊天入口(安全外壳):认证 → 输入上限 → 限流/额度 → 路由 → 用量记账"""
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
    # 每日额度同理放在这里:问候不调用模型,不该算进当天用量。
    if prompt:
        uid = str(rec.get("uid") or rec.get("phone") or "")
        _rate_check(uid)
        quota.check(uid)

    meta = {"role": "main", "research": False, "workspace": workspace}
    resp = await _route_chat(prompt, cmd, body, rec, meta, workspace)
    if not isinstance(resp, StreamingResponse):
        return resp
    if not prompt:
        # 空 prompt 只是"新会话问候"(固定文案,不调用模型):不计入用量,
        # 否则会污染成本报表,也会白占用户当天的模型额度
        return _with_meta(resp, meta)
    resp = _meter(resp, rec, len(prompt), cmd or "", meta)
    return _with_meta(resp, meta)


async def speech_to_math(request: Request) -> StreamingResponse:
    """语音识别文本 → 数学符号转写(SSE 流式:首帧即上屏,前端逐帧替换输入框,
    不用等模型收尾,感知延迟 ≈ 首 token 时间)。
    一字未出时回放原文帧,不阻断语音输入;已输出半截则主动中断流(前端
    complete=false 回退原文,避免半截转写混进缓存);计入限流与用量统计"""
    rec = require_auth(request)
    quota.check(str(rec.get("uid") or ""))
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
            log.warning(f"[chat] 语音转写记账失败: {exc}")

    return _sse(gen())










def _feature_answer(zh: bool) -> str:
    if zh:
        return (
            "**MathGuide 学习分析 · 遗忘曲线**\n\n"
            "学习分析由服务端先计算掌握度快照,再交给模型解读;"
            "接口是 `GET /api/profile/analysis`。\n\n"
            "待复核使用艾宾浩斯曲线:\n\n"
            "$$R(t,s)=\\exp\\left(-\\frac{t}{\\tau(s)}\\right),\\quad "
            "\\tau(s)=30+15\\times(s-1)\\text{ 天}$$\n\n"
            "- `t`:距最近一次诊断的天数;`s`:当时的诊断分(1–5)。\n"
            "- `R<0.6` 进入待复核,并优先进入复习队列。\n"
            "- 遗忘只影响复习优先级,不改写原始诊断分,也不阻断前置知识门槛。\n"
            "- 已掌握/薄弱仍按原始诊断分判断;待复核是叠加标记。\n\n"
            "如果你想看自己的进度,用「学习分析」或直接说“分析我的学习进度”。"
        )
    return (
        "**MathGuide Learning Analysis · Forgetting Curve**\n\n"
        "The server computes a mastery snapshot first; the model only interprets it. "
        "Endpoint: `GET /api/profile/analysis`.\n\n"
        "Review-due uses the Ebbinghaus curve:\n\n"
        "$$R(t,s)=\\exp\\left(-\\frac{t}{\\tau(s)}\\right),\\quad "
        "\\tau(s)=30+15\\times(s-1)\\text{ days}$$\n\n"
        "- `t`: days since the last diagnosis; `s`: score 1–5.\n"
        "- `R<0.6` means review due and moves the point up the review queue.\n"
        "- Forgetting affects review priority only; it does not rewrite the raw "
        "score or block prerequisites.\n"
        "- Mastered/weak still follow the raw score; review-due is an overlay.\n\n"
        "For your own progress, use Learning Analysis or ask “analyze my learning progress”."
    )


def _point_notes_text(point) -> str:
    """把知识点摘要与要点拼成模型可引用的纯文本。"""
    parts: list[str] = []
    if point.summary:
        parts.append(point.summary)
    if point.key_points:
        parts.append("重点注意点:\n" + "\n".join(
            f"- {item}" for item in point.key_points))
    return "\n\n".join(parts)


async def _gen_point_lesson(uid: str, point_id: str, question: str, zh: bool):
    """「知识点讲解」:先主干与重点注意点,再等待用户追问。"""
    graph = diagnosis.get_graph()
    point = graph.points.get(point_id)
    if point is None:
        text = ("未找到该知识点,请返回知识图谱重新选择。"
                if zh else "Knowledge point not found. Please pick one from the graph.")
        async for frame in _frames(text):
            yield frame
        return

    notes = _point_notes_text(point)
    excerpts = ""
    if not notes:
        try:
            hits = await asyncio.to_thread(rag.search, point.name, 3)
        except Exception:  # noqa: BLE001 检索失败不影响讲解入口
            hits = []
        excerpts = "\n\n".join(
            f"【{chunk.title} · {chunk.section}】{chunk.text[:600]}"
            for chunk, _score in hits)

    prereqs = "、".join(
        graph.points[item].name for item in point.prerequisites
        if item in graph.points) or ("无" if zh else "none")
    dependents = "、".join(
        graph.points[item].name for item in graph.direct_dependents(point.id)
        if item in graph.points) or ("无" if zh else "none")

    fallback = "\n\n".join(item for item in (
        ("**" + point.name + "**"),
        notes or excerpts or ("暂无预置内容。" if zh else "No prepared content yet."),
        (f"前置知识:{prereqs};后续知识:{dependents}。"),
        ("接下来你想先听哪一部分?定义、方法,还是常见错误?"
         if zh else "Which part would you like next: the definition, the method, or common mistakes?"),
    ) if item)

    if not rag.llm.is_configured():
        async for frame in _frames(fallback):
            yield frame
        return

    if zh:
        system = (
            "你是 MathGuide 的知识点讲解助教。下面是该知识点的服务端事实,是唯一可用内容。\n"
            "要求:\n"
            "1. 先输出「主干」(3–6 条),再输出「重点注意点」(2–4 条);\n"
            "2. 首轮不展开例题、不输出图解标记;\n"
            "3. 只使用提供的事实;内容不足时明确说明,不要编造;\n"
            "4. 最后问用户想先听哪一部分,等待追问。\n\n"
            f"知识点:{point.name}({point.chapter},难度 {point.difficulty}/5)\n"
            f"前置知识:{prereqs}\n后续知识:{dependents}\n\n"
            f"主要内容:\n{notes or excerpts or '暂无预置内容'}"
        )
    else:
        system = (
            "You are MathGuide's concept tutor. The facts below are the only allowed "
            "source.\nRules:\n"
            "1. First output 'Main structure' (3-6 bullets), then 'Key cautions' "
            "(2-4 bullets);\n"
            "2. Do not expand worked examples or emit diagram markers in the first turn;\n"
            "3. Use only the supplied facts; say so when content is insufficient;\n"
            "4. End by asking which part the user wants next.\n\n"
            f"Concept: {point.name} ({point.chapter}, difficulty {point.difficulty}/5)\n"
            f"Prerequisites: {prereqs}\nUnlocks: {dependents}\n\n"
            f"Main content:\n{notes or excerpts or 'No prepared content'}"
        )
    user = question or (f"讲解知识点:{point.name}" if zh else f"Explain the concept: {point.name}")
    parts: list[str] = []
    try:
        async for delta in rag.llm.stream_chat(system, user, role="main", thinking=False):
            parts.append(delta)
            yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
    except Exception as exc:  # noqa: BLE001 模型失败降级为预置内容
        log.warning(f"[chat] 知识点讲解模型失败,降级: {exc}")
        if not parts:
            async for frame in _frames(fallback):
                yield frame


async def _gen_learning_analysis(uid: str, question: str, zh: bool):
    """「学习分析」指令:服务端算快照,模型只解读;末尾补图谱定位链接。

    数据为空或模型未配置时走确定性报告,保证指令永远可用、且不编数字。
    """
    snapshot = await asyncio.to_thread(learning_analysis.build_snapshot, uid)
    text = ""
    if snapshot.get("dataQuality") == "none" or not rag.llm.is_configured():
        text = learning_analysis.fallback_report(snapshot, zh=zh)
    else:
        system = learning_analysis.system_prompt(snapshot, zh=zh)
        user = question or ("分析我的学习进度" if zh else "Analyze my learning progress")
        parts: list[str] = []
        try:
            async for delta in rag.llm.stream_chat(
                    system, user, role="main", thinking=False):
                parts.append(delta)
                yield f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 分析失败降级为确定性报告
            log.warning(f"[chat] 学习分析模型失败,降级: {exc}")
            text = learning_analysis.fallback_report(snapshot, zh=zh)
            if parts:
                text = "\n\n" + text

    if text:
        async for frame in _frames(text):
            yield frame
    footer = learning_analysis.footer_links(snapshot, zh=zh)
    if footer:
        async for frame in _frames(footer, pace=False):
            yield frame


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
    table_row: dict | None = None
    raw_table = body.get("tableId")
    if workspace == "research" and isinstance(raw_table, str) and raw_table:
        candidate = raw_table[:64]
        try:
            table = await asyncio.to_thread(research_tables._get_table, uid, candidate)
            if table:
                table_row = table
                table_context = research_tables.context_text(table)
                table_stamp = f"{candidate}:{int(table.get('updatedAt') or 0)}"
        except Exception as exc:  # noqa: BLE001 表格校验失败不影响普通对话
            log.warning(f"[chat] 数据表上下文读取失败(忽略): {exc}")

    raw_regression = body.get("tableRegression")
    if (workspace == "research" and prompt and table_row is not None
            and isinstance(raw_regression, dict)):
        spec_hash = hashlib.sha256(json.dumps(
            raw_regression, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        table_stamp = f"{table_stamp}:reg:{spec_hash}"
        try:
            spec = research_tables._validate_regression_spec(
                table_row.get("columns") or [],
                {key: value for key, value in raw_regression.items()
                 if key != "tableUpdatedAt"})
            payload = {
                "columns": table_row.get("columns") or [],
                "rows": research_tables._resolved_analysis_rows(
                    table_row.get("columns") or [],
                    table_row.get("rows") or [],
                    table_row.get("formulas") or {}),
                "formulas": {},
                "spec": spec,
            }
            result = await analysis_client.run_analysis(payload, timeout=30.0)
            try:
                stale = (
                    raw_regression.get("tableUpdatedAt") is not None
                    and int(raw_regression.get("tableUpdatedAt"))
                    != int(table_row.get("updatedAt") or 0)
                )
            except (TypeError, ValueError):
                stale = True
            if stale:
                meta["tableChanged"] = True
            table_context = research_tables.context_text(
                table_row, _regression_summary(result, stale))
        except Exception as exc:  # noqa: BLE001 回归失败不阻断聊天
            log.warning(f"[chat] 聊天回归重算失败(忽略): {exc}")
            table_context = research_tables.context_text(
                table_row, "回归结果不可用(计算服务未安装或失败),不要自行估算。")

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
    history_hint = body.get("history") if isinstance(body.get("history"), list) else []
    zh = _answer_is_zh(question, history_hint)

    # 知识点讲解:图谱“前往”进入,首轮讲主干与注意点,不检索知识库
    if cmd == "知识点讲解" and workspace == "learn":
        meta["role"] = "main"
        point_id = str(body.get("pointId") or "")[:64]
        return _sse(_gen_point_lesson(uid, point_id, question, zh))

    # 学习分析:指令或自然语言要求时,不检索知识库,直接解读服务端快照
    analysis_request = cmd == "学习分析" or (
        cmd is None and workspace == "learn"
        and _is_learning_analysis_request(question))
    if analysis_request:
        meta["role"] = "main"
        return _sse(_gen_learning_analysis(uid, question, zh))

    # 系统能力问题(艾宾浩斯/遗忘曲线/复习优先级):按实现事实回答,禁止自由发挥
    if workspace == "learn" and cmd is None and _is_feature_question(question):
        meta["role"] = "main"
        return _stream_text(_feature_answer(zh))

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

    # 当前论文问答:论文已经解析入库,只用本地正文作答。
    # 不能再走外部文献检索:附件/阅读器里提问时第三方源不可达或限额,
    # 会把「论文已读完」的问题误答成「网络/限额无法查询」。
    if workspace == "research" and paper_id:
        ctx = await asyncio.to_thread(
            research_corpus.paper_context, uid, paper_id, question,
            6, PAPER_CONTEXT_CHARS)
        excerpts = (ctx or {}).get("chunks") or []
        if not excerpts:
            return _stream_text(
                "未能从当前论文中提取到可用正文,暂时无法基于全文作答。"
                "请确认 PDF 有文字层后重新导入。"
                if zh else
                "No readable text was extracted from the current paper, so I cannot "
                "answer from its full text. Please re-import a PDF with a text layer.")
        paper_title = str((ctx or {}).get("title") or "当前论文")
        paper_chunks = [
            (rag.Chunk(
                f"{paper_id}:{i}", paper_title, "",
                f'第 {item["pageStart"]}-{item["pageEnd"]} 页 · {item["section"]}',
                item["text"]), 9.0)
            for i, item in enumerate(excerpts, 1)
        ]
        if table_context:
            paper_chunks.append(
                (rag.Chunk("research-table", "研究数据表", "",
                           "用户当前数据表(数值以此为准)", table_context), 7.0))
        # 用户要求“先入库”:只处理当前用户、当前论文,临时论文转正式,
        # 入库后与论文库论文完全同权(检索、阅读、批注、项目归属、导出)。
        if _is_import_request(question):
            imported = None
            try:
                doc = await asyncio.to_thread(
                    research_corpus.get_live_doc, uid, paper_id)
                if doc:
                    status = str(doc.get("status") or "")
                    if status == "temp":
                        await asyncio.to_thread(
                            research_corpus.import_temp_doc, uid, paper_id)
                        status = "imported"
                    imported = {
                        "docId": paper_id,
                        "title": paper_title,
                        "status": status,
                    }
            except Exception as exc:  # noqa: BLE001 入库失败要如实告知
                log.warning(f"[chat] 论文入库失败: {exc}")
                imported = {
                    "docId": paper_id, "title": paper_title,
                    "status": "failed", "reason": str(exc)[:200],
                }
            if imported:
                meta["paperImported"] = imported
                if imported["status"] == "imported":
                    paper_chunks.append((rag.Chunk(
                        "paper-import", "系统状态", "",
                        "文档状态",
                        "这篇论文已经正式入库,具备论文库论文的全部功能:"
                        "可在研究档案中打开、全文检索、批注、关联研究项目。"), 10.0))
        meta["role"] = _pick_role(question)
        sid = valid_session_id(body.get("sessionId"))
        history = _validated_history(body.get("history"))
        request_id = secrets.token_hex(8)
        if rag.llm.is_configured():
            summary = get_summary(uid, sid, workspace=workspace) if sid is not None else ""
            # 回答与论文窗口动作并行:先出字,动作规划完成后再补发事件帧。
            return _sse(_gen_paper_llm(
                question, cmd, paper_chunks, history=history, summary=summary,
                sid=sid, uid=uid, workspace=workspace,
                uid_for_actions=uid, doc_id=paper_id, request_id=request_id,
                excerpts=excerpts, planner_history=history))
        # 未配置模型:至少做本地定位,再把直答内容返回。
        try:
            actions = await research_actions.plan_actions(
                uid, paper_id, question, excerpts, history)
        except Exception as exc:  # noqa: BLE001
            log.warning(f"[chat] 论文窗口动作规划失败(忽略): {exc}")
            actions = []
        if actions:
            meta["paperActions"] = actions
            meta["paperRequestId"] = request_id
        return _stream_text(_compose_direct(question, paper_chunks))

    # P0/P1 路由:研究型提问优先于知识直答
    # (「泰勒展开的最新研究进展」虽命中知识库,意图是查文献 → 走跨论文库深度搜索)
    # 必须先判意图、后检索:深度搜索内部自会检索知识库,
    # 这里若先检一遍,研究型提问就要白付一份 embedding 开销(结果还被丢掉)
    # 只允许科学研究工作区进入该链路:学习辅助区不跨区查文献
    # 数据表上下文(带 tableId)也一并由此进入研究链路;未配模型时走下面的来源列表。
    # 不要再为"直答也带表"另开分支:那条分支在本函数里不可达,已于 2026-11-14 删除。
    if workspace == "research" and (
            table_context or rag.route.is_research_intent(question)):
        meta["research"] = True
        # 搜索范围(前端勾选的平台;缺省/空 = 全平台);非法名白名单校验在 deep_search 内
        scope = _clean_scope(body.get("sources"))
        ck = _research_cache_key(question, scope,
                                 f"{uid}|{research_corpus.corpus_stamp(uid)}|"
                                 f"{paper_id}|{table_stamp}|"
                                 f"diagrams={_diagram_requested(body)}")
        cached = _RESEARCH_ANSWER.get(ck)
        if cached and time.monotonic() - cached[0] < _RESEARCH_TTL:
            _RESEARCH_ANSWER.move_to_end(ck)  # 命中即刷新 LRU 顺序
            log.info(f"[chat] 研究综合缓存命中(问题 {len(question)} 字)")
            meta["role"] = "deep"
            return _stream_text(cached[1])
        outcome = await rag.research.deep_search(question, top_k=3, scope=scope)
        # 用户自己的论文库排在外部来源之前:个人语料与问题最对口,
        # 也是引用页码的唯一来源。语料库为空时行为不变。
        try:
            local = await asyncio.to_thread(
                research_corpus.chat_hits, uid, question, 4, paper_id or None)
        except Exception as exc:  # noqa: BLE001 语料检索失败不阻断外部检索
            log.warning(f"[chat] 科研语料检索失败(继续外部来源): {exc}")
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
                question, outcome, zh, ck=ck, extra=table_context,
                diagrams=_diagram_requested(body),
                request_id=secrets.token_hex(8)))
        return _stream_text(_research_reply(outcome, zh))

    # 追问的检索词带上上一轮用户问题;只影响检索,不改发给模型的 prompt
    history = _validated_history(body.get("history"))
    retrieval_query = _retrieval_query(question, history)
    # 检索含 embedding 请求(同步、冷启动可达数十秒)→ 线程池执行,
    # 不阻塞事件循环(否则这段等待会冻住所有并发会话)
    chunks = await asyncio.to_thread(rag.search, retrieval_query, RETRIEVAL_TOP_K)

    # 图谱知识点会话:追问仍带上摘要与要点,排在普通检索资料之前
    if workspace == "learn":
        point_id = str(body.get("pointId") or "")[:64]
        point = diagnosis.get_graph().points.get(point_id) if point_id else None
        note_text = _point_notes_text(point) if point is not None else ""
        if point is not None and note_text:
            chunks = [(rag.Chunk(
                f"point:{point.id}", point.name, "", point.chapter,
                note_text), 9.0)] + chunks

    # 科研区:无论是否命中研究意图,都先查用户自己的论文库。
    # 个人论文是私有且最对口的证据,排在公共知识库之前进入上下文。
    if workspace == "research":
        try:
            local = await asyncio.to_thread(
                research_corpus.chat_hits, uid, question, 4, paper_id or None)
        except Exception as exc:  # noqa: BLE001 语料检索失败不影响主链路
            log.warning(f"[chat] 科研语料检索失败(继续公共知识库): {exc}")
            local = []
        if local:
            chunks = [
                (rag.Chunk(h["nodeId"], h["docName"], "",
                           f'{h["section"]} · 第 {h["pageStart"]}-{h["pageEnd"]} 页',
                           h.get("text") or h["snippet"]), 6.0)
                for h in local
            ] + chunks

    if rag.llm.is_configured():
        # 双角色验证仅对数学题(命中知识库或题目措辞)开启;闲聊不浪费复核调用。
        # 公式手册第二步(上一条用户消息带澄清标记)强制开启:公式定理作答必须有独立复核
        role = _pick_role(question)
        meta["role"] = role
        # 评测可显式传 temperature=0 固定随机性;普通请求不传,沿用平台默认
        raw_temperature = body.get("temperature")
        temperature = (
            min(2.0, max(0.0, float(raw_temperature)))
            if isinstance(raw_temperature, (int, float)) and not isinstance(raw_temperature, bool)
            else None
        )
        sid = valid_session_id(body.get("sessionId"))
        verify = bool(chunks) or rag.is_math_question(question) or _is_formula_followup(history)
        summary = get_summary(uid, sid, workspace=workspace) if sid is not None else ""
        diagram_allowed = not research_diagrams.diagram_suppressed(
            question, history)
        return _sse(_gen_llm(
            question, cmd, chunks, history=history, role=role, verify=verify,
            summary=summary, sid=sid, uid=uid, workspace=workspace,
            diagram_mode=True, diagram_allowed=diagram_allowed,
            diagram_question=question,
            diagram_excerpts=[
                {"section": chunk.section, "text": chunk.text}
                for chunk, _score in chunks
            ],
            diagram_request_id=secrets.token_hex(8),
            temperature=temperature))
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
