"""图解标记流与结构化 schema:服务端只负责剥标记、校验、发事件。"""
from __future__ import annotations

import ast
import asyncio
import base64
import json
import math
import os
import re
import sys
import time
from array import array
from dataclasses import dataclass

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

import analysis_client
import diagram_alerts
import diagram_metrics
import diagram_taxonomy as taxonomy
import linear_algebra
import research_corpus as rc
import research_tables
from auth import require_auth
from http_utils import read_json_object
from rag import llm
from rate_limit import SlidingWindowLimiter

PREFIX = "[[MG_DIAGRAM:"
_MARKER_RE = re.compile(r"\[\[MG_DIAGRAM:(?:type=)?([a-z0-9_]+)\]\]")
MAX_DIAGRAMS = 2  # 单条回答最多两张图:图解是论据,不是配图册
_MAX_SURFACE_GRID = 101
_CURVE_SAMPLES = 1600
_TYPES = {"tree", "relation", "flow", "geometry2d", "plot2d",
          "geometry3d", "surface3d"}

# ---- GeoGebra 引擎(非商用嵌入)----
GEO_TYPES = {"geogebra2d", "geogebra3d"}
GEO_MAX_COMMANDS = 30
GEO_MAX_COMMAND_CHARS = 200
_GEO_FORBIDDEN = (
    "execute", "javascript", "setvalue", "startanimation", "play(",
    "delete", "rename", "setperspective", "zoomin", "zoomout", "pan(",
    "image", "text(", "text[", "http", "://", "export", "save", "open(", "load(",
    "script", "setactiveview", "setcoordsystem",
)
_GEO_COMMANDS_2D = {
    "point", "segment", "line", "ray", "vector", "circle", "ellipse",
    "polygon", "curve", "function", "tangent", "intersect", "derivative",
    "integral", "root", "extremum", "solve", "nsolve", "angle", "distance",
    "midpoint", "perpendicular", "parallel", "normal", "intersection",
}
_GEO_COMMANDS_3D = _GEO_COMMANDS_2D | {
    "surface", "plane", "sphere", "cube", "cylinder", "cone", "prism",
    "pyramid", "tetrahedron", "octahedron", "icosahedron", "dodecahedron",
    "curve", "polygon", "intersect",
}


def _geo_command_name(command: str) -> str | None:
    # 函数定义 f(x)=... 不是命令调用,交给简单赋值分支处理
    if re.match(r"^[A-Za-z]\w*\s*\([^)]*\)\s*=", command):
        return None
    match = re.match(r"^(?:[A-Za-z]\w*\s*=\s*)?([A-Za-z]\w*)\s*\(", command)
    return match.group(1).lower() if match else None


def validate_geogebra(raw: object) -> dict | None:
    """校验模型生成的 GeoGebra 命令:只允许白名单命令与简单赋值/函数定义。"""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind not in GEO_TYPES:
        return None
    commands = raw.get("commands")
    if not isinstance(commands, list) or not 1 <= len(commands) <= GEO_MAX_COMMANDS:
        return None
    allowed = _GEO_COMMANDS_2D if kind == "geogebra2d" else _GEO_COMMANDS_3D
    clean: list[str] = []
    for item in commands:
        if not isinstance(item, str):
            return None
        command = item.strip()
        if not command or len(command) > GEO_MAX_COMMAND_CHARS:
            return None
        if "\n" in command or "\r" in command or ";" in command:
            return None
        lowered = command.lower()
        if any(token in lowered for token in _GEO_FORBIDDEN):
            return None
        name = _geo_command_name(command)
        if name is not None:
            if name not in allowed:
                return None
        elif not re.match(
                r"^[A-Za-z]\w*\s*(?:\([^)]*\))?\s*(?::=|:|=)\s*\S",
                command):
            return None
        clean.append(command)
    result: dict = {
        "schemaVersion": DIAGRAM_SCHEMA_VERSION,
        "type": kind,
        "commands": clean,
        "nodes": [],
        "edges": [],
        "shapes": [],
        "annotations": [],
    }
    title = _text(raw.get("title"), 200)
    if title:
        result["title"] = title
    return result
DIAGRAM_SCHEMA_VERSION = 1
_SHAPES = {"point", "segment", "line", "vector", "circle", "ellipse",
           "polygon", "curve", "axis", "plane", "sphere", "box", "cone",
           "cylinder", "surface", "parametric_surface", "implicit_surface",
           "implicit_curve", "implicit_curve3d", "parametric_curve",
           "tangent"}
_MAX_NODES = 40
_MAX_EDGES = 80
_MAX_SHAPES = 100
_MAX_ANNOTATIONS = 40
_MAX_COORD = 1e4
MAX_TOTAL_POINTS = 30000
MAX_TOTAL_BYTES = 4_000_000  # 隐式曲面网格带 positions/indices,预算比纯点列高
_PLANNER_CONCURRENCY = 3
_PLANNER_BREAKER_THRESHOLD = 5
_PLANNER_BREAKER_COOLDOWN = 30.0

_planner_semaphore: asyncio.Semaphore | None = None
_planner_failures = 0
_planner_open_until = 0.0


def _planner_gate() -> asyncio.Semaphore:
    global _planner_semaphore
    if _planner_semaphore is None:
        _planner_semaphore = asyncio.Semaphore(_PLANNER_CONCURRENCY)
    return _planner_semaphore


def _breaker_open() -> bool:
    return time.monotonic() < _planner_open_until


def _breaker_success() -> None:
    global _planner_failures, _planner_open_until
    _planner_failures = 0
    _planner_open_until = 0.0


def _breaker_failure() -> None:
    global _planner_failures, _planner_open_until
    _planner_failures += 1
    if _planner_failures >= _PLANNER_BREAKER_THRESHOLD:
        _planner_failures = 0
        _planner_open_until = time.monotonic() + _PLANNER_BREAKER_COOLDOWN
        diagram_alerts.schedule("breaker_open")


def reset_planner_breaker() -> None:
    """测试与进程内重置用;正常请求不调用。"""
    global _planner_semaphore, _planner_failures, _planner_open_until
    _planner_semaphore = None
    _planner_failures = 0
    _planner_open_until = 0.0


def diagram_cost(diagram: dict) -> tuple[int, int]:
    """返回 (总点数, 序列化字节数),用于单条回答的总预算。"""
    points = 0
    for shape in diagram.get("shapes") or []:
        if isinstance(shape, dict) and isinstance(shape.get("points"), list):
            points += len(shape["points"])
    try:
        size = len(json.dumps(
            diagram, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        size = MAX_TOTAL_BYTES + 1
    return points, size

# 用户明确说出的表示方式优先于模型自选类型:要三维就画三维,不要改画思维导图。
_3D_SURFACE_RE = re.compile(
    r"曲面|梯度|切平面|等高线|抛物面|双曲面|锥面|椭球面|z\s*=\s*f\s*\(|"
    r"surface|gradient", re.IGNORECASE)
_3D_RE = re.compile(
    r"三维|3d|3-d|立体|空间向量|空间曲面|three[- ]?dimensional", re.IGNORECASE)
_GEO3D_SURFACE_DEFER_RE = re.compile(
    r"曲面|梯度|等高线|抛物面|双曲面|锥面|椭球面|z\s*=\s*f\s*\(|"
    r"surface|gradient", re.IGNORECASE)
_2D_GEOMETRY_RE = re.compile(
    r"二维几何|平面几何|平面图形|二维图", re.IGNORECASE)
_PLOT_RE = re.compile(
    r"函数图像|函数曲线|曲线图|plot|graph of|y\s*=|f\s*\(", re.IGNORECASE)
_FLOW_RE = re.compile(
    r"流程|步骤图|推导链|因果链|流程图|flow ?chart", re.IGNORECASE)


def explicit_types(question: str) -> list[str]:
    """收集用户原话中明确要求的表示方式;出现多种即为分步混排。"""
    text = question or ""
    found: list[str] = []
    if _3D_SURFACE_RE.search(text):
        found.append("surface3d")
    elif _3D_RE.search(text):
        found.append("geometry3d")
    if _2D_GEOMETRY_RE.search(text):
        found.append("geometry2d")
    if _PLOT_RE.search(text):
        found.append("plot2d")
    if _FLOW_RE.search(text):
        found.append("flow")
    return list(dict.fromkeys(found))


def explicit_type(question: str) -> str | None:
    """只有用户明确要求且只要求一种表示方式时才覆盖模型选型。
    同时要求 2D/3D/流程时是在描述一整套分步图解,应保留每一步自己的类型。"""
    found = explicit_types(question)
    return found[0] if len(found) == 1 else None


@dataclass
class DiagramSegment:
    text: str
    anchor_index: int
    kind: str
    score: float
    importance: float = 0.0


# 形式权重网在 diagram_taxonomy.py;这里只做段落级评分与阈值判断。
_STEP_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十0-9]+步|[0-9]+[.、)]|首先|其次|然后|最后|接着|下一步)",
    re.MULTILINE,
)
_STEP_INLINE_RE = re.compile(
    r"第[一二三四五六七八九十0-9]+步|首先|其次|然后|最后|接着|下一步")
_STEP_LABEL_RE = re.compile(
    r"^\s*(?:第[一二三四五六七八九十0-9]+步|[0-9]+[.、)]|首先|其次|然后|"
    r"最后|接着|下一步)\s*[:：、.]?\s*")
_GREETING_RE = re.compile(r"^(你好|您好|谢谢|感谢|再见|hi|hello|thanks)", re.I)
_MATH_RE = re.compile(r"[∫∑∂∇√±≤≥≠≈∞πθλσμΔ_]|[=<>^]|\\frac")
_CONTINUATION_RE = re.compile(
    r"^\s*(?:它|他|她|这|该|其|此|上式|前式|由此|据此|代入|整理|化简|"
    r"两边|进而|从而|于是|同样|同理|把(?:它|其|这|这个))")
_ACTION_RE = re.compile(
    r"定义|计算|求|令|设|画|比较|展开|代入|整理|化简|验证|判断|"
    r"说明|得到|推出|证明|选取|构造|分析|估计|积分|求导|写出")
_DEFINITION_RE = re.compile(r"定义|称为|是指|指的是|记作|表示为|就是")
_CONCLUSION_RE = re.compile(
    r"因此|所以|总之|综上|结论|本质|关键|核心|总结|规律|重要|意味着")


def _step_slices(body: str) -> list[tuple[int, int]]:
    """把同一段里的“首先/然后/最后”拆成独立步骤;不足两个标记就整段返回。"""
    marks = list(_STEP_INLINE_RE.finditer(body))
    if len(marks) < 2:
        return [(0, len(body))]
    slices: list[tuple[int, int]] = []
    for index, mark in enumerate(marks):
        start = 0 if index == 0 else mark.start()
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        if end > start:
            slices.append((start, end))
    return slices


def is_step_text(text: str) -> bool:
    return bool(_STEP_RE.search(text or "")
                or re.search(r"一步一步|逐步|分步|按步骤", text or ""))


def anchor_allowed(anchor: int, text: str, kept: list[int],
                   min_gap: int = 400) -> bool:
    """非步骤内容避免同主题连续堆图;步骤内容允许逐步紧挨。"""
    if is_step_text(text):
        return True
    return all(abs(anchor - other) >= min_gap for other in kept)


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _topic_terms(question: str, text: str) -> list[str]:
    """全文关键词:问题里的主题词辐射到每个段落,而不是只看单段。"""
    return taxonomy.terms_in_text(question, text)


def score_segment(
    text: str, topic_terms: tuple[str, ...] = (),
    prefer_visual: bool = False,
) -> tuple[str, float]:
    """给一段文本打分:返回最合适的图解类型与“是否值得画”的总分。"""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return "", 0.0
    decision = taxonomy.choose_visual(clean)
    scores = decision.scores
    is_step = bool(_STEP_RE.search(clean))
    if is_step:
        scores["flow"] += 2.0
    kind = max(scores, key=lambda item: scores[item])
    if prefer_visual and kind in ("flow", "relation", "tree"):
        visual = max(
            ((name, scores[name]) for name in
             ("plot2d", "geometry2d", "surface3d", "geometry3d")),
            key=lambda item: item[1],
        )
        if visual[1] >= 2.0:
            kind = visual[0]
    total = scores[kind]
    total += min(2.0, 0.15 * sum(
        1 for term in topic_terms if term and term in clean))
    length = len(clean)
    # 步骤本身往往很短,不能因为短就判为“不值得画”;非步骤文本才用长度降权。
    # 但强视觉关键词(梯度/曲面/函数图像等)本身就是画图理由,短也不降权。
    strong_visual = scores[kind] >= 3.0
    if is_step:
        if length < 6:
            total -= 2.0
    elif not strong_visual:
        if length < 25:
            total -= 2.5
        elif length < 60:
            total -= 1.5
    if _GREETING_RE.search(clean):
        total -= 8.0
    if not re.search(r"[一-鿿A-Za-z]", clean):
        total -= 5.0
    return (kind if total > 0 else ""), round(total, 2)


def importance_score(
    text: str, topic_terms: tuple[str, ...] = (),
) -> float:
    """段落对整篇回答的重要度,用于非步骤内容的选图排序。
    步骤不走这个分数,步骤只看“是否独立可单画”,且保持原顺序。"""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean or _GREETING_RE.search(clean):
        return 0.0
    decision = taxonomy.choose_visual(clean)
    rich = sum(sorted(decision.scores.values(), reverse=True)[:2])
    score = min(5.0, rich * 0.55)
    score += min(2.0, 0.25 * len(_MATH_RE.findall(clean)))
    if _CONCLUSION_RE.search(clean):
        score += 1.5
    if _DEFINITION_RE.search(clean):
        score += 1.2
    score += min(2.0, 0.15 * sum(
        1 for term in topic_terms if term and term in clean))
    length = len(clean)
    if length < 25:
        score -= 2.0
    elif length < 60:
        score -= 0.8
    if not re.search(r"[一-鿿A-Za-z]", clean):
        score -= 5.0
    return round(max(0.0, score), 2)


def _step_body(text: str) -> str:
    return _STEP_LABEL_RE.sub("", re.sub(r"\s+", " ", text or "").strip())


def step_independence(text: str) -> float:
    """判断一个步骤截断后能否独立成图。
    不是给步骤排序:分数低表示它依赖上一步/只是片段,应并入相邻步骤。"""
    clean = _step_body(text)
    if not clean:
        return 0.0
    decision = taxonomy.choose_visual(clean)
    top = sorted(decision.scores.values(), reverse=True)
    score = 1.0
    if _MATH_RE.search(clean):
        score += 0.8
    if top and top[0] >= 2.0:
        score += 0.7
    if _DEFINITION_RE.search(clean) or _CONCLUSION_RE.search(clean):
        score += 0.5
    if _ACTION_RE.search(clean) and len(clean) >= 14:
        score += 0.5
    if _CONTINUATION_RE.search(clean) and len(clean) < 40:
        score -= 1.2
    if len(clean) < 12:
        score -= 1.5
    elif len(clean) >= 35:
        score += 0.3
    return round(max(0.0, score), 2)


def visual_cue_score(text: str) -> float:
    """排除流程加分后的纯视觉证据:没有可画的几何/曲线/关系,就不要硬画。"""
    decision = taxonomy.choose_visual(text)
    return max((score for kind, score in decision.scores.items()
                if kind != "flow"), default=0.0)


def _key_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for cues in taxonomy.VISUAL_CUES.values():
        for word in cues:
            if word and word in text:
                tokens.add(word)
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*", text or ""):
        tokens.add(match.group().lower())
    for match in re.finditer(r"\d+(?:\.\d+)?", text or ""):
        tokens.add(match.group())
    return tokens


def step_relatedness(previous: str, current: str) -> float:
    """相邻步骤的语义承接度:高 = 当前步骤主要是上一步的延续/代入/整理。
    用来决定合并,而不是排序。"""
    prev = _step_body(previous)
    curr = _step_body(current)
    if not prev or not curr:
        return 0.0
    prev_tokens = _key_tokens(prev)
    curr_tokens = _key_tokens(curr)
    shared = len(prev_tokens & curr_tokens) / max(1, len(curr_tokens))
    score = shared
    if _CONTINUATION_RE.search(curr):
        score += 0.55
    if re.match(r"^\s*(它|这|该|此|其)", curr):
        score += 0.15
    if len(curr) < 18 and re.match(r"^\s*(再|然后|接着)", curr):
        score += 0.15
    prev_type = taxonomy.choose_visual(prev).kind
    curr_type = taxonomy.choose_visual(curr).kind
    if prev_type and prev_type == curr_type and curr_type != "flow":
        score += 0.12
    if visual_cue_score(curr) >= 2.0 and not (curr_tokens & prev_tokens):
        # 当前步骤引入了全新的关键视觉对象,即使很短也值得单独成图。
        score -= 0.35
    if len(curr) < 15 and not (curr_tokens - prev_tokens):
        score += 0.1
    return round(max(0.0, min(1.0, score)), 2)


def wants_visual(question: str) -> bool:
    return bool(re.search(r"画|图示|图解|可视化|图像|示意图", question or ""))


_META_RE = re.compile(
    r"系统能做什么|能做什么|有什么功能|功能介绍|介绍一下.*系统|系统介绍|"
    r"你是谁|怎么使用|使用说明|help|what can you do", re.IGNORECASE)
_RELATION_QUESTION_RE = re.compile(
    r"关系|之间|区别|联系|推出|蕴含|等价|条件|强弱|依赖|哪一个更", re.IGNORECASE)
_ANALOGY_RE = re.compile(
    r"类比|比喻|实体化|画图|图示|几何直观|可视化|想象成", re.IGNORECASE)
# 用户明确说“先不要画图”时,服务端不能再用模型漏标兜底或标记闸门把图补回来。
_NO_DIAGRAM_RE = re.compile(
    r"(?:先|暂时|这次|本轮|本次|今天)?\s*"
    r"(?:不要|不用|不需要|不必|无需|别|不)\s*"
    r"(?:再|先|急着|用)?\s*"
    r"(?:画|生成|出|配|做|给|用|展示)?\s*"
    r"(?:图|图解|图示|图像|示意图|思维导图|可视化)"
    r"|(?:不要|不用|别|无需)\s*(?:再|先)?\s*(?:画|生成|配|做)"
    r"(?:了|吧|啦)?(?=\s|$|[，。,.!?])"
    r"|\b(?:do not|don't|dont|no need to|without|skip)\s+"
    r"(?:draw|drawing|generate|show|include|using)?\s*"
    r"(?:a\s+)?(?:diagram|figure|graph|chart|visuali[sz]ation)\b",
    re.IGNORECASE,
)
_DRAW_AGAIN_RE = re.compile(
    r"(?:可以|现在|继续|开始|还是|重新|恢复|请|帮我)?\s*"
    r"(?:画|生成|出|做|配|给)\s*(?:一?张|个)?\s*"
    r"(?:三维|3d|二维|2d|立体|函数|曲线|几何|流程|思维导图|关系)?\s*"
    r"(?:图|图解|图示|图像|示意图)"
    r"|\b(?:draw|show|generate|include)\s+(?:a\s+)?"
    r"(?:diagram|figure|graph|chart)\b"
    r"|(?:用|来)\s*(?:一?张|个)?\s*"
    r"(?:三维|3d|二维|2d|立体|函数|曲线|几何|流程|思维导图|关系)?\s*"
    r"(?:图|图解|图示|图像|示意图)",
    re.IGNORECASE,
)


def _diagram_message_state(text: str) -> bool | None:
    """单条消息的画图意图:True=明确不要,False=明确要,None=没提。
    同一条消息里“不要画思维导图,画三维图”以后半句为准。"""
    body = text or ""
    negative = _NO_DIAGRAM_RE.search(body)
    positive = _DRAW_AGAIN_RE.search(body)
    if positive and (not negative or positive.start() > negative.end()):
        return False
    if negative:
        return True
    if positive:
        return False
    return None


def diagram_suppressed(
    question: str,
    history: list[dict] | None = None,
) -> bool:
    """本轮是否被用户明确要求不画图;最近的明确指令优先,直到用户恢复。"""
    state = _diagram_message_state(question)
    if state is not None:
        return state
    for item in reversed(history or []):
        if item.get("role") != "user":
            continue
        state = _diagram_message_state(str(item.get("content") or ""))
        if state is not None:
            return state
    return False


def is_meta_question(question: str) -> bool:
    """寒暄/系统介绍/功能列表不是知识点,不配图。"""
    return bool(_META_RE.search(question or ""))


def is_relation_question(question: str) -> bool:
    """概念关系/推出关系题:应走 relation/flow,不要拿坐标轴当装饰。"""
    return bool(_RELATION_QUESTION_RE.search(question or ""))


def wants_analogy(question: str) -> bool:
    """用户明确要类比/实体化/画图时,允许从思维导图改为具体 2D/3D。"""
    return bool(_ANALOGY_RE.search(question or ""))


def slice_utf16(text: str, units: int) -> str:
    """按前端 UTF-16 锚点截取文本。"""
    if units <= 0:
        return ""
    return (text or "").encode("utf-16-le")[:units * 2].decode(
        "utf-16-le", errors="ignore")


# 正文对图的引用:中文任何一个"图"字(图像/切线图/如图)都算;
# 英文只认 figure/diagram/plot/graph/chart/shown,避免 "photograph" 误伤。
_DIAGRAM_REFERENCE_RE = re.compile(
    r"图|figure|diagram|plot|graph|chart|shown|illustrat", re.IGNORECASE)


def references_diagram(prefix: str, window: int = 400) -> bool:
    """标记前这段文字是否提到了图。用于拦掉纯装饰性的图。"""
    if not prefix:
        return False
    return bool(_DIAGRAM_REFERENCE_RE.search(prefix[-window:]))


def select_segments(
    question: str,
    text: str,
    existing_anchors: tuple[int, ...] | list[int] = (),
    limit: int = 6,
) -> list[DiagramSegment]:
    """扫描整篇回答:有步骤按步骤选,没步骤按权重选高分段落。
    只返回值得画图的段落;模型没标记时由这里兜底决定画不画、画哪种。"""
    if not text or limit <= 0 or is_meta_question(question):
        return []
    if diagram_suppressed(question):
        return []
    topic_terms = tuple(_topic_terms(question, text))
    paragraphs: list[tuple[str, int, int, bool]] = []
    for match in re.finditer(r"[^\n]+(?:\n(?!\n)[^\n]+)*", text):
        raw = match.group()
        body = raw.strip()
        if not body:
            continue
        start = _utf16_len(text[:match.start()]) + _utf16_len(
            raw[:len(raw) - len(raw.lstrip())])
        anchor = _utf16_len(text[:match.end()])
        paragraphs.append((body, start, anchor, bool(_STEP_RE.search(body))))
    has_steps = any(step for _body, _start, _anchor, step in paragraphs)
    candidates: list[DiagramSegment] = []

    def consider(body: str, start: int, anchor: int) -> None:
        if any(start - 80 <= existing <= anchor + 80
               for existing in existing_anchors):
            return
        # 没有可画的几何/曲线/关系证据时不硬画;步骤标记本身不算视觉证据。
        if visual_cue_score(body) < 1.2:
            return
        kind, score = score_segment(
            body, topic_terms, prefer_visual=wants_visual(question))
        if not kind:
            return
        candidates.append(DiagramSegment(
            body, anchor, kind, score,
            importance_score(body, topic_terms)))

    if has_steps:
        # 步骤保持从头到尾的顺序;独立度只决定“并入上一步”还是“单独成图”。
        steps: list[dict] = []
        for body, start, anchor, is_step in paragraphs:
            if not is_step:
                continue
            for local_start, local_end in _step_slices(body):
                part = body[local_start:local_end].strip()
                if not part:
                    continue
                steps.append({
                    "text": part,
                    "start": start + _utf16_len(body[:local_start]),
                    "anchor": start + _utf16_len(body[:local_end]),
                    "indep": step_independence(part),
                })
        if not steps:
            return []
        # 开头就是“把它代入”这类依赖片段:并入下一步,而不是单独画。
        while (len(steps) > 1
               and visual_cue_score(steps[0]["text"]) < 1.2
               and step_relatedness(steps[0]["text"],
                                    steps[1]["text"]) >= 0.65):
            first = steps.pop(0)
            steps[0]["text"] = f"{first['text']} {steps[0]['text']}"
            steps[0]["start"] = first["start"]
        groups: list[dict] = []
        for step in steps:
            related = (groups and step_relatedness(
                groups[-1]["text"], step["text"]) >= 0.65)
            if related and groups:
                previous = groups[-1]
                previous["text"] = f"{previous['text']} {step['text']}"
                previous["anchor"] = step["anchor"]
            else:
                groups.append(dict(step))
        # 步骤不要过细:超过软上限时,优先把承接度最高的一对合并,保持顺序不变。
        max_steps = min(limit, 5)
        while len(groups) > max_steps:
            index = max(
                range(len(groups) - 1),
                key=lambda item: (
                    step_relatedness(groups[item]["text"],
                                     groups[item + 1]["text"]),
                    -groups[item]["indep"] - groups[item + 1]["indep"],
                ),
            )
            groups[index]["text"] = (
                f"{groups[index]['text']} {groups[index + 1]['text']}")
            groups[index]["anchor"] = groups[index + 1]["anchor"]
            groups.pop(index + 1)
        for group in groups:
            consider(group["text"], group["start"], group["anchor"])
        return candidates

    # 非步骤内容:按重要度排序,只取显著高于其他段落的点;不凑数。
    for body, start, anchor, _is_step in paragraphs:
        consider(body, start, anchor)
    if not candidates:
        return []
    top = max(candidate.importance for candidate in candidates)
    cut = max(2.0, top * 0.6)
    ranked = [candidate for candidate in candidates
              if candidate.importance >= cut]
    ranked.sort(key=lambda item: item.importance, reverse=True)
    selected: list[DiagramSegment] = []
    for candidate in ranked:
        if len(selected) >= min(limit, 4):
            break
        if all(abs(candidate.anchor_index - item.anchor_index) >= 400
               for item in selected):
            selected.append(candidate)
    selected.sort(key=lambda item: item.anchor_index)
    return selected





def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text or "")


def _text(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _num(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed if -_MAX_COORD <= parsed <= _MAX_COORD else None


def _point(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or not 2 <= len(value) <= 3:
        return None
    out = [_num(item) for item in value]
    return [item for item in out if item is not None] if all(
        item is not None for item in out) else None


_EXPR_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "arcsin": math.asin, "arccos": math.acos, "arctan": math.atan,
    "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh,
    "tanh": math.tanh, "exp": math.exp, "log": math.log,
    "ln": math.log, "lg": math.log10, "log10": math.log10,
    "sqrt": math.sqrt, "abs": abs, "pow": math.pow,
}
_EXPR_CONSTS = {"pi": math.pi, "e": math.e}


def _eval_expr(node: ast.AST, env: dict[str, float]) -> float:
    """只允许数值、x/y、四则运算和白名单函数,不执行任意代码。"""
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id in env:
            return float(env[node.id])
        if node.id in _EXPR_CONSTS:
            return float(_EXPR_CONSTS[node.id])
        raise ValueError(node.id)
    if isinstance(node, ast.UnaryOp):
        value = _eval_expr(node.operand, env)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise ValueError("op")
    if isinstance(node, ast.BinOp):
        left = _eval_expr(node.left, env)
        right = _eval_expr(node.right, env)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            # 限制的是指数大小与结果量级,不是底数:旧实现把 e^x 在 x>8 时
            # 误判成非法幂,导致曲线/tangent 采样整段失败。
            if abs(right) > 64:
                raise ValueError("pow")
            try:
                value = left ** right
            except (OverflowError, ValueError, TypeError):
                raise ValueError("pow")
            if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e12:
                raise ValueError("pow")
            return value
        if isinstance(node.op, ast.Mod):
            return left % right
        raise ValueError("op")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise ValueError("call")
        func = _EXPR_FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(node.func.id)
        return float(func(*[_eval_expr(arg, env) for arg in node.args]))
    raise ValueError("expr")


def _normalize_expr(expr: str) -> str:
    """把模型常写的 y=x^2 / LaTeX / Unicode 写法收成可安全求值的表达式。
    只做语法归一,不改变数学含义;无法识别的部分留给 AST 白名单拒绝。"""
    source = str(expr or "").strip().strip("$").strip()
    source = re.sub(
        r"^\s*(?:y|z|f\s*\(\s*x\s*(?:,\s*y\s*)?\))\s*=\s*",
        "", source, flags=re.IGNORECASE)
    source = (source.replace("π", "pi").replace("−", "-").replace("–", "-")
              .replace("×", "*").replace("·", "*").replace("⋅", "*")
              .replace("²", "^2").replace("³", "^3"))
    source = source.replace("\\cdot", "*").replace("\\times", "*")
    source = re.sub(r"\\(left|right|,|!|;|quad|qquad)", "", source)
    for name in ("arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
                 "sin", "cos", "tan", "exp", "ln", "log", "sqrt"):
        source = re.sub(rf"\\{name}\b", name, source)
    # \frac{A}{B} 可能嵌套:逐层替换,最多 4 层
    for _ in range(4):
        replaced = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}",
                          r"((\1)/(\2))", source)
        if replaced == source:
            break
        source = replaced
    source = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"sqrt(\1)", source)
    source = re.sub(r"\\mathrm\s*\{([^{}]*)\}", r"\1", source)
    source = source.replace("{", "(").replace("}", ")").replace("\\", "")
    # 隐式乘法只收窄到明确无歧义的形态:2x、2(x+1)、)(。
    source = re.sub(r"(?<=[0-9)])\s*(?=[A-Za-z(])", "*", source)
    source = source.replace("^", "**")
    return source.strip()


def _compile_xyz_expr(expr: object):
    """隐式曲面 F(x,y,z)=0:三变量白名单求值。"""
    if not isinstance(expr, str):
        return None
    source = _normalize_expr(expr)
    if not source or len(source) > 200:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    if sum(1 for _ in ast.walk(tree)) > 80:
        return None

    def run(x: float, y: float, z: float) -> float:
        value = _eval_expr(tree, {"x": x, "y": y, "z": z})
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("non-finite")
        return float(value)

    return run


def _compile_uv_expr(expr: object):
    """参数曲面分量:变量名为 u/v,仍走同一 AST 白名单。"""
    if not isinstance(expr, str):
        return None
    source = _normalize_expr(expr)
    if not source or len(source) > 200:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    if sum(1 for _ in ast.walk(tree)) > 80:
        return None

    def run(u: float, v: float) -> float:
        value = _eval_expr(tree, {"u": u, "v": v, "x": u, "y": v})
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("non-finite")
        return float(value)

    return run


def _compile_expr(expr: object, allow_y: bool = True):
    if not isinstance(expr, str):
        return None
    source = _normalize_expr(expr)
    if not source or len(source) > 200:
        return None
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return None
    if sum(1 for _ in ast.walk(tree)) > 80:
        return None
    if not allow_y and any(
            isinstance(node, ast.Name) and node.id == "y"
            for node in ast.walk(tree)):
        return None

    def run(x: float, y: float = 0.0) -> float:
        value = _eval_expr(tree, {"x": x, "y": y})
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("non-finite")
        return float(value)

    return run


def _int(value: object, default: int, low: int, high: int) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default
    return max(low, min(high, parsed))


def _domain(shape: dict) -> tuple[float, float, float, float] | None:
    raw = shape.get("domain")
    if not isinstance(raw, (list, tuple)):
        return None
    parsed = [_num(item) for item in raw]
    if any(item is None for item in parsed):
        return None
    values = [float(item) for item in parsed]
    if len(values) == 2:
        return values[0], values[1], values[0], values[1]
    if len(values) == 4:
        return values[0], values[1], values[2], values[3]
    return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _sample_curve(run, x0: float, x1: float, samples: int):
    """逐点采样并切段,返回 (点, 段列表, 收缩后的定义域或 None)。

    旧实现任一点出错就丢弃整条曲线:ln/sqrt 在定义域外会抛错,用户什么都看不到。
    现在只丢坏点,有效点少于 2 个才放弃;定义域两端无效时自动收缩。
    断点(1/x、tan)按相邻跳变切开,避免把渐近线画成实线。"""
    raw: list[list[float] | None] = []
    for i in range(samples):
        x = x0 + (x1 - x0) * i / (samples - 1)
        try:
            y = run(x)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            raw.append(None)
            continue
        raw.append([round(x, 6), round(y, 6)])
    valid = [point for point in raw if point is not None]
    if len(valid) < 2:
        return [], [], None

    first = next(i for i, point in enumerate(raw) if point is not None)
    last = len(raw) - 1 - next(
        i for i, point in enumerate(reversed(raw)) if point is not None)
    contiguous = all(point is not None for point in raw[first:last + 1])
    narrowed: list[float] | None = None
    if contiguous and (first > 0 or last < len(raw) - 1):
        # 无效点只在两端(ln/sqrt):把定义域收到有效区间,而不是整条丢弃
        narrowed = [valid[0][0], valid[-1][0]]
        valid = [point for point in valid
                 if narrowed[0] <= point[0] <= narrowed[1]]

    ys = [point[1] for point in valid]
    span_y = max(ys) - min(ys)
    diffs = [abs(valid[i + 1][1] - valid[i][1]) for i in range(len(valid) - 1)]
    step_x = (x1 - x0) / max(1, samples - 1)
    # 跳变阈值:正常相邻差分的中位数,再兜一个"整幅高度 20%"的绝对下限。
    # tan/1/x 在极点附近的跳变远大于两者,会被切开;exp 这类陡但连续的不切。
    threshold = max(_median(diffs) * 40, span_y * 0.2, 1e-9)

    segments: list[list[list[float]]] = []
    current: list[list[float]] = [valid[0]]
    for prev, cur in zip(valid, valid[1:]):
        gap = cur[0] - prev[0] > step_x * 1.5
        jump = abs(cur[1] - prev[1]) > threshold
        if gap or jump:
            if len(current) >= 2:
                segments.append(current)
            current = [cur]
        else:
            current.append(cur)
    if len(current) >= 2:
        segments.append(current)
    if not segments:
        return [], [], narrowed
    points = [point for segment in segments for point in segment]
    return points, segments, narrowed


_TETRA_EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
_TETRA_CELLS = (
    (0, 1, 3, 7), (0, 1, 5, 7), (0, 2, 3, 7),
    (0, 2, 6, 7), (0, 4, 5, 7), (0, 4, 6, 7),
)


def _encode_mesh(positions: list[float], indices: list[int]) -> dict:
    """隐式网格二进制传输:Float32 positions + Uint32 indices + base64。"""
    pos = array("f", (round(float(value), 5) for value in positions))
    index_type = "u16" if (not indices or max(indices) < 65536) else "u32"
    idx = array("H" if index_type == "u16" else "I",
                (int(value) for value in indices))
    if sys.byteorder != "little":
        pos.byteswap()
        idx.byteswap()
    return {
        "positions_b64": base64.b64encode(pos.tobytes()).decode("ascii"),
        "indices_b64": base64.b64encode(idx.tobytes()).decode("ascii"),
        "vertexCount": len(positions) // 3,
        "indexCount": len(indices),
        "indexType": index_type,
        "encoding": f"f32le/{index_type}le",
    }


def _compact_meshes(shapes: list[dict]) -> None:
    """把内部 positions/indices 压缩成二进制字段,减少 SSE 体积。"""
    for shape in shapes:
        if (shape.get("kind") == "implicit_surface"
                and isinstance(shape.get("positions"), list)
                and isinstance(shape.get("indices"), list)):
            shape.update(_encode_mesh(shape["positions"], shape["indices"]))
            shape.pop("positions", None)
            shape.pop("indices", None)


def _marching_squares(values: list[float], origin: tuple[float, float],
                      step: tuple[float, float], nx: int, ny: int
                      ) -> list[list[list[float]]]:
    """隐式曲线 F(x,y)=0 的 marching squares;输出线段列表。"""
    segments: list[list[list[float]]] = []

    def point(i: int, j: int) -> tuple[float, float]:
        return origin[0] + i * step[0], origin[1] + j * step[1]

    def cross(a: tuple[int, int], b: tuple[int, int]) -> list[float]:
        ia = a[1] * nx + a[0]
        ib = b[1] * nx + b[0]
        va, vb = values[ia], values[ib]
        if abs(va - vb) < 1e-12:
            return [*point(*a)]
        t = va / (va - vb)
        pa, pb = point(*a), point(*b)
        return [pa[0] + t * (pb[0] - pa[0]),
                pa[1] + t * (pb[1] - pa[1])]

    for i in range(nx - 1):
        for j in range(ny - 1):
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            states = [values[j * nx + i] <= 0 for i, j in corners]
            case = sum(1 << index for index, state in enumerate(states) if state)
            if case in (0, 15):
                continue
            e0 = lambda: cross(corners[0], corners[1])  # noqa: E731
            e1 = lambda: cross(corners[1], corners[2])  # noqa: E731
            e2 = lambda: cross(corners[2], corners[3])  # noqa: E731
            e3 = lambda: cross(corners[3], corners[0])  # noqa: E731
            if case == 5 or case == 10:
                center = (values[j * nx + i] + values[j * nx + i + 1]
                          + values[(j + 1) * nx + i]
                          + values[(j + 1) * nx + i + 1]) / 4
                if (center <= 0) == (case == 5):
                    segments.extend([[e3(), e2()], [e0(), e1()]])
                else:
                    segments.extend([[e3(), e0()], [e1(), e2()]])
                continue
            pairs = {
                1: (e3, e0), 2: (e0, e1), 3: (e3, e1), 4: (e1, e2),
                6: (e0, e2), 7: (e2, e3), 8: (e2, e3), 9: (e0, e2),
                11: (e1, e2), 12: (e1, e3), 13: (e0, e1), 14: (e3, e0),
            }[case]
            segments.append([pairs[0](), pairs[1]()])
    return segments


def _marching_tetra(values: list[float], origin: tuple[float, float, float],
                    step: tuple[float, float, float], shape: str
                    ) -> tuple[list[float], list[int]]:
    """隐式曲面 F=0 的 marching tetrahedra;输出扁平 positions + indices。"""
    nx, ny, nz = shape
    positions: list[float] = []
    indices: list[int] = []
    vertex_cache: dict[tuple[float, float, float], int] = {}

    def add_vertex(point: tuple[float, float, float]) -> int:
        key = (round(point[0], 5), round(point[1], 5), round(point[2], 5))
        cached = vertex_cache.get(key)
        if cached is not None:
            return cached
        if len(positions) >= 300000:
            return -1
        index = len(positions) // 3
        positions.extend(key)
        vertex_cache[key] = index
        return index

    def vertex(i: int, j: int, k: int) -> tuple[float, float, float]:
        return (origin[0] + i * step[0],
                origin[1] + j * step[1],
                origin[2] + k * step[2])

    def inside(index: int) -> bool:
        return values[index] <= 0.0

    for i in range(nx - 1):
        for j in range(ny - 1):
            for k in range(nz - 1):
                corners = [
                    (i, j, k), (i + 1, j, k), (i, j + 1, k), (i + 1, j + 1, k),
                    (i, j, k + 1), (i + 1, j, k + 1), (i, j + 1, k + 1),
                    (i + 1, j + 1, k + 1),
                ]
                corner_index = [
                    (cell[0]) * ny * nz + (cell[1]) * nz + (cell[2])
                    for cell in corners
                ]
                for tetra in _TETRA_CELLS:
                    ids = [corner_index[index] for index in tetra]
                    states = [inside(item) for item in ids]
                    count = sum(states)
                    if count in (0, 4):
                        continue

                    def cross(index_a: int, index_b: int) -> int:
                        va, vb = values[index_a], values[index_b]
                        if abs(va - vb) < 1e-12:
                            return -1
                        t = va / (va - vb)
                        ca = corners[tetra[ids.index(index_a)]]
                        cb = corners[tetra[ids.index(index_b)]]
                        point = vertex(
                            ca[0] + t * (cb[0] - ca[0]),
                            ca[1] + t * (cb[1] - ca[1]),
                            ca[2] + t * (cb[2] - ca[2]),
                        )
                        return add_vertex(point)

                    inside_ids = [ids[index] for index in range(4) if states[index]]
                    outside_ids = [ids[index] for index in range(4) if not states[index]]
                    if count == 1:
                        a = inside_ids[0]
                        points = [cross(a, b) for b in outside_ids]
                        if min(points) >= 0:
                            indices.extend([points[0], points[1], points[2]])
                    elif count == 3:
                        a = outside_ids[0]
                        points = [cross(a, b) for b in inside_ids]
                        if min(points) >= 0:
                            indices.extend([points[0], points[2], points[1]])
                    else:
                        a, b = inside_ids
                        c, d = outside_ids
                        points = [cross(a, c), cross(a, d),
                                  cross(b, d), cross(b, c)]
                        if min(points) >= 0:
                            indices.extend([points[0], points[1], points[2],
                                            points[0], points[2], points[3]])
    return positions, indices


def _sample_shape(shape: dict) -> bool:
    """服务端按表达式采样曲面/曲线,避免模型手写大量坐标出错。
    返回 False 表示这个形状没有可画数据,应丢弃。"""
    kind = shape.get("kind")
    if kind not in ("surface", "parametric_surface", "implicit_surface",
                    "implicit_curve", "implicit_curve3d", "parametric_curve",
                    "curve"):
        return True
    if kind == "implicit_curve3d":
        frun = _compile_xyz_expr(shape.get("expr"))
        grun = _compile_xyz_expr(shape.get("expr2"))
        raw_domain = shape.get("domain")
        if (frun is None or grun is None
                or not isinstance(raw_domain, (list, tuple))
                or len(raw_domain) != 6):
            return False
        parsed_domain = [_num(item) for item in raw_domain]
        if any(item is None for item in parsed_domain):
            return False
        x0, x1, y0, y1, z0, z1 = (float(item) for item in parsed_domain)
        if not (x0 < x1 and y0 < y1 and z0 < z1):
            return False
        resolution = _int(shape.get("resolution"), 24, 8, 76)
        step = ((x1 - x0) / (resolution - 1),
                (y1 - y0) / (resolution - 1),
                (z1 - z0) / (resolution - 1))
        values: list[float] = []
        try:
            for i in range(resolution):
                x = x0 + i * step[0]
                for j in range(resolution):
                    y = y0 + j * step[1]
                    for k in range(resolution):
                        z = z0 + k * step[2]
                        values.append(frun(x, y, z))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        positions, indices = _marching_tetra(
            values, (x0, y0, z0), step, (resolution, resolution, resolution))
        if not indices:
            return False
        segments: list[list[list[float]]] = []
        for triangle in range(0, len(indices) - 2, 3):
            try:
                points = [
                    (positions[indices[triangle + offset] * 3],
                     positions[indices[triangle + offset] * 3 + 1],
                     positions[indices[triangle + offset] * 3 + 2])
                    for offset in range(3)
                ]
                gvals = [grun(*point) for point in points]
            except (ValueError, ZeroDivisionError, OverflowError, TypeError,
                    IndexError):
                continue
            if all(value > 0 for value in gvals) or all(value < 0 for value in gvals):
                continue
            intersections = []
            for a, b in ((0, 1), (1, 2), (2, 0)):
                ga, gb = gvals[a], gvals[b]
                if abs(ga) < 1e-9:
                    intersections.append(points[a])
                if ga * gb < 0:
                    t = ga / (ga - gb)
                    intersections.append(tuple(
                        points[a][axis] + t * (points[b][axis] - points[a][axis])
                        for axis in range(3)))
            unique = []
            for point in intersections:
                if not any(sum((point[index] - other[index]) ** 2
                               for index in range(3)) < 1e-12 for other in unique):
                    unique.append(point)
            if len(unique) >= 2:
                segments.append([list(unique[0]), list(unique[1])])
        if not segments:
            return False
        shape["segments"] = segments
        shape["points"] = [point for segment in segments for point in segment]
        shape["resolution"] = resolution
        return True
    if kind == "parametric_curve":
        xrun = _compile_uv_expr(shape.get("xexpr"))
        yrun = _compile_uv_expr(shape.get("yexpr"))
        zrun = _compile_uv_expr(shape.get("zexpr"))
        domain = _domain(shape)
        if xrun is None or yrun is None or domain is None:
            return False
        u0, u1 = domain[0], domain[1]
        if not u0 < u1:
            return False
        samples = _int(shape.get("samples"), 240, 8, 2400)
        points: list[list[float]] = []
        try:
            for index in range(samples):
                u = u0 + (u1 - u0) * index / (samples - 1)
                point = [round(float(xrun(u, 0.0)), 6),
                         round(float(yrun(u, 0.0)), 6)]
                if zrun is not None:
                    point.append(round(float(zrun(u, 0.0)), 6))
                points.append(point)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        shape["points"] = points
        return True
    if kind == "implicit_curve":
        run = _compile_expr(shape.get("expr"), allow_y=True)
        domain = _domain(shape)
        if run is None or domain is None:
            return False
        x0, x1, y0, y1 = domain
        if not (x0 < x1 and y0 < y1):
            return False
        resolution = _int(shape.get("resolution"), 100, 20, 240)
        step_x = (x1 - x0) / (resolution - 1)
        step_y = (y1 - y0) / (resolution - 1)
        values: list[float] = []
        try:
            for j in range(resolution):
                y = y0 + j * step_y
                for i in range(resolution):
                    x = x0 + i * step_x
                    values.append(run(x, y))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        segments = _marching_squares(
            values, (x0, y0), (step_x, step_y), resolution, resolution)
        if not segments:
            return False
        shape["segments"] = segments
        shape["points"] = [point for segment in segments for point in segment]
        shape["resolution"] = resolution
        return True
    if kind == "implicit_surface":
        run = _compile_xyz_expr(shape.get("expr"))
        raw_domain = shape.get("domain")
        if run is None or not (isinstance(raw_domain, (list, tuple))
                               and len(raw_domain) == 6):
            return False
        parsed_domain = [_num(item) for item in raw_domain]
        if any(item is None for item in parsed_domain):
            return False
        x0, x1, y0, y1, z0, z1 = (float(item) for item in parsed_domain)
        if not (x0 < x1 and y0 < y1 and z0 < z1):
            return False
        resolution = _int(shape.get("resolution"), 24, 8, 76)
        step = ((x1 - x0) / (resolution - 1),
                (y1 - y0) / (resolution - 1),
                (z1 - z0) / (resolution - 1))
        values: list[float] = []
        try:
            for i in range(resolution):
                x = x0 + i * step[0]
                for j in range(resolution):
                    y = y0 + j * step[1]
                    for k in range(resolution):
                        z = z0 + k * step[2]
                        values.append(run(x, y, z))
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        positions, indices = _marching_tetra(
            values, (x0, y0, z0), step, (resolution, resolution, resolution))
        if not indices:
            return False
        shape["positions"] = positions
        shape["indices"] = indices
        shape["resolution"] = resolution
        return True
    if kind == "parametric_surface":
        xrun = _compile_uv_expr(shape.get("xexpr"))
        yrun = _compile_uv_expr(shape.get("yexpr"))
        zrun = _compile_uv_expr(shape.get("zexpr"))
        domain = _domain(shape)
        if xrun is None or yrun is None or zrun is None or domain is None:
            return False
        u0, u1, v0, v1 = domain
        if not (u0 < u1 and v0 < v1):
            return False
        rows = _int(shape.get("rows"), 25, 2, _MAX_SURFACE_GRID)
        cols = _int(shape.get("cols"), 25, 2, _MAX_SURFACE_GRID)
        sampled: list[list[float]] = []
        try:
            for i in range(rows):
                u = u0 + (u1 - u0) * i / (rows - 1)
                for j in range(cols):
                    v = v0 + (v1 - v0) * j / (cols - 1)
                    sampled.append([
                        round(float(xrun(u, v)), 6),
                        round(float(yrun(u, v)), 6),
                        round(float(zrun(u, v)), 6),
                    ])
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        shape["points"] = sampled
        shape["rows"] = rows
        shape["cols"] = cols
        return True
    points = shape.get("points")
    if isinstance(points, (int, float)):
        # 模型常把 "points" 写成采样数;把它当 samples,不要因此丢图。
        count = _num(points)
        if count is not None:
            shape["samples"] = int(count)
        shape.pop("points", None)
        points = None
    if isinstance(points, list) and points:
        return True
    run = _compile_expr(shape.get("expr"), allow_y=(kind == "surface"))
    domain = _domain(shape)
    if run is None or domain is None:
        return kind != "surface"
    x0, x1, y0, y1 = domain
    if not (x0 < x1 and y0 < y1):
        return kind != "surface"
    if kind == "surface":
        rows = _int(shape.get("rows"), 25, 2, _MAX_SURFACE_GRID)
        cols = _int(shape.get("cols"), 25, 2, _MAX_SURFACE_GRID)
        sampled: list[list[float]] = []
        try:
            for i in range(rows):
                x = x0 + (x1 - x0) * i / (rows - 1)
                for j in range(cols):
                    y = y0 + (y1 - y0) * j / (cols - 1)
                    sampled.append([round(x, 6), round(y, 6), round(run(x, y), 6)])
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return False
        shape["points"] = sampled
        shape["rows"] = rows
        shape["cols"] = cols
        return True
    samples = _int(shape.get("samples"), _CURVE_SAMPLES, 8, 3000)
    points, segments, narrowed = _sample_curve(run, x0, x1, samples)
    if len(points) < 2:
        return False
    shape["points"] = points
    if len(segments) > 1:
        # 多段(1/x、tan):前端按段绘制,不能连成一条跨渐近线的实线。
        shape["segments"] = segments
    if narrowed:
        shape["domain"] = narrowed
    return True


def _refine_gradient(shapes: list[dict]) -> None:
    """曲面 + 关键点 + 梯度向量时,用表达式数值求梯度,避免模型手估方向。"""
    surface = next((
        shape for shape in shapes
        if shape.get("kind") == "surface" and shape.get("expr")
    ), None)
    if surface is None:
        return
    run = _compile_expr(surface.get("expr"), allow_y=True)
    if run is None:
        return
    vector = next((
        shape for shape in shapes
        if shape.get("kind") == "vector" and "from" in shape and "to" in shape
        and re.search(r"梯度|∇|gradient|最陡|增长最快",
                      str(shape.get("label") or ""), re.IGNORECASE)
    ), None)
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point" and "x" in shape and "y" in shape
    ]
    start = vector.get("from") if vector else None
    if not (isinstance(start, (list, tuple)) and len(start) >= 2):
        start = [points[0]["x"], points[0]["y"]] if points else None
    if not start:
        return
    try:
        x0, y0 = float(start[0]), float(start[1])
        h = 1e-4 * max(1.0, abs(x0), abs(y0))
        gx = (run(x0 + h, y0) - run(x0 - h, y0)) / (2 * h)
        gy = (run(x0, y0 + h) - run(x0, y0 - h)) / (2 * h)
        z0 = run(x0, y0)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return
    if not all(math.isfinite(value) for value in (gx, gy, z0)):
        return
    if points:
        nearest = min(
            points,
            key=lambda item: (float(item["x"]) - x0) ** 2
            + (float(item["y"]) - y0) ** 2,
        )
        if (abs(float(nearest["x"]) - x0) <= 1e-6
                and abs(float(nearest["y"]) - y0) <= 1e-6):
            nearest["z"] = round(z0, 6)
    if vector is None:
        return
    domain = _domain(surface)
    span = min(domain[1] - domain[0], domain[3] - domain[2]) if domain else 2.0
    magnitude = math.hypot(gx, gy)
    plane = next((
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and re.search(r"切平面|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ), None)
    if plane is not None:
        plane["normal"] = [round(-gx, 6), round(-gy, 6), 1.0]
    if magnitude < 1e-9:
        shapes.remove(vector)
        return
    step = max(0.05, min(0.6, span * 0.35)) / magnitude
    dx, dy = gx * step, gy * step
    vector["from"] = [round(x0, 6), round(y0, 6), round(z0, 6)]
    vector["to"] = [
        round(x0 + dx, 6), round(y0 + dy, 6),
        round(z0 + gx * dx + gy * dy, 6),
    ]


def _refine_normal_from_solid(shapes: list[dict], normal_re: re.Pattern) -> None:
    """没有 z=f(x,y) 曲面时,用平面/球面/圆柱的几何法向修正“法向量”箭头。

    同时把箭头起点投到对应几何体表面:起点不在球面/平面上时,方向对也算错图。
    """
    planes = [
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and isinstance(shape.get("normal"), list) and len(shape["normal"]) >= 3
    ]
    spheres = [
        shape for shape in shapes
        if shape.get("kind") == "sphere"
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
        and float(shape.get("r", shape.get("radius", 0)) or 0) > 1e-9
    ]
    cylinders = [
        shape for shape in shapes
        if shape.get("kind") == "cylinder"
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
        and float(shape.get("r", shape.get("radius", 0)) or 0) > 1e-9
    ]
    solids = planes + spheres + cylinders
    if not solids:
        return

    def normal_at(solid: dict, x0: float, y0: float, z0: float):
        kind = solid.get("kind")
        if kind == "plane":
            nx, ny, nz = (float(solid["normal"][0]), float(solid["normal"][1]),
                          float(solid["normal"][2]))
            norm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm < 1e-9:
                return None
            nx, ny, nz = nx / norm, ny / norm, nz / norm
            # 有显式中心时把起点滑到平面上;没有中心时只改方向。
            if all(isinstance(solid.get(key), (int, float)) for key in ("x", "y", "z")):
                cx, cy, cz = float(solid["x"]), float(solid["y"]), float(solid["z"])
                distance = (x0 - cx) * nx + (y0 - cy) * ny + (z0 - cz) * nz
                return (nx, ny, nz), (x0 - distance * nx,
                                      y0 - distance * ny,
                                      z0 - distance * nz)
            return (nx, ny, nz), (x0, y0, z0)
        if kind == "sphere":
            cx, cy, cz = float(solid["x"]), float(solid["y"]), float(solid["z"])
            radius = float(solid.get("r", solid.get("radius", 0)))
            rx, ry, rz = x0 - cx, y0 - cy, z0 - cz
            norm = math.sqrt(rx * rx + ry * ry + rz * rz)
            if norm < 1e-9:
                return None
            nx, ny, nz = rx / norm, ry / norm, rz / norm
            return (nx, ny, nz), (cx + nx * radius, cy + ny * radius, cz + nz * radius)
        # 竖直圆柱:侧面法向径向,上下底面法向 ±z;起点投到最近表面。
        cx, cy, cz = float(solid["x"]), float(solid["y"]), float(solid["z"])
        radius = float(solid.get("r", solid.get("radius", 0)))
        height = float(solid.get("height", 1.5) or 1.5)
        top, bottom = cz + height / 2, cz - height / 2
        cap_tol = max(0.05, height * 0.08)
        if abs(z0 - top) <= cap_tol:
            return (0.0, 0.0, 1.0), (x0, y0, top)
        if abs(z0 - bottom) <= cap_tol:
            return (0.0, 0.0, -1.0), (x0, y0, bottom)
        rx, ry = x0 - cx, y0 - cy
        norm = math.hypot(rx, ry)
        if norm < 1e-9:
            return None
        nx, ny = rx / norm, ry / norm
        clamped_z = min(max(z0, bottom), top)
        return (nx, ny, 0.0), (cx + nx * radius, cy + ny * radius, clamped_z)

    def solid_distance(solid: dict, x0: float, y0: float, z0: float) -> float:
        kind = solid.get("kind")
        if kind == "plane":
            nx, ny, nz = (float(solid["normal"][0]), float(solid["normal"][1]),
                          float(solid["normal"][2]))
            norm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if norm < 1e-9 or not all(isinstance(solid.get(key), (int, float))
                                      for key in ("x", "y", "z")):
                return 0.0
            cx, cy, cz = float(solid["x"]), float(solid["y"]), float(solid["z"])
            return abs(((x0 - cx) * nx + (y0 - cy) * ny + (z0 - cz) * nz) / norm)
        cx, cy, cz = float(solid["x"]), float(solid["y"]), float(solid["z"])
        if kind == "sphere":
            radius = float(solid.get("r", solid.get("radius", 0)))
            return abs(math.sqrt((x0 - cx) ** 2 + (y0 - cy) ** 2 + (z0 - cz) ** 2) - radius)
        radius = float(solid.get("r", solid.get("radius", 0)))
        height = float(solid.get("height", 1.5) or 1.5)
        top, bottom = cz + height / 2, cz - height / 2
        return min(abs(math.hypot(x0 - cx, y0 - cy) - radius),
                   abs(z0 - top), abs(z0 - bottom))

    for shape in shapes:
        if shape.get("kind") != "vector":
            continue
        label = str(shape.get("label") or "")
        if not normal_re.search(label) and "∇F" not in label:
            continue
        start = shape.get("from")
        end = shape.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            x0, y0, z0 = float(start[0]), float(start[1]), float(start[2])
            length = math.sqrt((float(end[0]) - x0) ** 2
                               + (float(end[1]) - y0) ** 2
                               + (float(end[2]) - z0) ** 2)
        except (TypeError, ValueError):
            continue
        solid = min(solids, key=lambda item: solid_distance(item, x0, y0, z0))
        normal = normal_at(solid, x0, y0, z0)
        if normal is None:
            continue
        (nx, ny, nz), (px, py, pz) = normal
        try:
            dx, dy, dz = float(end[0]) - x0, float(end[1]) - y0, float(end[2]) - z0
        except (TypeError, ValueError):
            continue
        dot = dx * nx + dy * ny + dz * nz
        if dot < -1e-6 or (abs(dot) <= 1e-6 and nz < 0):
            nx, ny, nz = -nx, -ny, -nz
        if length < 1e-6:
            length = 1.0
        shape["from"] = [round(px, 6), round(py, 6), round(pz, 6)]
        shape["to"] = [
            round(px + nx * length, 6),
            round(py + ny * length, 6),
            round(pz + nz * length, 6),
        ]


def _refine_param_surface_normal(shapes: list[dict], normal_re: re.Pattern) -> bool:
    """参数曲面法向:用相邻采样点的 r_u × r_v 计算,不采用模型手估方向。"""
    surface = next((
        shape for shape in shapes
        if shape.get("kind") == "parametric_surface"
        and isinstance(shape.get("points"), list)
        and shape.get("rows") and shape.get("cols")
    ), None)
    if surface is None:
        return False
    rows, cols = int(surface["rows"]), int(surface["cols"])
    points = [
        (float(point[0]), float(point[1]), float(point[2]))
        for point in surface["points"]
        if isinstance(point, list) and len(point) >= 3
    ]
    if len(points) < rows * cols:
        return False
    field = _compile_xyz_expr(surface.get("fieldexpr"))
    changed = False
    plane = next((
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and re.search(r"切平面|tangent\s*plane",
                      str(shape.get("label") or ""), re.IGNORECASE)
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
    ), None)
    if plane is not None:
        try:
            px, py, pz = float(plane["x"]), float(plane["y"]), float(plane["z"])
        except (TypeError, ValueError):
            px = py = pz = None
        if px is not None:
            index = min(range(rows * cols), key=lambda item: (
                (points[item][0] - px) ** 2 + (points[item][1] - py) ** 2
                + (points[item][2] - pz) ** 2))
            row, col = divmod(index, cols)
            row0, row1 = max(row - 1, 0), min(row + 1, rows - 1)
            col0, col1 = max(col - 1, 0), min(col + 1, cols - 1)
            if row0 != row1 and col0 != col1:
                anchor = points[index]
                du = tuple(points[row1 * cols + col][axis]
                           - points[row0 * cols + col][axis] for axis in range(3))
                dv = tuple(points[row * cols + col1][axis]
                           - points[row * cols + col0][axis] for axis in range(3))
                nx = du[1] * dv[2] - du[2] * dv[1]
                ny = du[2] * dv[0] - du[0] * dv[2]
                nz = du[0] * dv[1] - du[1] * dv[0]
                norm = math.sqrt(nx * nx + ny * ny + nz * nz)
                if norm >= 1e-9:
                    plane["x"], plane["y"], plane["z"] = anchor
                    plane["normal"] = [round(nx / norm, 6),
                                       round(ny / norm, 6),
                                       round(nz / norm, 6)]
                    changed = True
    for vector in shapes:
        if vector.get("kind") != "vector":
            continue
        label = str(vector.get("label") or "")
        # 参数曲面上的标量场梯度:先求 ∇f,再投到切平面(去掉法向分量)。
        if field is not None and re.search(r"梯度|gradient", label, re.IGNORECASE):
            start, end = vector.get("from"), vector.get("to")
            if not (isinstance(start, list) and len(start) >= 3
                    and isinstance(end, list) and len(end) >= 3):
                continue
            try:
                x0, y0, z0 = (float(start[0]), float(start[1]), float(start[2]))
            except (TypeError, ValueError):
                continue
            index = min(range(rows * cols), key=lambda item: (
                (points[item][0] - x0) ** 2 + (points[item][1] - y0) ** 2
                + (points[item][2] - z0) ** 2))
            row, col = divmod(index, cols)
            row0, row1 = max(row - 1, 0), min(row + 1, rows - 1)
            col0, col1 = max(col - 1, 0), min(col + 1, cols - 1)
            if row0 == row1 or col0 == col1:
                continue
            anchor = points[index]
            du = tuple(points[row1 * cols + col][axis]
                       - points[row0 * cols + col][axis] for axis in range(3))
            dv = tuple(points[row * cols + col1][axis]
                       - points[row * cols + col0][axis] for axis in range(3))
            nx = du[1] * dv[2] - du[2] * dv[1]
            ny = du[2] * dv[0] - du[0] * dv[2]
            nz = du[0] * dv[1] - du[1] * dv[0]
            nnorm = math.sqrt(nx * nx + ny * ny + nz * nz)
            if nnorm < 1e-9:
                continue
            nx, ny, nz = nx / nnorm, ny / nnorm, nz / nnorm
            h = 1e-4 * max(1.0, abs(anchor[0]), abs(anchor[1]), abs(anchor[2]))
            try:
                gx = (field(anchor[0] + h, anchor[1], anchor[2])
                      - field(anchor[0] - h, anchor[1], anchor[2])) / (2 * h)
                gy = (field(anchor[0], anchor[1] + h, anchor[2])
                      - field(anchor[0], anchor[1] - h, anchor[2])) / (2 * h)
                gz = (field(anchor[0], anchor[1], anchor[2] + h)
                      - field(anchor[0], anchor[1], anchor[2] - h)) / (2 * h)
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                continue
            along = gx * nx + gy * ny + gz * nz
            sx, sy, sz = gx - along * nx, gy - along * ny, gz - along * nz
            snorm = math.sqrt(sx * sx + sy * sy + sz * sz)
            if snorm < 1e-9:
                continue
            sx, sy, sz = sx / snorm, sy / snorm, sz / snorm
            try:
                length = math.sqrt((float(end[0]) - x0) ** 2
                                   + (float(end[1]) - y0) ** 2
                                   + (float(end[2]) - z0) ** 2)
            except (TypeError, ValueError):
                length = 1.0
            if length < 1e-6:
                length = 1.0
            if sx * (float(end[0]) - x0) + sy * (float(end[1]) - y0) + sz * (float(end[2]) - z0) < 0:
                sx, sy, sz = -sx, -sy, -sz
            vector["from"] = [round(anchor[0], 6), round(anchor[1], 6),
                              round(anchor[2], 6)]
            vector["to"] = [
                round(anchor[0] + sx * length, 6),
                round(anchor[1] + sy * length, 6),
                round(anchor[2] + sz * length, 6),
            ]
            changed = True
            continue
        if not normal_re.search(label) and "∇F" not in label:
            continue
        start, end = vector.get("from"), vector.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            x0, y0, z0 = float(start[0]), float(start[1]), float(start[2])
        except (TypeError, ValueError):
            continue
        index = min(range(rows * cols), key=lambda item: (
            (points[item][0] - x0) ** 2 + (points[item][1] - y0) ** 2
            + (points[item][2] - z0) ** 2))
        row, col = divmod(index, cols)
        row0, row1 = max(row - 1, 0), min(row + 1, rows - 1)
        col0, col1 = max(col - 1, 0), min(col + 1, cols - 1)
        if row0 == row1 or col0 == col1:
            continue
        anchor = points[index]
        # 边界点用单侧差分,不能因为落在网格第一行/列就放弃。
        du = tuple(points[row1 * cols + col][axis]
                   - points[row0 * cols + col][axis] for axis in range(3))
        dv = tuple(points[row * cols + col1][axis]
                   - points[row * cols + col0][axis] for axis in range(3))
        nx = du[1] * dv[2] - du[2] * dv[1]
        ny = du[2] * dv[0] - du[0] * dv[2]
        nz = du[0] * dv[1] - du[1] * dv[0]
        norm = math.sqrt(nx * nx + ny * ny + nz * nz)
        if norm < 1e-9:
            continue
        nx, ny, nz = nx / norm, ny / norm, nz / norm
        try:
            dx, dy, dz = (float(end[0]) - x0, float(end[1]) - y0,
                          float(end[2]) - z0)
        except (TypeError, ValueError):
            continue
        dot = dx * nx + dy * ny + dz * nz
        if dot < -1e-6 or (abs(dot) <= 1e-6 and nz < 0):
            nx, ny, nz = -nx, -ny, -nz
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            length = 1.0
        vector["from"] = [round(anchor[0], 6), round(anchor[1], 6),
                          round(anchor[2], 6)]
        vector["to"] = [
            round(anchor[0] + nx * length, 6),
            round(anchor[1] + ny * length, 6),
            round(anchor[2] + nz * length, 6),
        ]
        changed = True
    return changed


def _refine_implicit_surface_normal(shapes: list[dict], normal_re: re.Pattern) -> bool:
    """隐式曲面 F=0 的法向 = ∇F;箭头起点投到最近的网格顶点。"""
    surface = next((
        shape for shape in shapes
        if shape.get("kind") == "implicit_surface" and shape.get("expr")
        and isinstance(shape.get("positions"), list)
    ), None)
    if surface is None:
        return False
    run = _compile_xyz_expr(surface.get("expr"))
    if run is None:
        return False
    flat = [float(value) for value in surface["positions"]]
    vertices = [
        (flat[index], flat[index + 1], flat[index + 2])
        for index in range(0, len(flat) - 2, 3)
    ]
    if not vertices:
        return False
    changed = False

    def value_gradient(point) -> tuple[float, tuple[float, float, float]] | None:
        x, y, z = point
        h = 1e-4 * max(1.0, abs(x), abs(y), abs(z))
        try:
            value = run(x, y, z)
            gx = (run(x + h, y, z) - run(x - h, y, z)) / (2 * h)
            gy = (run(x, y + h, z) - run(x, y - h, z)) / (2 * h)
            gz = (run(x, y, z + h) - run(x, y, z - h)) / (2 * h)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return None
        if not all(math.isfinite(item) for item in (value, gx, gy, gz)):
            return None
        return float(value), (gx, gy, gz)

    def project(point):
        """牛顿步把起点拉回 F=0,避免网格被截断时投到错误一侧。"""
        current = point
        for _ in range(3):
            result = value_gradient(current)
            if result is None:
                break
            value, gradient = result
            denominator = sum(item * item for item in gradient)
            if denominator < 1e-12:
                break
            current = tuple(
                current[index] - value * gradient[index] / denominator
                for index in range(3))
            if abs(value) < 1e-7:
                break
        return current

    def unit_normal(point):
        result = value_gradient(point)
        if result is None:
            return None
        _value, gradient = result
        norm = math.sqrt(sum(item * item for item in gradient))
        if norm < 1e-9:
            return None
        return tuple(item / norm for item in gradient)

    plane = next((
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and re.search(r"切平面|tangent\s*plane",
                      str(shape.get("label") or ""), re.IGNORECASE)
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
    ), None)
    if plane is not None:
        anchor = project((float(plane["x"]), float(plane["y"]),
                          float(plane["z"])))
        normal = unit_normal(anchor)
        if normal is None:
            anchor = min(vertices, key=lambda item: (
                (item[0] - float(plane["x"])) ** 2
                + (item[1] - float(plane["y"])) ** 2
                + (item[2] - float(plane["z"])) ** 2))
            normal = unit_normal(anchor)
        if normal is not None:
            plane["x"], plane["y"], plane["z"] = anchor
            plane["normal"] = [round(value, 6) for value in normal]
            changed = True

    for vector in shapes:
        if vector.get("kind") != "vector":
            continue
        label = str(vector.get("label") or "")
        if not normal_re.search(label) and "∇F" not in label:
            continue
        start, end = vector.get("from"), vector.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            probe = (float(start[0]), float(start[1]), float(start[2]))
            end_point = (float(end[0]), float(end[1]), float(end[2]))
        except (TypeError, ValueError):
            continue
        anchor = project(probe)
        normal = unit_normal(anchor)
        if normal is None:
            anchor = min(vertices, key=lambda item: sum(
                (item[index] - probe[index]) ** 2 for index in range(3)))
            normal = unit_normal(anchor)
        if normal is None:
            continue
        direction = tuple(end_point[index] - probe[index] for index in range(3))
        length = math.sqrt(sum(value * value for value in direction))
        dot = sum(direction[index] * normal[index] for index in range(3))
        if dot < -1e-6:
            normal = tuple(-value for value in normal)
        if length < 1e-6:
            length = 1.0
        vector["from"] = [round(anchor[0], 6), round(anchor[1], 6),
                          round(anchor[2], 6)]
        vector["to"] = [
            round(anchor[index] + normal[index] * length, 6)
            for index in range(3)
        ]
        changed = True
    return changed


def _refine_surface_normal(shapes: list[dict]) -> None:
    """曲面 z=f(x,y) 上的法向量由表达式求偏导,不采用模型手估的竖直箭头。

    典型错误:第二类曲面积分图中把某点法向量画成 (0,0,1),与 z 轴平行。
    对 z=f(x,y),正确法向是 (-f_x, -f_y, 1)(上侧);这里只修正明确标成
    法向量的箭头,并保留模型原本的朝向(上/下侧),不碰梯度或普通向量。
    """
    surface = next((
        shape for shape in shapes
        if shape.get("kind") == "surface" and shape.get("expr")
        and not isinstance(shape.get("points"), list)
    ), None)
    if surface is None:
        surface = next((
            shape for shape in shapes
            if shape.get("kind") == "surface" and shape.get("expr")
        ), None)
    normal_re = re.compile(
        r"法向|法向量|外法向|内法向|单位法向|上侧|下侧|外侧|内侧|"
        r"upward|downward|outward|inward|\bnormal\b|^n(?:\s|=|$)",
        re.IGNORECASE)
    if surface is None:
        if _refine_param_surface_normal(shapes, normal_re):
            return
        if any(shape.get("kind") == "parametric_surface" for shape in shapes):
            # 参数曲面存在但法向无法计算时,不要拿无关的平面/球面去冒充。
            return
        if any(shape.get("kind") == "implicit_surface" for shape in shapes):
            _refine_implicit_surface_normal(shapes, normal_re)
            return
        _refine_normal_from_solid(shapes, normal_re)
        return
    expr = str(surface.get("expr") or "").strip()
    expr = re.sub(r"^\s*z\s*=\s*", "", expr, flags=re.IGNORECASE)
    run = _compile_expr(expr, allow_y=True)
    if run is None:
        _refine_normal_from_solid(shapes, normal_re)
        return
    # 切平面即使没有法向量箭头也要按曲面偏导修正法向。
    plane = next((
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and re.search(r"切平面|tangent\s*plane",
                      str(shape.get("label") or ""), re.IGNORECASE)
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
    ), None)
    if plane is not None:
        try:
            px, py = float(plane["x"]), float(plane["y"])
            h = 1e-4 * max(1.0, abs(px), abs(py))
            fx = (run(px + h, py) - run(px - h, py)) / (2 * h)
            fy = (run(px, py + h) - run(px, py - h)) / (2 * h)
            pz = run(px, py)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            fx = fy = pz = None
        if fx is not None and all(math.isfinite(value) for value in (fx, fy, pz)):
            plane["z"] = round(float(pz), 6)
            plane["normal"] = [round(-float(fx), 6), round(-float(fy), 6), 1.0]
    for shape in shapes:
        if shape.get("kind") != "vector":
            continue
        label = str(shape.get("label") or "")
        if not normal_re.search(label) and "∇F" not in label:
            continue
        start = shape.get("from")
        end = shape.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            x0, y0, z0 = float(start[0]), float(start[1]), float(start[2])
            h = 1e-4 * max(1.0, abs(x0), abs(y0))
            fx = (run(x0 + h, y0) - run(x0 - h, y0)) / (2 * h)
            fy = (run(x0, y0 + h) - run(x0, y0 - h)) / (2 * h)
            surface_z = run(x0, y0)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            continue
        if not all(math.isfinite(value) for value in (fx, fy, surface_z)):
            continue
        # 起点必须落在这张曲面上,否则不是“曲面在一点的法向量”
        if abs(z0 - surface_z) > 0.25 * max(1.0, abs(surface_z)):
            continue
        normal = math.sqrt(fx * fx + fy * fy + 1.0)
        nx, ny, nz = -fx / normal, -fy / normal, 1.0 / normal
        try:
            dx, dy, dz = float(end[0]) - x0, float(end[1]) - y0, float(end[2]) - z0
        except (TypeError, ValueError):
            continue
        # 保留模型选择的朝向:下方/内侧时整体取反;接近垂直时默认取上侧
        dot = dx * nx + dy * ny + dz * nz
        if dot < -1e-6 or (abs(dot) <= 1e-6 and nz < 0):
            nx, ny, nz = -nx, -ny, -nz
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-6:
            length = 1.0
        shape["from"] = [round(x0, 6), round(y0, 6), round(surface_z, 6)]
        shape["to"] = [
            round(x0 + nx * length, 6),
            round(y0 + ny * length, 6),
            round(surface_z + nz * length, 6),
        ]


def _refine_ellipse3d_tangents(shapes: list[dict]) -> None:
    """3D 椭圆切线:在椭圆平面内按参数点求切向,法向决定平面。"""
    ellipses = [
        shape for shape in shapes
        if shape.get("kind") == "ellipse"
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
        and float(shape.get("rx", 0) or 0) > 1e-9
        and float(shape.get("ry", 0) or 0) > 1e-9
    ]
    tangents = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not ellipses or not tangents:
        return
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point"
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
    ]

    def dot(a, b):
        return sum(a[index] * b[index] for index in range(3))

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def unit(vector):
        norm = math.sqrt(sum(value * value for value in vector))
        if norm < 1e-9:
            return None
        return tuple(value / norm for value in vector)

    def add(*vectors):
        return tuple(sum(vector[index] for vector in vectors) for index in range(3))

    def scale(vector, factor):
        return tuple(value * factor for value in vector)

    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            mid = tuple((float(start[index]) + float(end[index])) / 2
                        for index in range(3))
            mid_x = (float(start[0]) + float(end[0])) / 2
            mid_y = (float(start[1]) + float(end[1])) / 2
        except (TypeError, ValueError):
            continue
        ellipse = min(
            ellipses,
            key=lambda item: (float(item["x"]) - mid_x) ** 2
            + (float(item["y"]) - mid_y) ** 2,
        )
        try:
            center = (float(ellipse["x"]), float(ellipse["y"]),
                      float(ellipse["z"]))
            rx, ry = float(ellipse["rx"]), float(ellipse["ry"])
            rotation = float(ellipse.get("rotation", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        raw_normal = ellipse.get("normal")
        normal = None
        if isinstance(raw_normal, (list, tuple)) and len(raw_normal) >= 3:
            try:
                normal = unit(tuple(float(value) for value in raw_normal[:3]))
            except (TypeError, ValueError):
                normal = None
        if normal is None:
            normal = (0.0, 0.0, 1.0)
        helper = (1.0, 0.0, 0.0) if abs(normal[0]) < 0.9 else (0.0, 1.0, 0.0)
        projected = tuple(helper[index] - normal[index] * dot(helper, normal)
                          for index in range(3))
        axis_u = unit(projected)
        axis_v = unit(cross(normal, axis_u)) if axis_u else None
        if axis_u is None or axis_v is None:
            continue
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)
        u = add(scale(axis_u, cos_r), scale(axis_v, sin_r))
        v = add(scale(axis_u, -sin_r), scale(axis_v, cos_r))

        def local(relative):
            return dot(relative, u), dot(relative, v)

        candidates = []
        for point in points:
            try:
                relative = tuple(float(point[key]) - center[index]
                                 for index, key in enumerate(("x", "y", "z")))
            except (TypeError, ValueError):
                continue
            if abs(dot(relative, normal)) > max(0.05, max(rx, ry) * 0.1):
                continue
            lx, ly = local(relative)
            error = abs((lx / rx) ** 2 + (ly / ry) ** 2 - 1)
            if error <= 0.35:
                candidates.append((
                    error * 5 + math.sqrt(sum(
                        (float(point[key]) - mid[index]) ** 2
                        for index, key in enumerate(("x", "y", "z")))),
                    point,
                ))
        point = min(candidates, key=lambda item: item[0])[1] if candidates else None
        if point is not None:
            try:
                relative = tuple(float(point[key]) - center[index]
                                 for index, key in enumerate(("x", "y", "z")))
            except (TypeError, ValueError):
                continue
        else:
            relative = tuple(mid[index] - center[index] for index in range(3))
            along = dot(relative, normal)
            relative = tuple(relative[index] - normal[index] * along
                             for index in range(3))
        lx, ly = local(relative)
        if abs(math.hypot(lx / rx, ly / ry) - 1) > 0.5 and point is None:
            continue
        angle = math.atan2(ly / ry, lx / rx)
        anchor_local = (rx * math.cos(angle) * u[0] + ry * math.sin(angle) * v[0],
                        rx * math.cos(angle) * u[1] + ry * math.sin(angle) * v[1],
                        rx * math.cos(angle) * u[2] + ry * math.sin(angle) * v[2])
        anchor = tuple(center[index] + anchor_local[index] for index in range(3))
        tangent_local = (-rx * math.sin(angle) * u[0] + ry * math.cos(angle) * v[0],
                         -rx * math.sin(angle) * u[1] + ry * math.cos(angle) * v[1],
                         -rx * math.sin(angle) * u[2] + ry * math.cos(angle) * v[2])
        direction = unit(tangent_local)
        if direction is None:
            continue
        half = max(0.2, max(rx, ry) * 0.35)
        tangent["from"] = [round(anchor[index] - direction[index] * half, 6)
                           for index in range(3)]
        tangent["to"] = [round(anchor[index] + direction[index] * half, 6)
                         for index in range(3)]
        if point is not None:
            point["x"], point["y"], point["z"] = (
                round(anchor[0], 6), round(anchor[1], 6), round(anchor[2], 6),
            )


def _refine_circle3d_tangents(shapes: list[dict]) -> None:
    """3D 圆的切线:在圆所在平面内,方向 = 法向 × 半径。"""
    circles = [
        shape for shape in shapes
        if shape.get("kind") == "circle"
        and all(isinstance(shape.get(key), (int, float))
                for key in ("x", "y", "z"))
        and float(shape.get("r", shape.get("radius", 0)) or 0) > 1e-9
    ]
    tangents = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not circles or not tangents:
        return
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point"
        and all(isinstance(shape.get(key), (int, float)) for key in ("x", "y", "z"))
    ]

    def dot(a, b):
        return sum(a[index] * b[index] for index in range(3))

    def cross(a, b):
        return (a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0])

    def unit(vector):
        norm = math.sqrt(sum(value * value for value in vector))
        if norm < 1e-9:
            return None
        return tuple(value / norm for value in vector)

    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            mid = tuple((float(start[index]) + float(end[index])) / 2
                        for index in range(3))
        except (TypeError, ValueError):
            continue
        circle = min(
            circles,
            key=lambda item: sum(
                (float(item[key]) - mid[index]) ** 2
                for index, key in enumerate(("x", "y", "z"))),
        )
        try:
            center = (float(circle["x"]), float(circle["y"]), float(circle["z"]))
            radius = float(circle.get("r", circle.get("radius", 0)))
        except (TypeError, ValueError):
            continue
        raw_normal = circle.get("normal")
        if isinstance(raw_normal, (list, tuple)) and len(raw_normal) >= 3:
            try:
                normal = unit(tuple(float(value) for value in raw_normal[:3]))
            except (TypeError, ValueError):
                normal = None
        else:
            normal = None
        if normal is None:
            normal = (0.0, 0.0, 1.0)
        on_circle = []
        for point in points:
            try:
                relative = tuple(float(point[key]) - center[index]
                                 for index, key in enumerate(("x", "y", "z")))
            except (TypeError, ValueError):
                continue
            if (abs(dot(relative, normal)) <= max(0.05, radius * 0.1)
                    and abs(math.sqrt(sum(value * value for value in relative)) - radius)
                    <= max(0.08 * radius, 0.05)):
                on_circle.append(point)
        point = min(
            on_circle,
            key=lambda item: sum(
                (float(item[key]) - mid[index]) ** 2
                for index, key in enumerate(("x", "y", "z"))),
        ) if on_circle else None
        if point is not None:
            relative = tuple(float(point[key]) - center[index]
                             for index, key in enumerate(("x", "y", "z")))
        else:
            relative = tuple(mid[index] - center[index] for index in range(3))
            along = dot(relative, normal)
            relative = tuple(relative[index] - normal[index] * along
                             for index in range(3))
        radial = unit(relative)
        if radial is None:
            continue
        direction = unit(cross(normal, radial))
        if direction is None:
            continue
        half = max(0.2, radius * 0.35)
        anchor = tuple(center[index] + radial[index] * radius
                       for index in range(3))
        tangent["from"] = [round(anchor[index] - direction[index] * half, 6)
                           for index in range(3)]
        tangent["to"] = [round(anchor[index] + direction[index] * half, 6)
                         for index in range(3)]
        if point is not None:
            point["x"], point["y"], point["z"] = (
                round(anchor[0], 6), round(anchor[1], 6), round(anchor[2], 6),
            )


def _refine_curve3d_tangents(shapes: list[dict]) -> None:
    """3D 参数曲线的手画切线按相邻点方向校正。

    3D 曲线没有 y=f(x) 的表达式,切线方向取曲线点列的局部中心差分;
    起点落在曲线上离切线中点最近的点。
    """
    curves = [
        shape for shape in shapes
        if shape.get("kind") in ("curve", "parametric_curve", "implicit_curve3d")
        and isinstance(shape.get("points"), list)
        and len(shape["points"]) >= 2
    ]
    tangents = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not curves or not tangents:
        return
    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        if not (isinstance(start, list) and len(start) >= 3
                and isinstance(end, list) and len(end) >= 3):
            continue
        try:
            sx, sy, sz = (float(start[0]), float(start[1]), float(start[2]))
            ex, ey, ez = (float(end[0]), float(end[1]), float(end[2]))
        except (TypeError, ValueError):
            continue
        mid = ((sx + ex) / 2, (sy + ey) / 2, (sz + ez) / 2)
        model = (ex - sx, ey - sy, ez - sz)
        model_len = math.sqrt(sum(value * value for value in model))
        if model_len < 1e-9:
            continue
        curve = min(
            curves,
            key=lambda item: min(
                sum((float(point[axis]) - mid[axis]) ** 2 for axis in range(3))
                for point in item["points"]),
        )
        pts = [
            (float(point[0]), float(point[1]), float(point[2]))
            for point in curve["points"]
        ]
        index = min(range(len(pts)), key=lambda item: sum(
            (pts[item][axis] - mid[axis]) ** 2 for axis in range(3)))
        if index == 0:
            first, second = pts[0], pts[1]
        elif index == len(pts) - 1:
            first, second = pts[-2], pts[-1]
        else:
            first, second = pts[index - 1], pts[index + 1]
        direction = tuple(second[axis] - first[axis] for axis in range(3))
        norm = math.sqrt(sum(value * value for value in direction))
        if norm < 1e-9:
            continue
        # 保留模型画的朝向;只改方向与位置。
        dot = sum(model[axis] * direction[axis] for axis in range(3))
        if dot < 0:
            direction = tuple(-value for value in direction)
            norm = math.sqrt(sum(value * value for value in direction))
        unit = tuple(value / norm for value in direction)
        anchor = pts[index]
        half = max(0.1, model_len / 2)
        tangent["from"] = [round(anchor[axis] - unit[axis] * half, 6)
                           for axis in range(3)]
        tangent["to"] = [round(anchor[axis] + unit[axis] * half, 6)
                         for axis in range(3)]


def _refine_implicit_curve_tangents(shapes: list[dict]) -> None:
    """隐式曲线 F(x,y)=0 的切线方向 = (F_y, -F_x),垂直于 ∇F。"""
    curves = [
        shape for shape in shapes
        if shape.get("kind") == "implicit_curve" and shape.get("expr")
        and isinstance(shape.get("points"), list) and shape["points"]
    ]
    tangents = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not curves or not tangents:
        return
    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        if not (isinstance(start, list) and len(start) >= 2
                and isinstance(end, list) and len(end) >= 2):
            continue
        try:
            mid_x = (float(start[0]) + float(end[0])) / 2
            mid_y = (float(start[1]) + float(end[1])) / 2
        except (TypeError, ValueError):
            continue
        curve = min(
            curves,
            key=lambda item: min(
                (float(point[0]) - mid_x) ** 2
                + (float(point[1]) - mid_y) ** 2
                for point in item["points"]),
        )
        anchor = min(
            ((float(point[0]), float(point[1])) for point in curve["points"]),
            key=lambda point: (point[0] - mid_x) ** 2 + (point[1] - mid_y) ** 2,
        )
        run = _compile_expr(curve.get("expr"), allow_y=True)
        if run is None:
            continue
        h = 1e-4 * max(1.0, abs(anchor[0]), abs(anchor[1]))
        try:
            gx = (run(anchor[0] + h, anchor[1])
                  - run(anchor[0] - h, anchor[1])) / (2 * h)
            gy = (run(anchor[0], anchor[1] + h)
                  - run(anchor[0], anchor[1] - h)) / (2 * h)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            continue
        norm = math.hypot(gx, gy)
        if norm < 1e-9:
            continue
        tx, ty = gy / norm, -gx / norm
        domain = _domain(curve)
        span = (domain[1] - domain[0]) if domain else 2.0
        half = max(0.2, span * 0.05)
        tangent["from"] = [round(anchor[0] - tx * half, 6),
                           round(anchor[1] - ty * half, 6)]
        tangent["to"] = [round(anchor[0] + tx * half, 6),
                         round(anchor[1] + ty * half, 6)]
        tangent["_implicit_tangent"] = True


def _refine_ellipse_tangents(shapes: list[dict]) -> None:
    """2D 椭圆切线:按参数点投影,方向 (-rx sin t, ry cos t) 旋转后使用。"""
    ellipses = [
        shape for shape in shapes
        if shape.get("kind") == "ellipse"
        and all(isinstance(shape.get(key), (int, float)) for key in ("x", "y"))
        and float(shape.get("rx", 0) or 0) > 1e-9
        and float(shape.get("ry", 0) or 0) > 1e-9
    ]
    if not ellipses:
        return
    tangents = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not tangents:
        return
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point" and "x" in shape and "y" in shape
    ]
    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        if not (isinstance(start, list) and len(start) >= 2
                and isinstance(end, list) and len(end) >= 2):
            continue
        try:
            mid_x = (float(start[0]) + float(end[0])) / 2
            mid_y = (float(start[1]) + float(end[1])) / 2
        except (TypeError, ValueError):
            continue
        ellipse = min(
            ellipses,
            key=lambda item: (float(item["x"]) - mid_x) ** 2
            + (float(item["y"]) - mid_y) ** 2,
        )
        try:
            cx, cy = float(ellipse["x"]), float(ellipse["y"])
            rx, ry = float(ellipse["rx"]), float(ellipse["ry"])
            rotation = float(ellipse.get("rotation", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        cos_r, sin_r = math.cos(rotation), math.sin(rotation)

        def local(px: float, py: float) -> tuple[float, float]:
            dx, dy = px - cx, py - cy
            return dx * cos_r + dy * sin_r, -dx * sin_r + dy * cos_r

        candidates = []
        for point in points:
            try:
                px, py = float(point["x"]), float(point["y"])
            except (TypeError, ValueError):
                continue
            lx, ly = local(px, py)
            error = abs((lx / rx) ** 2 + (ly / ry) ** 2 - 1)
            if error <= 0.35:
                candidates.append((
                    error * 5 + math.hypot(px - mid_x, py - mid_y), point,
                ))
        point = min(candidates, key=lambda item: item[0])[1] if candidates else None
        if point is not None:
            lx, ly = local(float(point["x"]), float(point["y"]))
        else:
            lx, ly = local(mid_x, mid_y)
            if abs(lx) < 1e-12 and abs(ly) < 1e-12:
                continue
            if abs(math.hypot(lx / rx, ly / ry) - 1) > 0.5:
                continue
        angle = math.atan2(ly / ry, lx / rx)
        # 参数点 + 切线方向
        ex, ey = rx * math.cos(angle), ry * math.sin(angle)
        gx = cx + ex * cos_r - ey * sin_r
        gy = cy + ex * sin_r + ey * cos_r
        tx = -rx * math.sin(angle)
        ty = ry * math.cos(angle)
        wx = tx * cos_r - ty * sin_r
        wy = tx * sin_r + ty * cos_r
        norm = math.hypot(wx, wy)
        if norm < 1e-9:
            continue
        wx, wy = wx / norm, wy / norm
        half = max(0.2, max(rx, ry) * 0.35)
        tangent["from"] = [round(gx - wx * half, 6), round(gy - wy * half, 6)]
        tangent["to"] = [round(gx + wx * half, 6), round(gy + wy * half, 6)]
        tangent["_conic_tangent"] = True
        if point is not None:
            point["x"] = round(gx, 6)
            point["y"] = round(gy, 6)


def _refine_circle_tangents(shapes: list[dict]) -> None:
    """圆的切线垂直于半径;模型手画的斜线按切点/圆心垂足校正。"""
    circles = [
        shape for shape in shapes
        if shape.get("kind") == "circle"
        and all(isinstance(shape.get(key), (int, float)) for key in ("x", "y"))
        and float(shape.get("r", shape.get("radius", 0)) or 0) > 1e-9
    ]
    if not circles:
        return
    tangents = [
        shape for shape in shapes
        if (shape.get("kind") in ("segment", "line")
            or (shape.get("kind") == "curve" and _is_straight_curve(shape)))
        and re.search(r"切线|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ]
    if not tangents:
        return
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point" and "x" in shape and "y" in shape
    ]
    for tangent in tangents:
        start, end = tangent.get("from"), tangent.get("to")
        curve_points = tangent.get("points")
        if not (isinstance(start, (list, tuple)) and len(start) >= 2):
            if isinstance(curve_points, list) and curve_points:
                start = curve_points[0]
        if not (isinstance(end, (list, tuple)) and len(end) >= 2):
            if isinstance(curve_points, list) and curve_points:
                end = curve_points[-1]
        if not (isinstance(start, (list, tuple)) and len(start) >= 2
                and isinstance(end, (list, tuple)) and len(end) >= 2):
            continue
        try:
            x1, y1 = float(start[0]), float(start[1])
            x2, y2 = float(end[0]), float(end[1])
        except (TypeError, ValueError):
            continue
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        circle = min(
            circles,
            key=lambda item: abs(
                math.hypot(mid_x - float(item["x"]), mid_y - float(item["y"]))
                - float(item.get("r", item.get("radius", 0)))),
        )
        try:
            cx, cy = float(circle["x"]), float(circle["y"])
            radius = float(circle.get("r", circle.get("radius", 0)))
        except (TypeError, ValueError):
            continue
        vx, vy = x2 - x1, y2 - y1
        length = math.hypot(vx, vy)
        if length < 1e-9 or radius < 1e-9:
            continue
        on_circle = []
        for point in points:
            try:
                px, py = float(point["x"]), float(point["y"])
            except (TypeError, ValueError):
                continue
            if abs(math.hypot(px - cx, py - cy) - radius) <= max(0.08 * radius, 0.05):
                on_circle.append(point)
        point = min(
            on_circle,
            key=lambda item: math.hypot(float(item["x"]) - mid_x,
                                       float(item["y"]) - mid_y),
        ) if on_circle else None
        if point is not None:
            px, py = float(point["x"]) - cx, float(point["y"]) - cy
        else:
            # 圆心到切线的垂足;线离圆太远时不动,避免把普通直线改成切线。
            t = ((cx - x1) * vx + (cy - y1) * vy) / (length * length)
            foot_x, foot_y = x1 + t * vx, y1 + t * vy
            fx, fy = foot_x - cx, foot_y - cy
            distance = math.hypot(fx, fy)
            if distance < 1e-9 or abs(distance - radius) > max(0.15 * radius, 0.1):
                continue
            px, py = fx, fy
        norm = math.hypot(px, py)
        if norm < 1e-9:
            continue
        nx, ny = px / norm, py / norm
        tx, ty = -ny, nx
        half = max(0.2, radius * 0.35)
        tangent["from"] = [round(cx + nx * radius - tx * half, 6),
                           round(cy + ny * radius - ty * half, 6)]
        tangent["to"] = [round(cx + nx * radius + tx * half, 6),
                         round(cy + ny * radius + ty * half, 6)]
        tangent["_conic_tangent"] = True
        if tangent.get("kind") == "curve":
            tangent["points"] = [tangent["from"], tangent["to"]]
        if point is not None:
            point["x"] = round(cx + nx * radius, 6)
            point["y"] = round(cy + ny * radius, 6)


def _is_straight_curve(shape: dict) -> bool:
    points = shape.get("points")
    if not isinstance(points, list) or len(points) < 2:
        return False
    if len(points) == 2:
        return True
    try:
        x0, y0 = float(points[0][0]), float(points[0][1])
        x1, y1 = float(points[-1][0]), float(points[-1][1])
        xm, ym = float(points[len(points) // 2][0]), float(points[len(points) // 2][1])
    except (TypeError, ValueError, IndexError):
        return False
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return False
    return abs((xm - x0) * dy - (ym - y0) * dx) / length < 1e-4


def _pretty_expr(expr: str) -> str:
    text = re.sub(
        r"^\s*(?:y|z|f\s*\(\s*x\s*(?:,\s*y\s*)?\))\s*=\s*",
        "", str(expr).strip(), flags=re.IGNORECASE)
    return (text.replace("**", "^").replace("^2", "²")
            .replace("^3", "³").replace("*", "·"))


def _materialize_tangent_objects(shapes: list[dict]) -> None:
    """把 tangent + curve + x 的语义对象落成 segment(切点由目标曲线求)。"""
    targets = [
        shape for shape in shapes
        if shape.get("kind") in ("curve", "parametric_curve", "implicit_curve",
                                 "circle", "ellipse")
        and (isinstance(shape.get("points"), list) and shape["points"]
             or shape.get("kind") in ("circle", "ellipse"))
    ]
    for shape in shapes:
        if shape.get("kind") != "tangent":
            continue
        name = str(shape.get("curve") or "").strip()
        x0 = _num(shape.get("x"))
        if not name or x0 is None:
            continue

        def norm(value: object) -> str:
            return re.sub(r"\s+", "", str(value or "")).lower()

        target = next((
            item for item in targets
            if norm(item.get("expr")) == norm(name)
            or norm(item.get("label")) == norm(name)
        ), None)
        if target is None:
            continue
        try:
            target_x = float(x0)
        except (TypeError, ValueError):
            continue
        if (target.get("kind") == "circle"
                and "z" not in target
                and ("r" in target or "radius" in target)):
            try:
                cx, cy = float(target["x"]), float(target["y"])
                radius = float(target.get("r", target.get("radius", 0)))
            except (KeyError, TypeError, ValueError):
                continue
            hint_y = _num(shape.get("y"))
            if radius <= 1e-9 or hint_y is None:
                continue
            rel_x, rel_y = target_x - cx, float(hint_y) - cy
            norm = math.hypot(rel_x, rel_y)
            if norm < 1e-9:
                continue
            ux, uy = rel_x / norm, rel_y / norm
            tx, ty = -uy, ux
            anchor = (cx + ux * radius, cy + uy * radius)
            half = max(0.2, radius * 0.35)
            shape["kind"] = "segment"
            shape.pop("curve", None)
            shape["label"] = shape.get("label") or "切线"
            shape["from"] = [round(anchor[0] - tx * half, 6),
                             round(anchor[1] - ty * half, 6)]
            shape["to"] = [round(anchor[0] + tx * half, 6),
                           round(anchor[1] + ty * half, 6)]
            continue
        if (target.get("kind") == "ellipse" and "z" not in target):
            try:
                cx, cy = float(target["x"]), float(target["y"])
                rx, ry = float(target["rx"]), float(target["ry"])
                rotation = float(target.get("rotation", 0.0) or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            hint_y = _num(shape.get("y"))
            if hint_y is None or rx <= 1e-9 or ry <= 1e-9:
                continue
            cos_r, sin_r = math.cos(rotation), math.sin(rotation)
            dx, dy = target_x - cx, float(hint_y) - cy
            lx, ly = dx * cos_r + dy * sin_r, -dx * sin_r + dy * cos_r
            angle = math.atan2(ly / ry, lx / rx)
            ex, ey = rx * math.cos(angle), ry * math.sin(angle)
            anchor = (cx + ex * cos_r - ey * sin_r,
                      cy + ex * sin_r + ey * cos_r)
            tx, ty = -rx * math.sin(angle), ry * math.cos(angle)
            wx, wy = tx * cos_r - ty * sin_r, tx * sin_r + ty * cos_r
            norm = math.hypot(wx, wy)
            if norm < 1e-9:
                continue
            wx, wy = wx / norm, wy / norm
            half = max(0.2, max(rx, ry) * 0.35)
            shape["kind"] = "segment"
            shape.pop("curve", None)
            shape["label"] = shape.get("label") or "切线"
            shape["from"] = [round(anchor[0] - wx * half, 6),
                             round(anchor[1] - wy * half, 6)]
            shape["to"] = [round(anchor[0] + wx * half, 6),
                           round(anchor[1] + wy * half, 6)]
            continue
        run = _compile_expr(target.get("expr"), allow_y=False)
        if run is not None:
            h = 1e-4 * max(1.0, abs(target_x))
            try:
                y0 = float(run(target_x))
                slope = (run(target_x + h) - run(target_x - h)) / (2 * h)
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                continue
            half = 0.2
            shape["kind"] = "segment"
            shape.pop("curve", None)
            shape["label"] = shape.get("label") or "切线"
            shape["from"] = [round(target_x - half, 6),
                             round(y0 - slope * half, 6)]
            shape["to"] = [round(target_x + half, 6),
                           round(y0 + slope * half, 6)]
            continue
        ordered = [(float(point[0]), float(point[1]))
                   for point in target["points"]]
        index = min(range(len(ordered)),
                    key=lambda item: abs(ordered[item][0] - target_x))
        if index == 0:
            first, second = ordered[0], ordered[1]
        elif index == len(ordered) - 1:
            first, second = ordered[-2], ordered[-1]
        else:
            first, second = ordered[index - 1], ordered[index + 1]
        dx, dy = second[0] - first[0], second[1] - first[1]
        norm_d = math.hypot(dx, dy)
        if norm_d < 1e-9:
            continue
        tx, ty = dx / norm_d, dy / norm_d
        anchor = ordered[index]
        half = 0.2
        shape["kind"] = "segment"
        shape.pop("curve", None)
        shape["label"] = shape.get("label") or "切线"
        shape["from"] = [round(anchor[0] - tx * half, 6),
                         round(anchor[1] - ty * half, 6)]
        shape["to"] = [round(anchor[0] + tx * half, 6),
                       round(anchor[1] + ty * half, 6)]
    # 目标无法解析的 tangent 不留在图里冒充可渲染对象。
    shapes[:] = [shape for shape in shapes
                 if shape.get("kind") != "tangent"]


def _refine_plot2d(shapes: list[dict], plot_type: bool = True) -> None:
    """plot2d/几何图的数学校正:不叠导函数曲线;切线斜率由采样点数值计算。
    plot_type=True 时把所有非 axis 的 segment/line 视为切线候选;
    geometry2d 只处理明确标了“切线”的线。"""
    derivative_re = re.compile(r"导函数|导数|derivative|y'|f'", re.IGNORECASE)
    curves = [
        shape for shape in shapes
        if shape.get("kind") in ("curve", "parametric_curve", "implicit_curve3d")
        and shape.get("points")
    ]
    primary = next((
        shape for shape in curves
        if not derivative_re.search(str(shape.get("label") or ""))
        and not _is_straight_curve(shape)
    ), next((
        shape for shape in curves
        if not derivative_re.search(str(shape.get("label") or ""))
    ), curves[0] if curves else None))
    if primary is not None and not primary.get("label") and primary.get("expr"):
        primary["label"] = f"y={_pretty_expr(primary['expr'])}"
    if len(curves) >= 2:
        # 原函数与导函数不叠在同一坐标系;导函数另起一张图。
        shapes[:] = [
            shape for shape in shapes
            if shape is not None and not (
                shape in curves and shape is not primary
                and derivative_re.search(str(shape.get("label") or ""))
            )
        ]
    tangent_label = re.compile(r"切线|tangent", re.IGNORECASE)
    equation_label = re.compile(r"^\s*(?:y|f\s*\(\s*x\s*\))\s*=", re.IGNORECASE)
    line_shapes = [
        shape for shape in shapes
        if shape.get("kind") in ("segment", "line")
        # 明确标了切线的线即使与坐标轴重合也要保留并校正;
        # 只有未标注/只标 x/y 的轴向线段才当作重复坐标轴过滤。
        and not shape.get("_conic_tangent")
        and not shape.get("_implicit_tangent")
        and (tangent_label.search(str(shape.get("label") or ""))
             or not _axis_aligned_segment(shape))
    ]
    if plot_type:
        labeled = [
            shape for shape in line_shapes
            if tangent_label.search(str(shape.get("label") or ""))
            or equation_label.search(str(shape.get("label") or ""))
        ]
        # 有明确标签时只校正明确对象;同图有割线/渐近线/多条辅助线时不能全改。
        # 模型漏标签且图里只有一条直线时,仍按切线处理。
        tangents = labeled if labeled else (
            line_shapes if len(line_shapes) == 1 else [])
    else:
        tangents = [
            shape for shape in line_shapes
            if tangent_label.search(str(shape.get("label") or ""))
        ]
    # 模型有时把切线画成一条“直线型 curve”(如 y=x),也要校正。
    # 只在一个非线性主曲线 + 关键点同时存在时这样做,避免误改普通直线几何图。
    has_point = any(
        shape.get("kind") == "point" and "x" in shape and "y" in shape
        for shape in shapes
    )
    if primary is not None and not _is_straight_curve(primary):
        tangents.extend(shape for shape in curves
                        if shape is not primary and shape not in tangents
                        and not derivative_re.search(str(shape.get("label") or ""))
                        and _is_straight_curve(shape)
                        and (has_point or re.search(
                            r"切线|tangent", str(shape.get("label") or ""),
                            re.IGNORECASE)))
    points = [
        shape for shape in shapes
        if shape.get("kind") == "point" and "x" in shape and "y" in shape
    ]
    if primary is None or not tangents:
        return
    function_curves = [
        shape for shape in shapes
        if shape.get("kind") in ("curve", "parametric_curve", "implicit_curve3d")
        and shape.get("points")
        and not derivative_re.search(str(shape.get("label") or ""))
        and not _is_straight_curve(shape)
    ]
    if not function_curves or not tangents:
        return

    value_cache: dict[int, list[tuple[float, float]]] = {}

    def curve_values(curve: dict) -> list[tuple[float, float]]:
        key = id(curve)
        if key not in value_cache:
            value_cache[key] = sorted(
                ((float(item[0]), float(item[1])) for item in curve["points"]),
                key=lambda item: item[0],
            )
        return value_cache[key]

    ordered_cache: dict[int, list[tuple[float, float]]] = {}

    def curve_ordered(curve: dict) -> list[tuple[float, float]]:
        key = id(curve)
        if key not in ordered_cache:
            ordered_cache[key] = [
                (float(item[0]), float(item[1])) for item in curve["points"]
            ]
        return ordered_cache[key]

    def is_function_curve(curve: dict) -> bool:
        points = curve_ordered(curve)
        return all(points[index + 1][0] >= points[index][0] - 1e-9
                   for index in range(len(points) - 1))

    def nearest_curve_point(curve: dict, px: float, py: float) -> tuple[float, float]:
        return min(curve_ordered(curve),
                   key=lambda point: (point[0] - px) ** 2 + (point[1] - py) ** 2)

    def tangent_at(curve: dict, x0: float, y_hint: float | None = None) -> tuple[float, float] | None:
        values = curve_values(curve)
        if not values:
            return None
        run = _compile_expr(curve.get("expr"), allow_y=False)
        if run is not None:
            h = 1e-4 * max(1.0, abs(x0))
            try:
                y0 = float(run(x0))
            except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                y0 = None
            if y0 is not None:
                # Richardson 外推:两项中心差分消掉 h² 项,斜率比单次差分更稳。
                try:
                    d1 = (run(x0 + h) - run(x0 - h)) / (2 * h)
                    d2 = (run(x0 + h / 2) - run(x0 - h / 2)) / h
                    # 左右导数不一致(尖点/跳跃)时不存在唯一切线,宁可不画。
                    left = (y0 - run(x0 - h)) / h
                    right = (run(x0 + h) - y0) / h
                    scale = max(1.0, abs(left), abs(right))
                    if abs(left - right) > 0.2 * scale:
                        return None
                    return (4 * d2 - d1) / 3, y0
                except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                    # 定义域边界只有单侧导数(sqrt 在 0):先试前向,再试后向。
                    try:
                        return (run(x0 + h) - y0) / h, y0
                    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                        try:
                            return (y0 - run(x0 - h)) / h, y0
                        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                            pass
        ordered = curve_ordered(curve)
        if not is_function_curve(curve) and len(ordered) >= 2:
            # 参数曲线(半圆、椭圆分支)不能按 x 排序;按点列顺序取相邻点。
            hint = y_hint if y_hint is not None else ordered[0][1]
            index = min(range(len(ordered)),
                        key=lambda item: (ordered[item][0] - x0) ** 2
                        + (ordered[item][1] - hint) ** 2)
            if index == 0:
                first, second = ordered[0], ordered[1]
            elif index == len(ordered) - 1:
                first, second = ordered[-2], ordered[-1]
            else:
                first, second = ordered[index - 1], ordered[index + 1]
            dx, dy = second[0] - first[0], second[1] - first[1]
            if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                return None
            if abs(dx) < 1e-9:
                return 1e12, ordered[index][1]
            return dy / dx, ordered[index][1]
        # 无表达式或求值失败:用采样点做五点差分;不足五点退化为左右割线。
        nearest = min(range(len(values)), key=lambda index: abs(values[index][0] - x0))
        if len(values) >= 5 and 2 <= nearest < len(values) - 2:
            step = (values[nearest + 2][0] - values[nearest - 2][0]) / 4
            if step > 1e-9:
                slope = (
                    values[nearest - 2][1] - 8 * values[nearest - 1][1]
                    + 8 * values[nearest + 1][1] - values[nearest + 2][1]
                ) / (12 * step)
                base = values[nearest]
                return slope, base[1] + slope * (x0 - base[0])
        try:
            left = max((item for item in values if item[0] <= x0),
                       key=lambda item: item[0], default=values[0])
            right = min((item for item in values if item[0] >= x0),
                        key=lambda item: item[0], default=values[-1])
            if right[0] <= left[0]:
                return None
            slope = (right[1] - left[1]) / (right[0] - left[0])
            return slope, left[1] + slope * (x0 - left[0])
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def best_curve(px: float, py: float) -> dict:
        """切点落在哪条曲线上:多个分支(y=±√、上下半圆)时不能总用第一条。"""
        best = function_curves[0]
        best_error = float("inf")
        for curve in function_curves:
            error = None
            run = _compile_expr(curve.get("expr"), allow_y=False)
            if run is not None:
                try:
                    error = abs(float(run(px)) - py)
                except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                    error = None
            if error is None:
                values = curve_values(curve)
                if values:
                    error = min(math.hypot(px - x, py - y) for x, y in values)
            if error is not None and error < best_error:
                best, best_error = curve, error
        return best

    # 选点阈值用最大横向跨度,避免多分支时某一支过短导致阈值失效。
    span_ref = 0.0
    for curve in function_curves:
        values = curve_values(curve)
        if len(values) >= 2:
            span_ref = max(span_ref, values[-1][0] - values[0][0])

    used: set[int] = set()
    for tangent in tangents:
        start = tangent.get("from")
        if not (isinstance(start, (list, tuple)) and len(start) >= 2):
            curve_points = tangent.get("points")
            if isinstance(curve_points, list) and curve_points:
                start = curve_points[0]
        end = tangent.get("to")
        if not (isinstance(end, (list, tuple)) and len(end) >= 2):
            curve_points = tangent.get("points")
            if isinstance(curve_points, list) and curve_points:
                end = curve_points[-1]
        if not (isinstance(end, (list, tuple)) and len(end) >= 2):
            end = start
        if not (isinstance(start, (list, tuple)) and len(start) >= 2):
            continue
        try:
            x1, y1 = float(start[0]), float(start[1])
            x2, y2 = float(end[0]), float(end[1])
        except (TypeError, ValueError):
            continue
        vx, vy = x2 - x1, y2 - y1
        length = math.hypot(vx, vy)
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2

        def line_distance(point: dict) -> float:
            """点到切线本身的距离。line 是无限直线,segment 按线段投影。"""
            try:
                px, py = float(point["x"]), float(point["y"])
            except (TypeError, ValueError):
                return float("inf")
            if length < 1e-9:
                return math.hypot(px - x1, py - y1)
            if tangent.get("kind") == "line":
                return abs((px - x1) * vy - (py - y1) * vx) / length
            t = ((px - x1) * vx + (py - y1) * vy) / (length * length)
            t = max(0.0, min(1.0, t))
            return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))

        def score(point: dict) -> float:
            try:
                px, py = float(point["x"]), float(point["y"])
            except (TypeError, ValueError):
                return float("inf")
            curve = best_curve(px, py)
            result = tangent_at(curve, px, py)
            curve_error = abs(py - result[1]) if result is not None else 0.0
            label = str(point.get("label") or "").strip()
            # 切点标签的优先级只做轻微加权,不能压过几何位置。
            boost = -0.5 if re.search(r"切点|tangent point|^P$", label, re.IGNORECASE) else 0.0
            return (line_distance(point) * 2
                    + math.hypot(px - mid_x, py - mid_y) * 0.25
                    + curve_error * 3 + boost)

        candidates = [point for point in points if id(point) not in used]
        point = min(candidates, key=score) if candidates else None
        if point is not None:
            label = str(point.get("label") or "").strip()
            trusted = bool(re.search(r"切点|tangent point|^P$", label, re.IGNORECASE))
            # 图上只有原点 O 时,长切线的中点通常才是真正切点;不要被 O 抢走。
            # 明确标了 P/切点的点优先,不受这条规则影响。
            if (not trusted
                    and abs(float(point["x"]) - mid_x) > max(0.1, span_ref * 0.15)):
                point = None
        if point is not None:
            probe_x, probe_y = float(point["x"]), float(point["y"])
        else:
            probe_x, probe_y = mid_x, mid_y
        curve = best_curve(probe_x, probe_y)
        values = curve_values(curve)
        if not values:
            continue
        span = values[-1][0] - values[0][0]
        span_y = max(value[1] for value in values) - min(value[1] for value in values)
        dx = max(0.2, span * 0.04)
        if point is not None:
            if not is_function_curve(curve):
                px, py = nearest_curve_point(
                    curve, float(point["x"]), float(point["y"]))
                point["x"] = round(px, 6)
                point["y"] = round(py, 6)
            x0 = float(point["x"])
            y_hint = float(point["y"])
        else:
            if not is_function_curve(curve):
                x0, y_hint = nearest_curve_point(curve, mid_x, mid_y)
            else:
                x0 = min(max(mid_x, values[0][0]), values[-1][0])
                y_hint = mid_y
        result = tangent_at(curve, x0, y_hint)
        if result is None:
            # 表达式求值失败或尖点处无唯一切线:删掉模型手画的假切线。
            if tangent in shapes:
                shapes.remove(tangent)
            continue
        slope, y0 = result
        if not math.isfinite(slope) or not math.isfinite(y0):
            continue
        if point is not None:
            point["y"] = round(y0, 6)
            used.add(id(point))
        if abs(slope) > 1e6:
            # 竖直切线:不要用巨大斜率把端点甩出图外。
            dy = max(0.2, span_y * 0.12)
            tangent["from"] = [round(x0, 6), round(y0 - dy, 6)]
            tangent["to"] = [round(x0, 6), round(y0 + dy, 6)]
        else:
            # 陡峭曲线的切线缩短到纵向跨度的 15% 以内,避免压扁主体曲线。
            half = dx
            if abs(slope) > 1e-9:
                half = min(half, max(0.05, span_y * 0.15) / abs(slope))
            half = max(half, 1e-4)
            tangent["from"] = [round(x0 - half, 6), round(y0 - slope * half, 6)]
            tangent["to"] = [round(x0 + half, 6), round(y0 + slope * half, 6)]
        if tangent.get("kind") == "curve":
            tangent["points"] = [tangent["from"], tangent["to"]]
            if not re.search(r"切线|tangent",
                             str(tangent.get("label") or ""), re.IGNORECASE):
                tangent["label"] = "切线"


def _axis_aligned_segment(shape: dict) -> bool:
    """无标签或只标 x/y/z、穿过原点的轴向线段:自动坐标轴已经画了,不要重复。"""
    if shape.get("kind") not in ("segment", "line"):
        return False
    label = str(shape.get("label") or "").strip().lower()
    label = re.sub(r"\s*(?:轴|axis)$", "", label, flags=re.IGNORECASE)
    if label and label not in {"x", "y", "z"}:
        return False
    start = _point(shape.get("from"))
    end = _point(shape.get("to"))
    if start is None or end is None:
        return False
    while len(start) < 3:
        start.append(0.0)
    while len(end) < 3:
        end.append(0.0)
    pairs = [(1, 2), (0, 2), (0, 1)]
    for pair in pairs:
        # pair 里是必须恒为 0 的两个坐标;剩下那个坐标才是线段的方向。
        if not (all(abs(start[index]) < 1e-6 and abs(end[index]) < 1e-6
                    for index in pair)):
            continue
        varying = next(index for index in range(3) if index not in pair)
        a, b = start[varying], end[varying]
        # 两个端点在该轴上都没有变化(例如 2D 线段 z=0→0),不是坐标轴。
        if abs(a) < 1e-9 and abs(b) < 1e-9:
            continue
        if a == 0 or b == 0 or a * b < 0:
            return True
    return False


def _axis_kind(shape: dict) -> str | None:
    label = str(shape.get("label") or "").strip().lower()
    if re.match(r"^x\b|^x[ (]|横", label):
        return "x"
    if re.match(r"^y\b|^y[ (]|纵", label):
        return "y"
    return None


def normalize_2d_axes(shapes: list[dict]) -> None:
    """所有 2D 坐标图的 x/y 轴统一为正交轴,长度由实际数据决定。"""
    axes = [shape for shape in shapes if shape.get("kind") == "axis"]
    if not axes:
        return
    xs: list[float] = [0.0]
    ys: list[float] = [0.0]
    for shape in shapes:
        if shape.get("kind") == "axis":
            continue
        kind = shape.get("kind")
        try:
            if kind in ("point", "circle"):
                xs.append(float(shape.get("x", 0)))
                ys.append(float(shape.get("y", 0)))
                radius = abs(float(shape.get("r", shape.get("radius", 0)) or 0))
                xs.extend((xs[-1] - radius, xs[-1] + radius))
                ys.extend((ys[-1] - radius, ys[-1] + radius))
            elif kind in ("segment", "line", "vector"):
                for key in ("from", "to"):
                    point = _point(shape.get(key))
                    if point:
                        xs.append(float(point[0]))
                        ys.append(float(point[1]))
            elif kind in ("curve", "polygon", "surface"):
                for item in shape.get("points") or []:
                    point = _point(item)
                    if point:
                        xs.append(float(point[0]))
                        ys.append(float(point[1]))
        except (TypeError, ValueError):
            continue
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    for axis in axes:
        kind = _axis_kind(axis)
        if kind == "x":
            axis["from"] = [min_x, 0.0]
            axis["to"] = [max_x, 0.0]
        elif kind == "y":
            axis["from"] = [0.0, min_y]
            axis["to"] = [0.0, max_y]


def prune_node_decorations(diagram: dict) -> None:
    """节点型图(tree/relation/flow)只能有节点和边;坐标轴/几何形状/散落注释一律清掉。"""
    if diagram.get("type") in ("tree", "relation", "flow"):
        diagram["shapes"] = []
        diagram["annotations"] = []


def _norm_label(value: object) -> str:
    text = re.sub(r"[\s=^]", "", str(value or "")).lower()
    return text.replace("²", "2").replace("³", "3")


_LABEL_Y_RE = re.compile(r"y\s*=\s*([-+]?\d+(?:\.\d+)?)\s*(?=$|[\s，,。;；)）])")
_LABEL_X_RE = re.compile(r"x\s*=\s*([-+]?\d+(?:\.\d+)?)\s*(?=$|[\s，,。;；)）])")


def _align_axis_labels(note: dict) -> bool:
    """把 “水平渐近线 y=0 / 垂直渐近线 x=0” 这类标注钉到对应坐标轴上。

    模型给的标注坐标经常漂移;文字里已经写明 y=0 / x=0 时,以文字为准。
    返回 True 表示已按文字定位,不再参与曲线吸附。"""
    text = str(note.get("text") or "")
    ym = _LABEL_Y_RE.search(text)
    xm = _LABEL_X_RE.search(text)
    if not ym and not xm:
        return False
    if ym and not xm:
        note["y"] = float(ym.group(1))
    elif xm and not ym:
        note["x"] = float(xm.group(1))
    else:
        note["x"] = float(xm.group(1))
        note["y"] = float(ym.group(1))
    return True


def _snap_annotations(shapes: list[dict], raw: dict) -> dict:
    """plot2d 标注点吸附到曲线上。

    模型给的标注坐标经常差一点或干脆指错位置。能算出曲线的图里,
    近的把 y 校正到曲线值,远到离谱的直接丢弃(宁可不标,不可错标)。
    多条曲线时分不清归属,只吸附不丢弃。"""
    notes = raw.get("annotations")
    if not isinstance(notes, list) or not notes:
        return raw
    curves = [
        shape for shape in shapes
        if shape.get("kind") == "curve" and shape.get("expr") and shape.get("points")
    ]
    if not curves:
        return raw
    runners = []
    for curve in curves:
        run = _compile_expr(curve.get("expr"), allow_y=False)
        if run is None:
            continue
        xs = [float(item[0]) for item in curve["points"]]
        ys = [float(item[1]) for item in curve["points"]]
        if not xs:
            continue
        runners.append((run, min(xs), max(xs), max(ys) - min(ys)))
    if not runners:
        return raw
    strict = len(runners) == 1
    kept: list[dict] = []
    for note in notes:
        if not isinstance(note, dict):
            kept.append(note)
            continue
        if _align_axis_labels(note):
            kept.append(note)
            continue
        x, y = _num(note.get("x")), _num(note.get("y"))
        if x is None or y is None or "z" in note:
            kept.append(note)
            continue
        best: tuple[float, float] | None = None  # (距离, 曲线上的 y)
        for run, x0, x1, span_y in runners:
            if not (x0 - 1e-9 <= x <= x1 + 1e-9):
                continue
            try:
                actual = float(run(x))
            except (ValueError, ZeroDivisionError, OverflowError, TypeError):
                continue
            distance = abs(actual - y)
            if best is None or distance < best[0]:
                best = (distance, actual)
        if best is None:
            kept.append(note)
            continue
        distance, actual = best
        span = max(1.0, runners[0][3])
        # 1/x、tan 的极端值会把整幅跨度撑大;吸附容差必须封顶,
        # 否则离曲线很远的说明文字会被硬拽到曲线附近。
        tolerance = min(max(1e-6, span * 0.02), 0.5)
        if distance <= tolerance:
            kept.append({**note, "y": round(actual, 6)})
        elif strict and distance > max(tolerance * 3, span * 0.25):
            # 远到不可能只是排版偏移(例如曲线值域 [-2,2] 却标到 y=50):丢弃。
            continue
        else:
            kept.append(note)
    return {**raw, "annotations": kept}


_SURFACE_CLAUSE_RE = re.compile(r"[，,。;；、]|和|与|及|以及|并且")
_SURFACE_EXPR_RE = re.compile(r"(?<![A-Za-z])z\s*=\s*([0-9A-Za-z_.^*/()+\-\s]+)")


def _surface_question_terms(question: str) -> tuple[str | None, float | None]:
    """从用户原话里提取 z=f(x,y) 与水平平面 z=c,只用于修补模型漏给的字段。"""
    expr: str | None = None
    plane_values: set[float] = set()
    for clause in _SURFACE_CLAUSE_RE.split(question or ""):
        # 一个分句里可能同时出现曲面方程和截平面(如“z=x^2+y^2 被 z=1 截下”),
        # 只 search 第一个会漏掉截平面高度,投影圆半径就只能用渲染器默认值。
        for match in _SURFACE_EXPR_RE.finditer(clause):
            value = match.group(1).strip()
            if not value:
                continue
            if re.search(r"[xy]", value, re.IGNORECASE):
                if expr is None:
                    expr = value
                continue
            number = re.match(r"[-+]?\d+(?:\.\d+)?", value)
            if number:
                parsed = _num(number.group(0))
                if parsed is not None:
                    plane_values.add(round(parsed, 9))
    # 多个不同高度的平面无法判断哪个缺坐标;不猜,保留模型值。
    plane_z = next(iter(plane_values)) if len(plane_values) == 1 else None
    return expr, plane_z


def repair_surface_shapes(raw: dict, question: str) -> dict:
    """修补三维曲面图里的漏坐标:平面/圆落到 z=c,曲面按题面表达式补回。

    模型常只给 normal 或半径,渲染器会把缺省坐标当成 0,于是 z=1 的平面
    被画到 z=0。这里只用用户题面里明确写出的表达式和数值,不猜。
    """
    if raw.get("type") not in ("surface3d", "geometry3d"):
        return raw
    expr, plane_z = _surface_question_terms(question)
    shapes = raw.get("shapes")
    if not isinstance(shapes, list):
        shapes = []
    if not expr and plane_z is None:
        _add_projection_shape(shapes, question)
        return {**raw, "shapes": shapes}
    if expr and not any(
            isinstance(shape, dict)
            and shape.get("kind") in ("surface", "parametric_surface",
                                      "implicit_surface")
            for shape in shapes):
        shapes.insert(0, {
            "kind": "surface", "expr": expr,
            "domain": [-2.0, 2.0, -2.0, 2.0],
            "rows": 30, "cols": 30,
        })
    if plane_z is not None:
        missing_planes = [
            shape for shape in shapes
            if isinstance(shape, dict) and shape.get("kind") == "plane"
            and not all(isinstance(shape.get(key), (int, float))
                        for key in ("x", "y", "z"))
        ]
        # 多张缺坐标的平面无法判断哪张对应 z=c;不批量填同一个高度。
        fill_planes = len(missing_planes) == 1
        for shape in shapes:
            if not isinstance(shape, dict):
                continue
            kind = shape.get("kind")
            if kind == "plane":
                if not fill_planes:
                    continue
                normal = shape.get("normal")
                # 只有水平平面(法向 z 轴,或模型没给法向)才能由 z=c 唯一定位。
                # 倾斜平面缺中心坐标时,填 z=c 会把它画到错误位置,宁可丢弃。
                if isinstance(normal, (list, tuple)) and len(normal) >= 3:
                    try:
                        nx, ny, nz = (float(normal[0]), float(normal[1]),
                                      float(normal[2]))
                    except (TypeError, ValueError):
                        continue
                    if math.hypot(nx, ny) > 1e-6 or abs(nz) < 1e-9:
                        continue
                shape.setdefault("x", 0.0)
                shape.setdefault("y", 0.0)
                shape.setdefault("z", plane_z)
                shape.setdefault("normal", [0.0, 0.0, 1.0])
                shape.setdefault("width", 4.0)
                shape.setdefault("height", 4.0)
            elif kind == "circle":
                # 投影圆盘落在 z=0;截口圆落在 z=plane_z。仅补缺失坐标,不改模型显式值。
                label = str(shape.get("label") or "")
                at_projection = bool(re.search(
                    r"投影|projection|xoy|xy\s*面", label, re.IGNORECASE))
                shape.setdefault("x", 0.0)
                shape.setdefault("y", 0.0)
                shape.setdefault("z", 0.0 if at_projection else plane_z)
                if not any(isinstance(shape.get(key), (int, float))
                           for key in ("r", "radius")) and expr:
                    simple = re.fullmatch(
                        r"\s*x\s*\^\s*2\s*\+\s*y\s*\^\s*2\s*",
                        expr, re.IGNORECASE)
                    if simple and plane_z > 0:
                        shape["r"] = math.sqrt(plane_z)
    _add_projection_shape(shapes, question)
    return {**raw, "shapes": shapes}


def _add_projection_shape(shapes: list[dict], question: str) -> None:
    """题面/图注明确要投影,但模型只画了截口或没画投影时,补一个可渲染的投影。

    只做确定性的垂直投影:把水平截口圆/边界曲线降到 z=0;都没有时用曲面
    采样点的 xy 范围补一个矩形区域。投影只作为辅助注记,不改变原曲面。
    """
    if not re.search(r"投影|projection", question or "", re.IGNORECASE):
        return
    if any(re.search(r"投影|projection", str(shape.get("label") or ""),
                     re.IGNORECASE)
           for shape in shapes):
        return

    def projected_label(text: str) -> str:
        if _has_cjk(question):
            return f"投影 D: {text}" if text else "投影区域 D"
        return f"Projection D: {text}" if text else "Projection region D"

    # 1) 水平截口圆 → 同半径、同圆心的 z=0 圆
    for shape in shapes:
        if shape.get("kind") != "circle":
            continue
        radius = shape.get("r") if isinstance(shape.get("r"), (int, float)) else shape.get("radius")
        z = shape.get("z")
        if not isinstance(radius, (int, float)) or radius <= 0:
            continue
        if not isinstance(z, (int, float)) or abs(z) < 1e-9:
            continue
        shapes.append({
            "kind": "circle",
            "x": shape.get("x", 0.0),
            "y": shape.get("y", 0.0),
            "z": 0.0,
            "r": float(radius),
            "label": projected_label(str(shape.get("label") or "")),
            "color": "#ff4dd2",
        })
        return

    # 2) 边界折线/曲线 → 投影到 z=0
    for shape in shapes:
        if shape.get("kind") not in ("polygon", "curve"):
            continue
        pts = shape.get("points")
        if not isinstance(pts, list) or len(pts) < 2:
            continue
        projected = []
        for item in pts:
            point = _point(item)
            if point and len(point) >= 2:
                projected.append([point[0], point[1], 0.0])
        if len(projected) >= 2:
            shapes.append({
                "kind": "polygon" if shape.get("kind") == "polygon" else "curve",
                "points": projected,
                "label": projected_label(str(shape.get("label") or "")),
                "color": "#ff4dd2",
            })
            return

    # 3) 只有曲面采样点 → 用 xy 范围补矩形投影
    surface = next((shape for shape in shapes
                    if shape.get("kind") in ("surface", "parametric_surface")
                    and isinstance(shape.get("points"), list)
                    and len(shape["points"]) >= 2), None)
    if surface is None:
        implicit = next((shape for shape in shapes
                         if shape.get("kind") == "implicit_surface"
                         and isinstance(shape.get("positions"), list)
                         and len(shape["positions"]) >= 6), None)
        if implicit is None:
            return
        flat = implicit["positions"]
        xs = [float(flat[index]) for index in range(0, len(flat) - 2, 3)]
        ys = [float(flat[index]) for index in range(1, len(flat) - 1, 3)]
    else:
        xs, ys = [], []
        for item in surface["points"]:
            point = _point(item)
            if point and len(point) >= 2:
                xs.append(point[0])
                ys.append(point[1])
    if not xs or not ys:
        return
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    shapes.append({
        "kind": "polygon",
        "points": [[x0, y0, 0.0], [x1, y0, 0.0], [x1, y1, 0.0], [x0, y1, 0.0]],
        "label": "投影区域 D" if _has_cjk(question) else "Projection region D",
        "color": "#ff4dd2",
    })


def prepare_diagram(raw: object) -> dict | None:
    """采样表达式形状后再做白名单校验。"""
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("linear"), dict):
        built = linear_algebra.build_linear_diagram(raw)
        if built is None:
            return None
        raw = built
    shapes = raw.get("shapes")
    if isinstance(shapes, list) and len(shapes) <= _MAX_SHAPES:
        dict_shapes: list[dict] = []
        for shape in shapes:
            if not isinstance(shape, dict) or not _sample_shape(shape):
                continue
            clean = _shape(shape)
            if clean is not None:
                dict_shapes.append(clean)
        _materialize_tangent_objects(dict_shapes)
        _refine_gradient(dict_shapes)
        _refine_surface_normal(dict_shapes)
        for shape in dict_shapes:
            if (shape.get("kind") == "surface" and shape.get("expr")
                    and not shape.get("label")):
                shape["label"] = f"z={_pretty_expr(shape['expr'])}"
            elif shape.get("kind") == "parametric_surface" and not shape.get("label"):
                shape["label"] = "参数曲面"
            elif shape.get("kind") == "implicit_surface" and not shape.get("label"):
                shape["label"] = "隐式曲面"
        if raw.get("type") in ("plot2d", "geometry2d"):
            _refine_implicit_curve_tangents(dict_shapes)
            _refine_ellipse_tangents(dict_shapes)
            _refine_circle_tangents(dict_shapes)
            _refine_plot2d(dict_shapes, raw.get("type") == "plot2d")
            normalize_2d_axes(dict_shapes)
            if raw.get("type") == "plot2d":
                raw = _snap_annotations(dict_shapes, raw)
        if (raw.get("type") in ("geometry3d", "surface3d")
                and not isinstance(raw.get("linear"), dict)):
            _refine_ellipse3d_tangents(dict_shapes)
            _refine_circle3d_tangents(dict_shapes)
            _refine_curve3d_tangents(dict_shapes)
            dict_shapes = [shape for shape in dict_shapes
                           if shape.get("kind") != "axis"
                           and not _axis_aligned_segment(shape)]
            notes = raw.get("annotations")
            if isinstance(notes, list):
                raw = {**raw, "annotations": [
                    note for note in notes
                    if not (isinstance(note, dict)
                            and re.fullmatch(
                                r"[xyz]\s*轴?",
                                _text(note.get("text"), 20).strip(),
                                re.IGNORECASE))
                ]}
        _compact_meshes(dict_shapes)
        raw = {**raw, "shapes": dict_shapes}
        labels = {
            _norm_label(shape.get("label"))
            for shape in dict_shapes if shape.get("label")
        }
        if labels and isinstance(raw.get("annotations"), list):
            raw = {**raw, "annotations": [
                note for note in raw["annotations"]
                if isinstance(note, dict)
                and _norm_label(note.get("text")) not in labels
            ]}
    diagram = validate_diagram(raw)
    if diagram is not None:
        prune_node_decorations(diagram)
    return diagram



def build_data_plot(table_id: str, x: str, y: str,
                    fit_result: dict) -> dict | None:
    """用回归服务返回的真实点/拟合曲线构建 plot2d;模型不参与数值。"""
    if not isinstance(fit_result, dict):
        return None
    raw_points = fit_result.get("points")
    if not isinstance(raw_points, list) or not raw_points:
        return None
    points: list[list[float]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            continue
        x_value = _num(item.get("x") if "x" in item else item.get("row"))
        y_value = _num(item.get("actual"))
        if x_value is None or y_value is None:
            return None
        points.append([x_value, y_value])
    if not points:
        return None
    total_points = len(points)
    max_points = _MAX_SHAPES - 3
    if total_points > max_points:
        points = [points[i * (total_points - 1) // (max_points - 1)]
                  for i in range(max_points)]

    shapes: list[dict] = [
        {"kind": "axis", "from": [0, 0], "to": [1, 0], "label": str(x)[:40]},
        {"kind": "axis", "from": [0, 0], "to": [0, 1], "label": str(y)[:40]},
    ]
    shapes.extend({"kind": "point", "x": point[0], "y": point[1]}
                  for point in points)

    raw_curve = fit_result.get("fitCurve")
    curve: list[list[float]] = []
    if isinstance(raw_curve, list):
        for item in raw_curve[:200]:
            if not isinstance(item, dict):
                continue
            x_value = _num(item.get("x"))
            y_value = _num(item.get("y"))
            if x_value is None or y_value is None:
                curve.clear()
                break
            curve.append([x_value, y_value])
    if len(curve) >= 2:
        shapes.append({"kind": "curve", "points": curve, "color": "#4dd6ff"})

    equation = str(fit_result.get("equation") or "").strip()
    title = f"{str(y)[:40]} ~ {str(x)[:40]}"
    if total_points > len(points):
        title += f" (显示 {len(points)}/{total_points} 点)"
    if equation:
        title = f"{title}: {equation[:120]}"
    return prepare_diagram({
        "type": "plot2d",
        "title": title[:200],
        "shapes": shapes,
        "annotations": [],
    })


def _shape(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("kind"), 40)
    if kind not in _SHAPES:
        return None
    # 切线的语义对象:落到渲染层仍是 segment;没有起止点就无法画。
    tangent_alias = kind == "tangent"
    if tangent_alias:
        has_segment = (isinstance(raw.get("from"), (list, tuple))
                       and isinstance(raw.get("to"), (list, tuple)))
        has_target = (isinstance(raw.get("curve"), str)
                      and raw.get("curve").strip()
                      and _num(raw.get("x")) is not None)
        if not (has_segment or has_target):
            return None
        if has_segment:
            kind = "segment"
    out: dict = {"kind": kind}
    for key in ("x", "y", "z", "r", "radius", "width", "height", "depth",
                "rx", "ry", "rotation"):
        if key in raw:
            parsed = _num(raw[key])
            if parsed is not None:
                out[key] = parsed
    for key in ("rows", "cols", "samples"):
        if key in raw:
            parsed = _num(raw[key])
            if parsed is not None and parsed.is_integer():
                cap = 3000 if key == "samples" else _MAX_SURFACE_GRID
                out[key] = max(2, min(cap, int(parsed)))
    for key in ("label", "expr", "expr2", "curve", "color", "xexpr",
                "yexpr", "zexpr", "fieldexpr"):
        if key in raw:
            value = _text(raw[key], 200)
            if key == "label" and value.lower() in {"djj"}:
                # 模型偶发的无意义占位标签,不进图。
                value = ""
            if value:
                out[key] = value
    if tangent_alias and not out.get("label"):
        out["label"] = "切线"
    if "domain" in raw:
        domain = raw["domain"]
        if isinstance(domain, (list, tuple)) and len(domain) in (2, 4, 6):
            parsed = [_num(item) for item in domain]
            if all(item is not None for item in parsed):
                out["domain"] = parsed
    if "resolution" in raw:
        parsed = _num(raw["resolution"])
        if parsed is not None:
            out["resolution"] = max(8, min(76, int(parsed)))
    if "points" in raw:
        points = raw["points"]
        if isinstance(points, list):
            cleaned: list[list[float]] = []
            for item in points[:2000]:
                point = _point(item)
                if point is not None:
                    cleaned.append(point)
            if cleaned:
                out["points"] = cleaned
    for key in ("positions_b64", "indices_b64"):
        if isinstance(raw.get(key), str) and raw[key]:
            out[key] = raw[key][:12_000_000]
    for key in ("vertexCount", "indexCount"):
        if key in raw:
            try:
                parsed = int(raw[key])
            except (TypeError, ValueError, OverflowError):
                parsed = None
            if parsed is not None and parsed >= 0:
                out[key] = parsed
    if isinstance(raw.get("encoding"), str) and raw["encoding"]:
        out["encoding"] = _text(raw["encoding"], 40)
    if isinstance(raw.get("indexType"), str) and raw["indexType"] in ("u16", "u32"):
        out["indexType"] = raw["indexType"]
    if "positions" in raw:
        raw_positions = raw["positions"]
        if isinstance(raw_positions, list):
            cleaned_positions = [_num(item) for item in raw_positions[:300000]]
            if all(item is not None for item in cleaned_positions):
                out["positions"] = [float(item) for item in cleaned_positions]
    if "indices" in raw:
        raw_indices = raw["indices"]
        if isinstance(raw_indices, list):
            cleaned_indices = []
            for item in raw_indices[:300000]:
                value = _num(item)
                if value is not None and value >= 0:
                    cleaned_indices.append(int(value))
            if cleaned_indices:
                max_vertex = len(out.get("positions", [])) // 3
                cleaned_indices = [item for item in cleaned_indices
                                   if item < max_vertex]
                cleaned_indices = cleaned_indices[
                    :len(cleaned_indices) // 3 * 3]
                if cleaned_indices:
                    out["indices"] = cleaned_indices
    if "segments" in raw:
        # 多段曲线:每段至少 2 点,总点数与 points 共用同一预算。
        raw_segments = raw["segments"]
        if isinstance(raw_segments, list):
            cleaned_segments: list[list[list[float]]] = []
            budget = 0
            for segment in raw_segments[:200]:
                if not isinstance(segment, list) or budget >= 2000:
                    continue
                pts: list[list[float]] = []
                for item in segment[:2000 - budget]:
                    point = _point(item)
                    if point is not None:
                        pts.append(point)
                if len(pts) >= 2:
                    cleaned_segments.append(pts)
                    budget += len(pts)
            if cleaned_segments:
                out["segments"] = cleaned_segments
    for key in ("from", "to", "normal"):
        if key in raw:
            point = _point(raw[key])
            if point is not None:
                out[key] = point
    if kind in ("segment", "line", "vector", "axis"):
        if "from" not in out or "to" not in out:
            return None
    if kind in ("point",) and ("x" not in out or "y" not in out):
        return None
    if kind in ("surface", "polygon") and not out.get("points"):
        return None
    return out


def _renderable_shape(shape: dict, diagram_type: str = "") -> bool:
    """没有实际可画几何的旧图解(例如只有 expr 没有采样点)不能进渲染器。"""
    kind = shape.get("kind")
    spatial = diagram_type in ("geometry3d", "surface3d")
    if kind == "axis":
        return False
    if kind in ("curve", "polygon", "surface", "parametric_surface",
                "parametric_curve"):
        return bool(shape.get("points"))
    if kind in ("implicit_curve", "implicit_curve3d"):
        return bool(shape.get("segments") or shape.get("points"))
    if kind == "implicit_surface":
        if (isinstance(shape.get("positions_b64"), str)
                and isinstance(shape.get("indices_b64"), str)):
            return (int(shape.get("vertexCount", 0)) >= 3
                    and int(shape.get("indexCount", 0)) >= 3)
        return (isinstance(shape.get("positions"), list)
                and len(shape["positions"]) >= 9
                and isinstance(shape.get("indices"), list)
                and len(shape["indices"]) >= 3)
    if kind == "ellipse":
        if not ("x" in shape and "y" in shape
                and float(shape.get("rx", 0) or 0) > 1e-9
                and float(shape.get("ry", 0) or 0) > 1e-9):
            return False
        # 3D 椭圆必须有 z;所在平面由 normal 决定(缺省为水平面)。
        return (not spatial) or "z" in shape
    if kind in ("segment", "line", "vector"):
        start, end = shape.get("from"), shape.get("to")
        if not (isinstance(start, list) and isinstance(end, list)
                and len(start) >= 2 and len(end) >= 2):
            return False
        try:
            distance = math.sqrt(sum((float(b) - float(a)) ** 2
                                     for a, b in zip(start, end)))
        except (TypeError, ValueError):
            return False
        # 零长度箭头/线段在渲染器里不可见;留在图里只会让标签指向空气。
        return math.isfinite(distance) and distance > 1e-6
    if kind in ("point", "circle"):
        if spatial and kind == "circle":
            # 三维圆的中心缺 z 会被渲染器当成 0;宁可丢弃,也不画错位置。
            return all(key in shape for key in ("x", "y", "z"))
        return "x" in shape and "y" in shape
    if kind == "plane":
        # 平面只给了法向量时,渲染器会把位置默认成原点;这不是“过原点的平面”,
        # 而是未知位置。必须要求显式中心坐标。
        return (not spatial) or all(key in shape for key in ("x", "y", "z"))
    return True


def validate_diagram(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    version = raw.get("schemaVersion")
    if version is not None:
        try:
            parsed_version = int(version)
        except (TypeError, ValueError):
            return None
        if parsed_version > DIAGRAM_SCHEMA_VERSION:
            return None
    kind = _text(raw.get("type"), 40)
    if kind not in _TYPES:
        return None

    nodes: list[dict] = []
    ids: set[str] = set()
    raw_nodes = raw.get("nodes")
    if isinstance(raw_nodes, list):
        if len(raw_nodes) > _MAX_NODES:
            return None
        for item in raw_nodes:
            if not isinstance(item, dict):
                continue
            node_id = _text(item.get("id"), 64)
            label = _text(item.get("label"), 200)
            if not node_id or not label or node_id in ids:
                continue
            ids.add(node_id)
            node = {"id": node_id, "label": label}
            node_kind = _text(item.get("kind"), 40)
            if node_kind:
                node["kind"] = node_kind
            page = _num(item.get("page"))
            if page is not None and page.is_integer() and page > 0:
                node["page"] = int(page)
            nodes.append(node)

    edges: list[dict] = []
    raw_edges = raw.get("edges")
    if isinstance(raw_edges, list):
        if len(raw_edges) > _MAX_EDGES:
            return None
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            start = _text(item.get("from"), 64)
            end = _text(item.get("to"), 64)
            if not start or not end:
                continue
            if ids and (start not in ids or end not in ids):
                continue
            edge = {"from": start, "to": end}
            label = _text(item.get("label"), 200)
            if label:
                edge["label"] = label
            edge_kind = _text(item.get("kind"), 40)
            if edge_kind:
                edge["kind"] = edge_kind
            edges.append(edge)

    shapes: list[dict] = []
    raw_shapes = raw.get("shapes")
    if isinstance(raw_shapes, list):
        if len(raw_shapes) > _MAX_SHAPES:
            return None
        for item in raw_shapes:
            shape = _shape(item)
            if shape is not None and (
                    shape.get("kind") == "axis"
                    or _renderable_shape(shape, kind)):
                shapes.append(shape)

    annotations: list[dict] = []
    seen_notes: set[tuple[float, float, float]] = set()
    raw_notes = raw.get("annotations")
    if isinstance(raw_notes, list):
        if len(raw_notes) > _MAX_ANNOTATIONS:
            return None
        for item in raw_notes:
            if not isinstance(item, dict):
                continue
            x, y = _num(item.get("x")), _num(item.get("y"))
            text = _text(item.get("text"), 400)
            if x is None or y is None or not text:
                continue
            note = {"x": x, "y": y, "text": text}
            z = _num(item.get("z"))
            if z is not None:
                note["z"] = z
            key = (round(x, 3), round(y, 3), round(z or 0.0, 3))
            if key in seen_notes:
                continue
            seen_notes.add(key)
            annotations.append(note)

    if not nodes and not shapes and not annotations:
        return None
    # 类型与结构必须自洽:关系/流程/树必须有节点,几何/曲线/三维必须有形状。
    # 否则会渲染成空白图或错误图,这是“默认关系图”这类问题的最后一道闸。
    if kind in ("tree", "relation", "flow"):
        if not nodes:
            return None
    elif not shapes or not any(_renderable_shape(shape, kind) for shape in shapes):
        return None
    if kind == "surface3d" and not any(
            shape.get("kind") in ("surface", "parametric_surface", "implicit_surface")
            for shape in shapes):
        # surface3d 没有曲面只剩平面/点,是模型漏掉主体后的残图;不拿它冒充曲面图。
        return None
    result: dict = {
        "schemaVersion": DIAGRAM_SCHEMA_VERSION,
        "type": kind, "nodes": nodes, "edges": edges,
        "shapes": shapes, "annotations": annotations,
    }
    linear = linear_algebra.sanitize_linear(raw.get("linear"))
    if linear is not None:
        result["linear"] = linear
    title = _text(raw.get("title"), 200)
    if title:
        result["title"] = title
    view = raw.get("view")
    if isinstance(view, dict):
        x, y, zoom = _num(view.get("x")), _num(view.get("y")), _num(view.get("zoom"))
        if x is not None and y is not None and zoom is not None and zoom > 0:
            result["view"] = {
                "x": x, "y": y, "zoom": max(0.1, min(8.0, zoom)),
            }
    return result


@dataclass
class DiagramMarker:
    anchor_id: str
    kind: str
    anchor_index: int


class MarkerStream:
    """逐 delta 剥离隐藏标记;完整 marker 交给调用方规划图解。"""

    MAX_MARKER = 80

    def __init__(self, request_id: str):
        self.request_id = request_id[:80]
        self._buffer = ""
        self._visible_len = 0
        self._markers: list[DiagramMarker] = []
        self._count = 0

    def _partial_prefix(self) -> int:
        for size in range(min(len(self._buffer), len(PREFIX)), 0, -1):
            if self._buffer.endswith(PREFIX[:size]):
                return size
        return 0

    def _emit(self, out: list[str], text: str) -> None:
        if not text:
            return
        out.append(text)
        # 前端 JS 字符串按 UTF-16 code unit 计数,emoji 不能按 Python 码点算。
        self._visible_len += len(text.encode("utf-16-le")) // 2

    def _malformed_tail(self, text: str) -> str:
        """未闭合/畸形标记整段剥掉;标记后真正跟的正文要保留。
        类型名可能被模型写成大写或被截断,不能只按小写字母清理,
        否则会残留 D]] / DJJ 之类碎片。"""
        tail = text[len(PREFIX):] if text.startswith(PREFIX) else text
        return re.sub(
            r"^(?:type=)?[A-Za-z0-9_:=.\-]*\]*", "", tail,
            flags=re.IGNORECASE)

    def feed(self, text: str) -> str:
        self._buffer += text or ""
        out: list[str] = []
        while True:
            start = self._buffer.find(PREFIX)
            if start < 0:
                hold = self._partial_prefix()
                if hold:
                    if len(self._buffer) > hold:
                        self._emit(out, self._buffer[:-hold])
                    self._buffer = self._buffer[-hold:]
                else:
                    self._emit(out, self._buffer)
                    self._buffer = ""
                break
            if start:
                self._emit(out, self._buffer[:start])
            end = self._buffer.find("]]", start)
            if end < 0:
                if len(self._buffer) - start > self.MAX_MARKER:
                    tail = self._malformed_tail(self._buffer[start:])
                    self._emit(out, tail)
                    self._buffer = ""
                else:
                    self._buffer = self._buffer[start:]
                break
            raw = self._buffer[start:end + 2]
            self._buffer = self._buffer[end + 2:]
            match = _MARKER_RE.fullmatch(raw)
            if not match:
                # 畸形标记不能吞掉中间正文;保留标记以外内容。
                self._emit(out, self._malformed_tail(raw))
                continue
            kind = match.group(1)
            if kind not in _TYPES:
                continue
            self._count += 1
            self._markers.append(DiagramMarker(
                anchor_id=f"{self.request_id}-{self._count}",
                kind=kind,
                anchor_index=self._visible_len,
            ))
        return "".join(out)

    def drain(self) -> list[DiagramMarker]:
        out = self._markers
        self._markers = []
        return out

    def finish(self) -> str:
        if not self._buffer:
            return ""
        tail = self._malformed_tail(self._buffer)
        self._buffer = ""
        return tail


def diagram_event(diagram: dict, request_id: str, anchor_id: str,
                  anchor_index: int) -> str:
    try:
        payload = json.dumps({
            "mg_event": "diagram",
            "requestId": request_id,
            "anchorId": anchor_id,
            "anchorIndex": anchor_index,
            "diagram": diagram,
        }, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return ""
    return "data: " + payload + "\n\n"


_PLAN_SYSTEM_RESEARCH = (
    "你是 MathGuide 的科研图解规划器。只把【论文片段】【数据表】【计算结果】"
    "中真实出现的对象、关系或数值画出来。\n"
    "科研图服务于方法流程、模型结构、数据关系或实验设计,不要套用教学步骤模板。\n"
    "硬规则:\n"
    "1. 数据点必须来自数据表或服务端的确定性计算结果;禁止编造、估读、"
    "手写拟合系数或把示例数值当成真实数据。\n"
    "2. 散点、拟合线、残差图由服务端用回归结果确定性构建;你只表达 dataPlot 意图,"
    "不要自己写散点坐标或拟合系数。\n"
    "3. 资料不足、没有数据表、没有计算结果时,不要画图;正文说明资料不足。\n"
    "4. 只画这一段真正需要的图,不画装饰性坐标轴,不把论文结论画成空泛关系网。\n"
    "5. 只输出一个 JSON 对象,不要解释,不要 Markdown 代码块。"
)

_PLAN_SYSTEM = (
    "你是 MathGuide 的图解规划器。用户正在听讲解,你需要把【标记前最新一段】"
    "所讲的内容画成一张静态图解,帮助学生看懂这一步。\n"
    "只输出一个 JSON 对象,不要解释,不要 Markdown 代码块。\n"
    "类型要求为“硬性”时必须等于【请求图解类型】;为“建议”或“自选”时,"
    "根据这一段内容自主选择最合适的类型,不要机械沿用建议。2D/3D 选择:"
    "一元函数及其导数用 2D;多元函数、偏导数、曲面、梯度用 3D;"
    "平面几何、函数曲线、二维关系用 2D;空间对象、立体结构用 3D;"
    "用户没指定维度时按内容权重判断,不要默认 2D;能用 2D 讲清就不要硬上 3D。"
    "各类型结构:\n"
    '- flow/tree/relation:{"nodes":[{"id":"a","label":"概念"}],'
    '"edges":[{"from":"a","to":"b","label":"推出"}]}\n'
    '- geometry2d/plot2d:{"shapes":[{"kind":"point|segment|vector|circle|ellipse|'
    'polygon|curve|implicit_curve|parametric_curve|axis","x":0,"y":0,"from":[0,0],"to":[1,1],'
    '"points":[[x,y]],"rx":2,"ry":1,"rotation":0,"label":"A"}],'
    '"annotations":[{"x":0,"y":0,"text":"说明"}]}\n'
    '- geometry3d:{"shapes":[{"kind":"point|segment|vector|plane|sphere|box|'
    'cone|cylinder|circle|ellipse|parametric_curve|implicit_curve3d","x":0,"y":0,"z":0,"from":[0,0,0],"to":[1,1,1],'
    '"normal":[0,0,1],"label":"A"}],"annotations":[{"x":0,"y":0,"z":0,'
    '"text":"说明"}]}\n'
    '- surface3d:用 {"kind":"surface","expr":"x^2+y^2","domain":[-3,3],'
    '"rows":25,"cols":25} 表示显式曲面;参数曲面用 '
    '{"kind":"parametric_surface","xexpr":"cos(u)*sin(v)",'
    '"yexpr":"sin(u)*sin(v)","zexpr":"cos(v)",'
    '"domain":[0,6.283,0,3.142],"rows":25,"cols":25};'
    '隐式曲面用 {"kind":"implicit_surface","expr":"x^2+y^2+z^2-1",'
    '"domain":[-1.5,1.5,-1.5,1.5,-1.5,1.5],"resolution":24};'
    '用 {"kind":"vector","from":[x,y,z],"to":[x,y,z]} 表示方向;'
    '用 {"kind":"point","x":x,"y":y,"z":z} 标出关键点。\n'
    "规则:\n"
    "1. 只图解最新一段的内容,不要把前文所有内容塞进同一张图。\n"
    "2. 只使用【用户问题】【当前回答】【资料】里出现的内容,不得虚构关系或数据。\n"
    "3. 用户明确要求三维/三维坐标系/画图/几何直观时,直接按该表示方式画;"
    "relation 只在内容本身是概念关系网时使用,tree 只用于层级结构。\n"
    "4. 抽象概念要化抽象为具体:先找一个人人能看见的类比物(如把梯度想成"
    "山坡上最陡的上坡方向、把概率密度想成沙堆高度),再把它画成具体图形;"
    "不要只把抽象名词连成关系网。2D 还是 3D 按哪种更能表现该意象来选。\n"
    "5. 一张教学图只保留这一步的关键对象,关系图/流程图节点一般 3–8 个;"
    "硬上限:节点 40、边 80、形状 100、曲面网格 101×101。\n"
    "6. 坐标用可读的数学坐标;给出 title,关键对象给 label。\n"
    "7. 不要输出 HTML、脚本、图片或任意 SVG 代码。\n"
    "8. 曲线优先用 expr+domain 让服务端采样;确实需要时再手写 points。\n"
    "9. 坐标轴只画线条并标 x/y/z 名称,不要画刻度数字;"
    "图面只标关键对象符号(如 P、∇f、θ),不要把公式和数值堆进图里。\n"
    "10. surface3d 的关键点、梯度向量要落在曲面上并从该点出发;"
    "法向量必须按曲面方程计算:z=f(x,y) 在一点的单位法向为 "
    "(-f_x,-f_y,1)/|(-f_x,-f_y,1)|,不得把点法向量一律画成 (0,0,1);"
    "平面用法向量,球面用该点减球心;法向起点必须落在对应曲面上。"
    "同一位置只放一条 annotation,避免标签重叠;说明文字分散在图形外围的"
    "上/下/左/右不同方位,同一侧不要堆叠,更不要压在曲线或曲面上。\n"
    "11. 几何图必须按真实比例和坐标画:长度、角度、位置要计算,不要随手估;"
    "曲面/曲线用 expr+domain 交给服务端精确采样,标注点要落在真实位置上。\n"
    "12. 文字说明放图形外围,同一区域不要叠放多条;箭头/曲线旁只留短标签"
    "(如 ∂f/∂x),长句放外围 annotation。\n"
    "13. 不要在 title、label、annotation 或任何文字里解释你为什么选这种图、"
    "提到了什么权重/评分/维度判断;只画内容本身,选型是后台动作。\n"
    "14. 先抓这一步最关键的对象或转折,不要平均用力;如果这段只是上一步的"
    "代入/整理/化简,不要单独成图,应合并到上一步。\n"
    "15. 画切线时只画切点附近的一条短切线,一张图最多一条切线,切线不能再次穿过"
    "曲线;不要把导函数曲线和原函数曲线叠在同一坐标系里冒充切线,导函数应另起"
    "一张图或用符号/箭头标注。\n"
    "16. label 必须是有意义的数学符号或短词(如 P、∇f、u、切点);"
    "不要输出 DJJ、ABC 之类占位符,也不要用无意义字母凑标签。\n"
    "17. 系统介绍、功能列表、寒暄、使用说明不画图。\n"
    "18. 3D 图选平缓、可读的函数和适中的定义域,让曲面主体占住画面;"
    "梯度/方向/曲面用明显不同的颜色,关键量就近标文字即可,不要加大底板或色块。\n"
    "19. 概念辨析、条件关系、A/B/C 之间的关系默认用 tree(思维导图);"
    "只有用户明确要类比/实体化/画图且你能给出准确具体的图像时,才改用 2D/3D;"
    "明确步骤/推导/因果链才用 flow;真正的关系网才用 relation。"
    "这些图都不要加装饰性坐标轴;坐标轴只属于几何图、函数图或空间图。\n"
    "20. 条件/推出关系必须用有向边:若 A 能推出 B,边从 A 指向 B,"
    "label 写“A 是 B 的充分条件”;若 A 需要 B,仍按推出方向 A→B,"
    "label 写“B 是 A 的必要条件”。箭头方向表示推出方向,label 表示充分/必要,"
    "不要反向,也不要用无向连线代替。\n"
    "21. 椭圆用 kind=ellipse 并给 rx/ry/rotation(弧度);3D 圆/椭圆用 normal "
    "指定所在平面,不要假设水平;参数曲面用 parametric_surface 的三个分量表达式,"
    "不要把它硬写成 z=f(x,y);参数曲线用 parametric_curve+xexpr/yexpr(+zexpr)/domain;"
    "隐式曲线用 implicit_curve+expr+4 元 domain,3D 交线用 implicit_curve3d+expr+expr2+6 元 domain,隐式曲面用 implicit_surface+expr+6 元 domain;"
    "参数曲面上画标量场梯度时给 fieldexpr,梯度会投到切平面。"
    "切线可用 kind=tangent+curve+x(圆/椭圆再加 y),或直接给 from/to。\n"
)


def _load_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def plan_diagram(question: str, before: str, excerpts: list[dict],
                       kind: str, role: str = "main",
                       strict: bool | None = None,
                       local_hint: bool = False,
                       mode: str = "learn",
                       table_context: str = "") -> dict | None:
    """根据用户问题与当前段落生成一张图解;失败返回 None。

    strict=True:kind 是硬性要求(用户明确说了表示方式)。
    strict=False:kind 只是建议,规划器可按内容自主改选 2D/3D/流程/关系。"""
    requested = explicit_type(question)
    if requested:
        kind = requested
        strict = True
    elif is_relation_question(question) and not wants_analogy(question):
        # 概念辨析默认思维导图;用户明确要类比/画图时留给规划器选具体图。
        # 默认图不再允许拿坐标轴当装饰。
        kind = "flow" if is_step_text(question) else "tree"
        strict = True
    elif strict is None:
        strict = False
    if kind and kind not in _TYPES:
        return None
    if not llm.is_configured(role):
        return None
    if _breaker_open():
        diagram_metrics.record("plan", False, "breaker")
        return None
    started = time.monotonic()
    # 图解只针对标记前的最新一步:取正文尾部,避免把整篇回答塞进一张图。
    latest = re.sub(r"\s+", " ", before or "").strip()[-3500:]
    if not kind:
        # 用户没指定维度时,由后台权重给一个建议;规划器仍可按内容改选。
        # 权重分数只在后台使用,不写进上下文、回答、图题或标注。
        hint_source = latest
        if local_hint:
            parts = [part for part in re.split(r"\n\s*\n", before or "")
                     if part.strip()]
            if parts:
                hint_source = re.sub(r"\s+", " ", parts[-1]).strip()
        hint, hint_score = score_segment(
            hint_source, tuple(_topic_terms(question, before or "")),
            prefer_visual=wants_visual(question))
        if hint and hint_score >= 2.0:
            kind = hint
            # 用户明确要“画图”,且内容有强视觉证据时,不允许规划器退回流程图。
            if (wants_visual(question) and hint in (
                    "plot2d", "geometry2d", "surface3d", "geometry3d")
                    and hint_score >= 3.0):
                strict = True
    context: list[str] = [
        f"请求图解类型:{kind or '自选(按内容决定)'}",
        f"类型要求:{'硬性,必须一致' if strict else '建议,可按内容改选更合适的类型'}",
        f"用户明确要求的表示方式:{requested or '未指定'}",
        f"用户问题:{_text(question, 1000)}",
        f"当前回答(标记前最新段落):{latest}",
        "资料:",
    ]
    if table_context:
        context.insert(0, f"数据表/计算结果(只可引用真实数值):{_text(table_context, 4000)}")
    for item in (excerpts or [])[:6]:
        section = _text(item.get("section"), 120)
        body = _text(item.get("text") or item.get("snippet"), 900)
        if body:
            context.append(f"- {section}:{body}")
    system = _PLAN_SYSTEM_RESEARCH if mode == "research" else _PLAN_SYSTEM
    if not _has_cjk(question):
        # 英文提问:图的标题/标签/注释也必须全英文,否则答案框里会混入中文
        system += (
            "\nLanguage: the user writes in English. Write every title, label and "
            "annotation text in English; keep mathematical notation unchanged. "
            "Do not output Chinese text."
        )
    context_text = "\n".join(context)

    async def _attempt(repair_note: str = "") -> dict | None:
        async with _planner_gate():
            parts: list[str] = []
            async for delta in llm.stream_chat(
                    system + repair_note, context_text, role=role,
                    fallback=True, max_tokens=1800, thinking=False):
                parts.append(delta)
                if sum(len(part) for part in parts) >= 12000:
                    break
            raw = _load_json("".join(parts))
            if isinstance(raw, dict) and kind and not raw.get("type"):
                # 规划器经常省略 type;把请求类型补上再校验。
                raw["type"] = kind
            if isinstance(raw, dict):
                raw = repair_surface_shapes(raw, question)
            # 表达式采样是 CPU 活,放线程里,避免卡住 SSE 事件循环。
            return await asyncio.to_thread(prepare_diagram, raw)

    try:
        diagram = await _attempt()
        # 一次校验失败很常见(模型漏字段/类型写错);重试一次再判失败,
        # 避免用户只点一次「图解此段」就收到失败提示。
        if diagram is None or (strict and kind and diagram.get("type") != kind):
            diagram = await _attempt(
                "\n\n上一次输出未通过图解协议校验。请重新只输出一个合法 JSON 对象:"
                "字段齐全、类型与要求一致、坐标与表达式可被直接计算,不要 Markdown 代码块。"
            )
            diagram_metrics.record(
                "plan_retry", diagram is not None, "ok" if diagram else "invalid")
    except asyncio.CancelledError:
        diagram_metrics.record(
            "plan", False, "cancelled",
            round((time.monotonic() - started) * 1000))
        raise
    except Exception:  # noqa: BLE001 图解失败不能影响回答
        _breaker_failure()
        diagram_metrics.record(
            "plan", False, "exception",
            round((time.monotonic() - started) * 1000))
        return None
    # 硬性要求时类型必须一致;建议类型允许规划器按内容改选。
    if diagram is None or (strict and kind and diagram.get("type") != kind):
        _breaker_failure()
        diagram_metrics.record(
            "plan", False, "invalid",
            round((time.monotonic() - started) * 1000))
        return None
    _breaker_success()
    points, _size = diagram_cost(diagram)
    diagram_metrics.record(
        "plan", True, "ok", round((time.monotonic() - started) * 1000),
        points)
    return diagram


_VERIFY_SYSTEM = (
    "你是图解质检员。判断这张图是否与用户问题、以及这段讲解一致。"
    "只输出一行 JSON:{\"ok\": true 或 false, \"reason\": \"一句话\"}。"
    "图与讲解无关、画错对象、标错坐标、或会误导读者时 ok=false;拿不准也判 false。"
)


def verify_enabled() -> bool:
    """语义一致性检查默认开启;MG_DIAGRAM_VERIFY=0 可关(省一次模型调用)。"""
    return os.getenv("MG_DIAGRAM_VERIFY", "1").strip().lower() not in (
        "0", "false", "off", "no")


def _diagram_summary(diagram: dict) -> str:
    lines = [f"图类型:{diagram.get('type', '')}"]
    if diagram.get("title"):
        lines.append(f"标题:{_text(diagram.get('title'), 120)}")
    labels = [
        _text(item.get("label"), 60)
        for item in (diagram.get("nodes") or []) + (diagram.get("shapes") or [])
        if isinstance(item, dict) and item.get("label")
    ][:8]
    if labels:
        lines.append("标注:" + "、".join(labels))
    edges = []
    for edge in (diagram.get("edges") or [])[:12]:
        if not isinstance(edge, dict):
            continue
        source = _text(edge.get("from"), 60)
        target = _text(edge.get("to"), 60)
        label = _text(edge.get("label"), 40)
        if source and target:
            edges.append(f"{source}->{target}" + (f"({label})" if label else ""))
    if edges:
        lines.append("有向关系:" + "；".join(edges))
    exprs = [
        _text(item.get("expr"), 80)
        for item in diagram.get("shapes") or []
        if isinstance(item, dict) and item.get("expr")
    ][:4]
    if exprs:
        lines.append("表达式:" + "、".join(exprs))
    commands = [
        _text(item, 160)
        for item in diagram.get("commands") or []
        if isinstance(item, str)
    ][:12]
    if commands:
        # GeoGebra 图没有 shapes,只给类型/标题会让质检员误判为空图。
        lines.append("构造命令:" + "；".join(commands))
    notes = [
        _text(item.get("text"), 80)
        for item in diagram.get("annotations") or []
        if isinstance(item, dict) and item.get("text")
    ][:5]
    if notes:
        lines.append("坐标标注:" + "、".join(notes))
    return "\n".join(lines)


async def verify_diagram(question: str, context: str, diagram: dict,
                         role: str = "backup") -> bool | None:
    """异源模型判断图是否对题。True=一致,False=不一致,None=无法判断。
    只做语义一致性,不重画、不改图;调用失败由调用方决定是否放行。"""
    if not llm.is_configured(role):
        role = llm.pick("main")
        if not llm.is_configured(role):
            return None
    prompt = (
        f"用户问题:{_text(question, 800)}\n\n"
        f"当前讲解段落:{_text(context, 800)}\n\n"
        f"待检图:\n{_diagram_summary(diagram)}"
    )
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(
                _VERIFY_SYSTEM, prompt, role=role, fallback=False,
                max_tokens=120, thinking=False):
            parts.append(delta)
            if sum(len(part) for part in parts) >= 400:
                break
    except Exception:  # noqa: BLE001 校验失败不伪造结论
        return None
    raw = "".join(parts)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    ok = data.get("ok")
    return ok if isinstance(ok, bool) else None


_GEO_PLAN_SYSTEM = """你是 GeoGebra 绘图规划器。只输出一个 JSON 对象，不要 Markdown、不要解释：
{"type":"geogebra2d"或"geogebra3d","title":"中文标题","commands":["命令1","命令2"]}
规则：
1. 2D 用 geogebra2d，3D/曲面/空间用 geogebra3d；一条命令一行，最多 12 条。
2. 只用这些命令：
   2D：Point, Segment, Line, Vector, Circle, Ellipse, Polygon, Curve, Tangent, Intersect, Derivative, Integral, Root, Extremum, Solve
   3D：Point, Segment, Vector, Line, Polygon, Plane, Sphere, Cube, Cylinder, Cone, Prism, Pyramid, Surface, Curve, Intersect
3. 函数定义与点赋值可直接写：f(x)=x^2、A=(1,2)、P=(0,0,0)。
4. 曲面必须用参数式：Surface(u,v,f(u,v),u,-2,2,v,-2,2)。
5. 不要写样式命令（SetColor/SetVisible 等），不要写 Execute/JavaScript/Text/Image/URL。
6. 坐标与范围要贴合问题，不要给离谱的大范围。
示例 2D：{"type":"geogebra2d","title":"y=x^2 在 (1,1) 的切线","commands":["f(x)=x^2","A=(1,1)","t=Tangent(A,f)"]}
示例 3D：{"type":"geogebra3d","title":"旋转抛物面","commands":["f(x,y)=x^2+y^2","s=Surface(u,v,f(u,v),u,-2,2,v,-2,2)"]}
"""


def geogebra_enabled() -> bool:
    return os.getenv("MG_DIAGRAM_ENGINE", "legacy").strip().lower() in (
        "geogebra", "auto")


async def plan_geogebra(question: str, before: str, role: str = "main") -> dict | None:
    """让模型输出 GeoGebra 命令；校验不过返回 None，由调用方回退旧规划器。"""
    if not llm.is_configured(role):
        return None
    kind = "geogebra3d" if (
        _3D_RE.search(question or "") or _3D_SURFACE_RE.search(question or "")
    ) else "geogebra2d"
    if kind == "geogebra3d" and _GEO3D_SURFACE_DEFER_RE.search(question or ""):
        # 参数曲面/梯度仍走旧表达式采样 + Three.js;3D 内核只接可精确构造对象。
        diagram_metrics.record("plan_geo", False, "3d_surface_deferred")
        return None
    latest = re.sub(r"\s+", " ", before or "").strip()[-1200:]
    context = f"""类型:{kind}
用户问题:{_text(question, 800)}
当前讲解:{_text(latest, 1200)}"""
    parts: list[str] = []
    system = _GEO_PLAN_SYSTEM
    if not _has_cjk(question):
        system += ("\nLanguage: write the title in English; do not output Chinese text.")
    try:
        async for delta in llm.stream_chat(
                system, context, role=role, fallback=True,
                max_tokens=700, thinking=False):
            parts.append(delta)
            if sum(len(part) for part in parts) >= 4000:
                break
    except Exception:  # noqa: BLE001 生成失败交给旧规划器
        diagram_metrics.record("plan_geo", False, "exception")
        return None
    raw = _load_json("".join(parts))
    if isinstance(raw, dict) and not raw.get("type"):
        raw["type"] = kind
    diagram = validate_geogebra(raw)
    if (diagram is not None
            and any((_geo_command_name(command) or "") == "surface"
                    for command in diagram.get("commands") or [])):
        # 3D XML 对 Surface 不直接给网格;这类问题交回旧采样器。
        diagram_metrics.record("plan_geo", False, "3d_surface_deferred")
        return None
    diagram_metrics.record("plan_geo", diagram is not None,
                           "ok" if diagram else "invalid")
    return diagram


async def plan_diagram_auto(question: str, before: str, excerpts: list[dict],
                            kind: str, role: str = "main",
                            mode: str = "learn",
                            table_context: str = "", **kwargs) -> dict | None:
    """按内容领域与 MG_DIAGRAM_ENGINE 选择引擎;失败自动回退旧规划器。"""
    if (linear_algebra.looks_linear(question)
            and (wants_visual(question) or not is_relation_question(question))):
        diagram = await linear_algebra.plan_linear(question, before, role=role)
        if diagram is not None:
            diagram_metrics.record("plan_linear", True, "ok")
            return diagram
        diagram_metrics.record("plan_linear", False, "fallback")
        # 高等代数语义题一旦语义计划失败,不能退回自由作图:
        # 模型很容易把 λ 标签、旋转方向、平行关系画反,错图比没图更糟。
        # 只有 R^2/R^3 这类维度词、没有代数语义的题仍允许回退旧管线。
        if linear_algebra.looks_linear_core(question):
            return None
    if (geogebra_enabled()
            and kind not in ("tree", "relation", "flow")
            and not is_relation_question(question)):
        diagram = await plan_geogebra(question, before, role=role)
        if diagram is not None:
            return diagram
        diagram_metrics.record("plan", False, "geo_fallback")
    return await plan_diagram(
        question, before, excerpts, kind, role=role,
        mode=mode, table_context=table_context, **kwargs)


_diagram_limiter = SlidingWindowLimiter(12, 60.0)
_get_table = research_tables._get_table
_run_analysis = analysis_client.run_analysis


async def metrics_endpoint(request: Request):
    """图解运行指标:只返回聚合计数/耗时,不含问题、回答或用户身份。"""
    require_auth(request)
    if request.query_params.get("format") == "prometheus":
        return PlainTextResponse(
            diagram_metrics.prometheus(),
            headers={"Cache-Control": "no-store"})
    return JSONResponse(
        diagram_metrics.snapshot(), headers={"Cache-Control": "no-store"})


async def plan_endpoint(request: Request) -> JSONResponse:
    """手动“图解此段”:只依据当前回答/当前论文,不触发外部检索。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not _diagram_limiter.allow(uid):
        raise HTTPException(429, "操作过于频繁,请稍后再试")
    body = await read_json_object(request)
    question = _text(body.get("question"), 4000)
    answer = _text(body.get("answer"), 12000)
    if not question:
        raise HTTPException(400, "缺少 question")
    kind = _text(body.get("kind"), 40)
    requested = explicit_type(question)
    if requested:
        kind = requested
    elif kind not in _TYPES:
        # 手动图解没有指定类型时,让规划器按内容选,不默认画关系网。
        kind = ""
    excerpts: list[dict] = []
    paper_id = _text(body.get("paperId"), 64)
    if paper_id:
        try:
            doc = await asyncio.to_thread(rc.get_live_doc, uid, paper_id)
            if doc:
                ctx = await asyncio.to_thread(
                    rc.paper_context, uid, paper_id, question, 4, 6000)
                excerpts = (ctx or {}).get("chunks") or []
        except Exception:  # noqa: BLE001 论文不可用时只依据回答
            excerpts = []
    table_id = _text(body.get("tableId"), 64)
    table_context = ""
    table_row: dict | None = None
    if table_id:
        try:
            table = await asyncio.to_thread(_get_table, uid, table_id)
            if table:
                table_row = table
                table_context = research_tables.context_text(table)
        except Exception:  # noqa: BLE001 表格不可用时只依据回答
            table_context = ""
    mode = "research" if table_id or body.get("mode") == "research" else "learn"
    regression = body.get("regression")
    if regression is not None:
        if not isinstance(regression, dict) or not table_id:
            raise HTTPException(400, "bad_spec")
        if table_row is None:
            raise HTTPException(404, "not found")
        try:
            spec = research_tables._validate_regression_spec(
                table_row.get("columns") or [],
                {key: value for key, value in regression.items()
                 if key != "tableUpdatedAt"})
            fit_result = await _run_analysis({
                "columns": table_row.get("columns") or [],
                "rows": research_tables._resolved_analysis_rows(
                    table_row.get("columns") or [],
                    table_row.get("rows") or [],
                    table_row.get("formulas") or {}),
                "formulas": {},
                "spec": spec,
            })
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except analysis_client.AnalysisError as exc:
            status = 400 if exc.code in {"empty", "insufficient_n", "singular", "bad_column", "unsupported"} else 503
            raise HTTPException(status, exc.code) from exc
        x_label = spec["x"][0] if len(spec["x"]) == 1 else "观测序号"
        diagram = build_data_plot(table_id, x_label, spec["y"], fit_result)
        if diagram is None:
            raise HTTPException(422, "invalid_plot")
        return JSONResponse({"diagram": diagram}, headers={"Cache-Control": "no-store"})
    if table_context or mode == "research":
        diagram = await plan_diagram(
            question, answer, excerpts, kind,
            mode=mode, table_context=table_context)
        if table_id and diagram is not None:
            shapes = diagram.get("shapes") if isinstance(diagram.get("shapes"), list) else []
            if any(shape.get("kind") in {"point", "curve"} for shape in shapes
                   if isinstance(shape, dict)):
                # 科研区数据图必须来自服务端回归结果,不接受模型手写点/曲线。
                diagram = None
    else:
        diagram = await plan_diagram(question, answer, excerpts, kind)
    return JSONResponse({"diagram": diagram}, headers={"Cache-Control": "no-store"})

