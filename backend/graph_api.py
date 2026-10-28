"""知识图谱数据接口:节点、依赖边与当前账号的掌握度标记。

前端按拓扑层级自绘有向图,后端只负责组织数据:
- status:mastered(≥3 分)/ weak(<3 分)/ new(未诊断)
- edges 方向:source(前置)→ target(后继)
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import diagnosis
from recommendation import MASTERED_SCORE


def _status(score: int | None) -> str:
    if score is None:
        return "new"
    return "mastered" if score >= MASTERED_SCORE else "weak"


async def graph_data(request: Request) -> JSONResponse:
    """GET /api/graph:全量知识点、依赖边、章节顺序与个人掌握度。"""
    rec = auth.require_auth(request)
    uid = str(rec.get("uid") or "")
    graph = diagnosis.get_graph()
    latest = diagnosis.latest(uid)

    nodes: list[dict] = []
    edges: list[dict] = []
    chapters: list[str] = []
    for point in graph.points.values():
        if point.chapter not in chapters:
            chapters.append(point.chapter)
        score = latest.get(point.id, {}).get("score")
        nodes.append({
            "id": point.id,
            "name": point.name,
            "chapter": point.chapter,
            "difficulty": point.difficulty,
            "descendantCount": graph.descendant_count(point.id),
            "prerequisites": list(point.prerequisites),
            "mastery": score,
            "status": _status(score),
        })
        for prereq in point.prerequisites:
            edges.append({"source": prereq, "target": point.id})

    return JSONResponse({"nodes": nodes, "edges": edges, "chapters": chapters})
