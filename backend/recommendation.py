"""动态学习路径推荐。

候选集规则(拓扑排序思想):
- 前置知识点全部达到 MASTERED_SCORE 才进入候选;
- 未诊断过的知识点 → 新学(new);
- 已诊断但未达标 → 复习(review);
- 已达标 → 不进候选。

排序策略:
- difficulty:难度升序,再按核心度降序;
- coreness:核心度(传递后继数)降序,再按难度升序。
同分按拓扑序稳定排序,保证同一份掌握度每次推荐结果一致。
"""
from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import diagnosis
from knowledge_graph import KnowledgeGraph

MASTERED_SCORE = 3
STRATEGIES = ("difficulty", "coreness")
MAX_LIMIT = 20


def recommend(graph: KnowledgeGraph, mastery: dict[str, int],
              strategy: str = "difficulty", limit: int = 5) -> dict:
    """按掌握度返回下一批学习内容。mastery 为 {知识点 id: 1~5 分}。"""
    if strategy not in STRATEGIES:
        raise ValueError(f"未知推荐策略: {strategy}")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit 必须是整数") from None
    limit = max(1, min(MAX_LIMIT, limit))

    order = {
        point_id: index
        for index, point_id in enumerate(graph.topological_order())
    }
    items: list[dict] = []
    mastered = 0
    for point_id, point in graph.points.items():
        score = mastery.get(point_id)
        if isinstance(score, int) and score >= MASTERED_SCORE:
            mastered += 1
            continue
        if any(mastery.get(prereq, 0) < MASTERED_SCORE
               for prereq in point.prerequisites):
            continue
        items.append({
            "pointId": point_id,
            "name": point.name,
            "chapter": point.chapter,
            "difficulty": point.difficulty,
            "descendantCount": graph.descendant_count(point_id),
            "reason": "review" if score is not None else "new",
            "mastery": score,
            "prerequisites": list(point.prerequisites),
        })

    if strategy == "difficulty":
        items.sort(key=lambda item: (
            item["difficulty"], -item["descendantCount"], order[item["pointId"]]))
    else:
        items.sort(key=lambda item: (
            -item["descendantCount"], item["difficulty"], order[item["pointId"]]))

    return {
        "strategy": strategy,
        "mastered": mastered,
        "items": items[:limit],
    }


async def recommend_points(request: Request) -> JSONResponse:
    """GET /api/recommendation?strategy=difficulty|coreness&limit=5"""
    rec = auth.require_auth(request)
    uid = str(rec.get("uid") or "")
    strategy = request.query_params.get("strategy", "difficulty")
    if strategy not in STRATEGIES:
        raise HTTPException(400, "invalid strategy")
    raw_limit = request.query_params.get("limit", "5")
    try:
        limit = int(raw_limit)
    except ValueError:
        raise HTTPException(400, "invalid limit") from None

    mastery = {
        point_id: int(entry["score"])
        for point_id, entry in diagnosis.latest(uid).items()
    }
    return JSONResponse(recommend(diagnosis.get_graph(), mastery, strategy, limit))
