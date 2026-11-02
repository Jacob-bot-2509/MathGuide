"""图解标记流与结构化 schema:服务端只负责剥标记、校验、发事件。"""
from __future__ import annotations

import ast
import asyncio
import json
import math
import re
from dataclasses import dataclass

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import research_corpus as rc
from auth import require_auth
from http_utils import read_json_object
from rag import llm
from rate_limit import SlidingWindowLimiter
import diagram_taxonomy as taxonomy

PREFIX = "[[MG_DIAGRAM:"
_MARKER_RE = re.compile(r"\[\[MG_DIAGRAM:(?:type=)?([a-z0-9_]+)\]\]")
MAX_DIAGRAMS = 6
_MAX_SURFACE_GRID = 41
_CURVE_SAMPLES = 80
_TYPES = {"tree", "relation", "flow", "geometry2d", "plot2d",
          "geometry3d", "surface3d"}
_SHAPES = {"point", "segment", "line", "vector", "circle", "polygon",
           "curve", "axis", "plane", "sphere", "box", "cone", "cylinder",
           "surface"}
_MAX_NODES = 40
_MAX_EDGES = 80
_MAX_SHAPES = 100
_MAX_ANNOTATIONS = 40
_MAX_COORD = 1e4

# 用户明确说出的表示方式优先于模型自选类型:要三维就画三维,不要改画思维导图。
_3D_SURFACE_RE = re.compile(
    r"曲面|梯度|切平面|等高线|z\s*=\s*f\s*\(|surface|gradient", re.IGNORECASE)
_3D_RE = re.compile(
    r"三维|3d|3-d|立体|空间向量|空间曲面|three[- ]?dimensional", re.IGNORECASE)
_2D_GEOMETRY_RE = re.compile(
    r"二维几何|平面几何|平面图形|二维图", re.IGNORECASE)
_PLOT_RE = re.compile(
    r"函数图像|函数曲线|曲线图|plot|graph of", re.IGNORECASE)
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


def score_segment(text: str, topic_terms: tuple[str, ...] = ()) -> tuple[str, float]:
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


def slice_utf16(text: str, units: int) -> str:
    """按前端 UTF-16 锚点截取文本。"""
    if units <= 0:
        return ""
    return (text or "").encode("utf-16-le")[:units * 2].decode(
        "utf-16-le", errors="ignore")


def select_segments(
    question: str,
    text: str,
    existing_anchors: tuple[int, ...] | list[int] = (),
    limit: int = 6,
) -> list[DiagramSegment]:
    """扫描整篇回答:有步骤按步骤选,没步骤按权重选高分段落。
    只返回值得画图的段落;模型没标记时由这里兜底决定画不画、画哪种。"""
    if not text or limit <= 0:
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
        kind, score = score_segment(body, topic_terms)
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





def _text(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _num(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
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
    "atan2": math.atan2, "sinh": math.sinh, "cosh": math.cosh,
    "tanh": math.tanh, "exp": math.exp, "log": math.log,
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
            if abs(right) > 8:
                raise ValueError("pow")
            return left ** right
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


def _compile_expr(expr: object, allow_y: bool = True):
    if not isinstance(expr, str):
        return None
    source = expr.replace("π", "pi").replace("^", "**").strip()
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
    except (TypeError, ValueError):
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


def _sample_shape(shape: dict) -> bool:
    """服务端按表达式采样曲面/曲线,避免模型手写大量坐标出错。
    返回 False 表示这个形状没有可画数据,应丢弃。"""
    kind = shape.get("kind")
    if kind not in ("surface", "curve"):
        return True
    points = shape.get("points")
    if isinstance(points, (int, float)):
        # 模型常把 "points" 写成采样数;把它当 samples,不要因此丢图。
        shape["samples"] = int(points)
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
    samples = _int(shape.get("samples"), _CURVE_SAMPLES, 8, 200)
    sampled2d: list[list[float]] = []
    try:
        for i in range(samples):
            x = x0 + (x1 - x0) * i / (samples - 1)
            sampled2d.append([round(x, 6), round(run(x), 6)])
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return False
    shape["points"] = sampled2d
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
        nearest["z"] = round(z0, 6)
    if vector is None:
        return
    domain = _domain(surface)
    span = min(domain[1] - domain[0], domain[3] - domain[2]) if domain else 2.0
    magnitude = math.hypot(gx, gy)
    if magnitude < 1e-9:
        return
    step = max(0.05, min(0.6, span * 0.35)) / magnitude
    dx, dy = gx * step, gy * step
    vector["from"] = [round(x0, 6), round(y0, 6), round(z0, 6)]
    vector["to"] = [
        round(x0 + dx, 6), round(y0 + dy, 6),
        round(z0 + gx * dx + gy * dy, 6),
    ]
    plane = next((
        shape for shape in shapes
        if shape.get("kind") == "plane"
        and re.search(r"切平面|tangent", str(shape.get("label") or ""), re.IGNORECASE)
    ), None)
    if plane is not None:
        plane["normal"] = [round(-gx, 6), round(-gy, 6), 1.0]


def prepare_diagram(raw: object) -> dict | None:
    """采样表达式形状后再做白名单校验。"""
    if not isinstance(raw, dict):
        return None
    shapes = raw.get("shapes")
    if isinstance(shapes, list) and len(shapes) <= _MAX_SHAPES:
        kept: list[object] = []
        for shape in shapes:
            if isinstance(shape, dict) and not _sample_shape(shape):
                continue
            kept.append(shape)
        raw = {**raw, "shapes": kept}
        _refine_gradient([shape for shape in kept if isinstance(shape, dict)])
    return validate_diagram(raw)



def _shape(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("kind"), 40)
    if kind not in _SHAPES:
        return None
    out: dict = {"kind": kind}
    for key in ("x", "y", "z", "r", "radius", "width", "height", "depth"):
        if key in raw:
            parsed = _num(raw[key])
            if parsed is not None:
                out[key] = parsed
    for key in ("rows", "cols"):
        if key in raw:
            parsed = _num(raw[key])
            if parsed is not None and parsed.is_integer():
                out[key] = max(2, min(_MAX_SURFACE_GRID, int(parsed)))
    for key in ("label", "expr", "color"):
        if key in raw:
            value = _text(raw[key], 200)
            if value:
                out[key] = value
    if "domain" in raw:
        domain = raw["domain"]
        if isinstance(domain, (list, tuple)) and len(domain) in (2, 4):
            parsed = [_num(item) for item in domain]
            if all(item is not None for item in parsed):
                out["domain"] = parsed
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


def validate_diagram(raw: object) -> dict | None:
    if not isinstance(raw, dict):
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
            if shape is not None:
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
    elif not shapes:
        return None
    result: dict = {
        "type": kind, "nodes": nodes, "edges": edges,
        "shapes": shapes, "annotations": annotations,
    }
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
        """未闭合标记只剥掉前缀和类型名,后面的正文必须还给用户。"""
        tail = text[len(PREFIX):] if text.startswith(PREFIX) else text
        return re.sub(r"^[a-z0-9_]*", "", tail)

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
    return "data: " + json.dumps({
        "mg_event": "diagram",
        "requestId": request_id,
        "anchorId": anchor_id,
        "anchorIndex": anchor_index,
        "diagram": diagram,
    }, ensure_ascii=False) + "\n\n"


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
    '- geometry2d/plot2d:{"shapes":[{"kind":"point|segment|vector|circle|'
    'polygon|curve|axis","x":0,"y":0,"from":[0,0],"to":[1,1],'
    '"points":[[x,y]],"label":"A"}],"annotations":[{"x":0,"y":0,"text":"说明"}]}\n'
    '- geometry3d:{"shapes":[{"kind":"point|segment|vector|plane|sphere|box|'
    'cone|cylinder","x":0,"y":0,"z":0,"from":[0,0,0],"to":[1,1,1],'
    '"normal":[0,0,1],"label":"A"}],"annotations":[{"x":0,"y":0,"z":0,'
    '"text":"说明"}]}\n'
    '- surface3d:用 {"kind":"surface","expr":"x^2+y^2","domain":[-3,3],'
    '"rows":25,"cols":25} 表示曲面,服务端会按行优先采样;'
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
    "硬上限:节点 40、边 80、形状 100、曲面网格 41×41。\n"
    "6. 坐标用可读的数学坐标;给出 title,关键对象给 label。\n"
    "7. 不要输出 HTML、脚本、图片或任意 SVG 代码。\n"
    "8. 曲线优先用 expr+domain 让服务端采样;确实需要时再手写 points。\n"
    "9. 坐标轴只画线条并标 x/y/z 名称,不要画刻度数字;"
    "图面只标关键对象符号(如 P、∇f、θ),不要把公式和数值堆进图里。\n"
    "10. surface3d 的关键点、梯度向量要落在曲面上并从该点出发;"
    "同一位置只放一条 annotation,避免标签重叠。\n"
    "11. 几何图必须按真实比例和坐标画:长度、角度、位置要计算,不要随手估;"
    "曲面/曲线用 expr+domain 交给服务端精确采样,标注点要落在真实位置上。\n"
    "12. 文字说明放图形外围,同一区域不要叠放多条;箭头/曲线旁只留短标签"
    "(如 ∂f/∂x),长句放外围 annotation。\n"
    "13. 不要在 title、label、annotation 或任何文字里解释你为什么选这种图、"
    "提到了什么权重/评分/维度判断;只画内容本身,选型是后台动作。\n"
    "14. 先抓这一步最关键的对象或转折,不要平均用力;如果这段只是上一步的"
    "代入/整理/化简,不要单独成图,应合并到上一步。\n"
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
                       local_hint: bool = False) -> dict | None:
    """根据用户问题与当前段落生成一张图解;失败返回 None。

    strict=True:kind 是硬性要求(用户明确说了表示方式)。
    strict=False:kind 只是建议,规划器可按内容自主改选 2D/3D/流程/关系。"""
    requested = explicit_type(question)
    if requested:
        kind = requested
        strict = True
    elif strict is None:
        strict = False
    if kind and kind not in _TYPES:
        return None
    if not llm.is_configured(role):
        return None
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
            hint_source, tuple(_topic_terms(question, before or "")))
        if hint and hint_score >= 2.0:
            kind = hint
    context: list[str] = [
        f"请求图解类型:{kind or '自选(按内容决定)'}",
        f"类型要求:{'硬性,必须一致' if strict else '建议,可按内容改选更合适的类型'}",
        f"用户明确要求的表示方式:{requested or '未指定'}",
        f"用户问题:{_text(question, 1000)}",
        f"当前回答(标记前最新段落):{latest}",
        "资料:",
    ]
    for item in (excerpts or [])[:6]:
        section = _text(item.get("section"), 120)
        body = _text(item.get("text") or item.get("snippet"), 900)
        if body:
            context.append(f"- {section}:{body}")
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(
                _PLAN_SYSTEM, "\n".join(context), role=role,
                fallback=True, max_tokens=1800, thinking=False):
            parts.append(delta)
            if sum(len(part) for part in parts) >= 12000:
                break
    except Exception:  # noqa: BLE001 图解失败不能影响回答
        return None
    raw = _load_json("".join(parts))
    if isinstance(raw, dict) and kind and not raw.get("type"):
        # 规划器经常省略 type;把请求类型补上再校验。
        raw["type"] = kind
    diagram = prepare_diagram(raw)
    # 硬性要求时类型必须一致;建议类型允许规划器按内容改选。
    if diagram is not None and strict and kind and diagram.get("type") != kind:
        return None
    return diagram


_diagram_limiter = SlidingWindowLimiter(12, 60.0)


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
    diagram = await plan_diagram(question, answer, excerpts, kind)
    return JSONResponse({"diagram": diagram}, headers={"Cache-Control": "no-store"})

