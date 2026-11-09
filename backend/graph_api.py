"""知识图谱数据接口:节点、依赖边、布局坐标与当前账号的掌握度标记。

前端负责渲染与交互,NetworkX 在后端计算分层坐标:
- status:mastered(≥3 分)/ weak(<3 分)/ new(未诊断)
- edges 方向:source(前置)→ target(后继)
- x / y / level:最长路径分层 + 重心法排序后的像素坐标
"""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import auth
import diagnosis
import ebbinghaus
from graph_layout import layout_points
from recommendation import MASTERED_SCORE


def _status(score: int | None) -> str:
    if score is None:
        return "new"
    return "mastered" if score >= MASTERED_SCORE else "weak"


async def graph_data(request: Request) -> JSONResponse:
    """GET /api/graph:全量知识点、依赖边、章节顺序、坐标与个人掌握度。"""
    rec = auth.require_auth(request)
    uid = str(rec.get("uid") or "")
    graph = diagnosis.get_graph()
    latest = diagnosis.latest(uid)
    layout = layout_points(graph)

    nodes: list[dict] = []
    edges: list[dict] = []
    chapters: list[str] = []
    for point in graph.points.values():
        if point.chapter not in chapters:
            chapters.append(point.chapter)
        entry = latest.get(point.id, {})
        score = entry.get("score")
        due, retention, _age = ebbinghaus.review_due(entry.get("at"), score)
        position = layout.get(point.id, {"x": 0, "y": 0, "level": 0})
        nodes.append({
            "id": point.id,
            "name": point.name,
            "chapter": point.chapter,
            "difficulty": point.difficulty,
            "descendantCount": graph.descendant_count(point.id),
            "prerequisites": list(point.prerequisites),
            "summary": point.summary,
            "keyPoints": list(point.key_points),
            "mastery": score,
            "retention": retention,
            "reviewDue": due,
            "status": _status(score),
            "x": position["x"],
            "y": position["y"],
            "level": position["level"],
        })
        for prereq in point.prerequisites:
            edges.append({"source": prereq, "target": point.id})

    return JSONResponse({"nodes": nodes, "edges": edges, "chapters": chapters})


_STATUS_COLOR = {
    "mastered": "#4dd6ff",
    "weak": "#ff6b6b",
    "new": "#718299",
}


async def graph_export(request: Request) -> Response:
    """GET /api/graph/export:导出可独立打开的 Pyvis HTML 图谱。

    只读当前账号掌握度着色;vis 资源内联,不依赖 CDN,便于分享与打印。
    """
    rec = auth.require_auth(request)
    uid = str(rec.get("uid") or "")
    graph = diagnosis.get_graph()
    latest = diagnosis.latest(uid)
    layout = layout_points(graph)

    # 延迟导入:未安装 pyvis 时不影响主服务启动,只有导出接口不可用
    try:
        from pyvis.network import Network
    except ImportError:  # pragma: no cover - 依赖缺失属于部署问题
        raise HTTPException(503, "graph export unavailable") from None

    net = Network(height="900px", width="100%", directed=True, notebook=False,
                  bgcolor="#05060a", font_color="#e8f2ff", cdn_resources="in_line")
    for point in graph.points.values():
        score = latest.get(point.id, {}).get("score")
        status = _status(score)
        position = layout.get(point.id, {"x": 0, "y": 0, "level": 0})
        net.add_node(
            point.id,
            label=point.name,
            title=f"{point.name}\n{point.chapter} · 难度 {point.difficulty}/5",
            x=position["x"],
            y=position["y"],
            physics=False,
            color=_STATUS_COLOR[status],
        )
        for prereq in point.prerequisites:
            net.add_edge(prereq, point.id, arrows="to")
    net.toggle_physics(False)
    html = net.generate_html(notebook=False)
    return Response(
        html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="mathguide-graph.html"'},
    )
