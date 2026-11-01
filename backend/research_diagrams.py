"""图解标记流与结构化 schema:服务端只负责剥标记、校验、发事件。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from rag import llm

PREFIX = "[[MG_DIAGRAM:"
_MARKER_RE = re.compile(r"\[\[MG_DIAGRAM:([a-z0-9_]+)\]\]")
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


def _shape(raw: object) -> dict | None:
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("kind"), 40)
    if kind not in _SHAPES:
        return None
    out: dict = {"kind": kind}
    for key in ("x", "y", "z", "r", "radius", "width", "height"):
        if key in raw:
            parsed = _num(raw[key])
            if parsed is None:
                return None
            out[key] = parsed
    for key in ("label", "expr", "color"):
        if key in raw:
            value = _text(raw[key], 200)
            if value:
                out[key] = value
    if "domain" in raw:
        domain = raw["domain"]
        if not isinstance(domain, (list, tuple)) or len(domain) != 2:
            return None
        parsed = [_num(item) for item in domain]
        if any(item is None for item in parsed):
            return None
        out["domain"] = parsed
    if "points" in raw:
        points = raw["points"]
        if not isinstance(points, list) or len(points) > 200:
            return None
        out["points"] = []
        for item in points:
            point = _point(item)
            if point is None:
                return None
            out["points"].append(point)
    for key in ("from", "to"):
        if key in raw:
            point = _point(raw[key])
            if point is None:
                return None
            out[key] = point
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
            if shape is None:
                return None
            shapes.append(shape)

    annotations: list[dict] = []
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
            annotations.append({"x": x, "y": y, "text": text})

    if not nodes and not shapes and not annotations:
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

    def feed(self, text: str) -> str:
        self._buffer += text or ""
        out: list[str] = []
        while True:
            start = self._buffer.find(PREFIX)
            if start < 0:
                hold = self._partial_prefix()
                if hold:
                    if len(self._buffer) > hold:
                        out.append(self._buffer[:-hold])
                    self._buffer = self._buffer[-hold:]
                else:
                    out.append(self._buffer)
                    self._buffer = ""
                break
            if start:
                out.append(self._buffer[:start])
            end = self._buffer.find("]]", start)
            if end < 0:
                self._buffer = self._buffer[start:]
                break
            raw = self._buffer[start:end + 2]
            self._buffer = self._buffer[end + 2:]
            match = _MARKER_RE.fullmatch(raw)
            if not match:
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
        clean = "".join(out)
        self._visible_len += len(clean)
        return clean

    def drain(self) -> list[DiagramMarker]:
        out = self._markers
        self._markers = []
        return out

    def finish(self) -> str:
        self._buffer = ""
        return ""


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
    "你是 MathGuide 的图解规划器。用户刚在对话中提出了理解困惑,"
    "你只负责把当前回答中的一个关键关系画成静态图解。\n"
    "只输出一个 JSON 对象,不要解释,不要 Markdown 代码块。\n"
    "格式:\n"
    '{"type":"relation","title":"可选",'
    '"nodes":[{"id":"a","label":"概念"}],'
    '"edges":[{"from":"a","to":"b","label":"推出"}],'
    '"shapes":[],"annotations":[]}\n'
    "规则:\n"
    "1. 只使用【用户问题】【当前回答】【资料】里出现的内容,不得虚构关系或数据。\n"
    "2. 只画一张图,节点不超过 40,边不超过 80,形状不超过 100。\n"
    "3. type 只能是 tree/relation/flow/geometry2d/plot2d/geometry3d/surface3d。\n"
    "4. 优先表达概念之间的内在联系、因果、步骤或几何直观。\n"
    "5. 不要输出 HTML、脚本、图片或任意 SVG 代码。\n"
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
                       kind: str, role: str = "main") -> dict | None:
    """根据用户问题与标记前的回答生成一张图解;失败返回 None。"""
    if kind not in _TYPES or not llm.is_configured(role):
        return None
    context: list[str] = [
        f"用户问题:{_text(question, 1000)}",
        f"当前回答(标记前):{_text(before, 6000)}",
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
                fallback=True, max_tokens=1200, thinking=False):
            parts.append(delta)
            if sum(len(part) for part in parts) >= 8000:
                break
    except Exception:  # noqa: BLE001 图解失败不能影响回答
        return None
    return validate_diagram(_load_json("".join(parts)))

