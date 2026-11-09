"""动态学习路径推荐。

候选集规则(拓扑排序思想):
- 前置知识点全部达到 MASTERED_SCORE 才进入候选;
- 未诊断过的知识点 → 新学(new);
- 已诊断但未达标 → 复习(review);
- 已达标且记忆保持率足够 → 不进候选;
- 已达标但按艾宾浩斯曲线进入待复核 → 复习(review),并优先展示。

排序策略:
- 有待复核项时:待复核按 retention 升序优先,其次薄弱复习,最后新学;
- 无 retention 数据时保持旧行为:difficulty 难度升序,coreness 核心度降序。
同分按拓扑序稳定排序,保证同一份掌握度每次推荐结果一致。
"""
from __future__ import annotations

from datetime import datetime

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import diagnosis
import ebbinghaus
from knowledge_graph import KnowledgeGraph

MASTERED_SCORE = 3
STRATEGIES = ("difficulty", "coreness")
MAX_LIMIT = 20


def recommend(graph: KnowledgeGraph, mastery: dict[str, int],
              strategy: str = "difficulty", limit: int = 5,
              latest: dict[str, dict] | None = None,
              now: datetime | None = None) -> dict:
    """按掌握度与记忆保持率返回下一批学习内容。

    mastery: {知识点 id: 1~5 分};latest: 诊断记录(含 at),用于艾宾浩斯待复核。
    """
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
        entry = (latest or {}).get(point_id) or {}
        due, retention, age = ebbinghaus.review_due(
            entry.get("at"), score if isinstance(score, int) else None, now)
        if isinstance(score, int) and score >= MASTERED_SCORE:
            mastered += 1
            if not due:
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
            "retention": retention,
            "reviewDue": due,
            "ageDays": age,
            "prerequisites": list(point.prerequisites),
        })

    if latest is None:
        # 旧调用方:没有时间数据,保持原有排序
        if strategy == "difficulty":
            items.sort(key=lambda item: (
                item["difficulty"], -item["descendantCount"], order[item["pointId"]]))
        else:
            items.sort(key=lambda item: (
                -item["descendantCount"], item["difficulty"], order[item["pointId"]]))
    else:
        def sort_key(item: dict) -> tuple:
            if item["reviewDue"]:
                lane, urgent = 0, item["retention"] or 0.0
            elif item["reason"] == "review":
                lane, urgent = 1, 0.0
            else:
                lane, urgent = 2, 0.0
            if strategy == "difficulty":
                return (lane, urgent, item["difficulty"],
                        -item["descendantCount"], order[item["pointId"]])
            return (lane, urgent, -item["descendantCount"],
                    item["difficulty"], order[item["pointId"]])

        items.sort(key=sort_key)

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

    latest = diagnosis.latest(uid)
    mastery = {
        point_id: int(entry["score"])
        for point_id, entry in latest.items()
    }
    return JSONResponse(recommend(
        diagnosis.get_graph(), mastery, strategy, limit, latest=latest))
