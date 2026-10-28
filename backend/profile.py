"""学习画像:基于诊断记录聚合掌握情况。

只使用 diagnosis 已落库的数据(掌握度与变化),不额外采集聊天正文;
提问历史仍在浏览器本地,随账号导出由前端合并。
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import diagnosis
from recommendation import MASTERED_SCORE

RECENT_LIMIT = 10
WEAK_LIMIT = 5


def summarize(uid: str, graph=None) -> dict:
    graph = graph or diagnosis.get_graph()
    entries = diagnosis.for_user(uid)
    latest = diagnosis.latest(uid)

    scores = [
        entry["score"] for entry in latest.values()
        if isinstance(entry.get("score"), int)
    ]
    mastered = sum(1 for score in scores if score >= MASTERED_SCORE)
    weak = sum(1 for score in scores if score < MASTERED_SCORE)
    average = round(sum(scores) / len(scores), 1) if scores else None

    chapter_scores: dict[str, list[int]] = {}
    for point in graph.points.values():
        entry = latest.get(point.id)
        if entry and isinstance(entry.get("score"), int):
            chapter_scores.setdefault(point.chapter, []).append(entry["score"])
    chapters = [
        {
            "chapter": chapter,
            "diagnosed": len(values),
            "mastered": sum(1 for score in values if score >= MASTERED_SCORE),
            "weak": sum(1 for score in values if score < MASTERED_SCORE),
            "averageScore": round(sum(values) / len(values), 1),
        }
        for chapter, values in chapter_scores.items()
    ]

    recent: list[dict] = []
    for entry in reversed(entries[-RECENT_LIMIT:]):
        point = graph.points.get(str(entry.get("pointId")))
        recent.append({
            "pointId": entry.get("pointId"),
            "name": point.name if point else entry.get("pointId"),
            "chapter": point.chapter if point else "",
            "score": entry.get("score"),
            "comment": entry.get("comment", ""),
            "source": entry.get("source", ""),
            "at": entry.get("at", ""),
        })

    return {
        "diagnosed": len(latest),
        "mastered": mastered,
        "weak": weak,
        "averageScore": average,
        "chapters": chapters,
        "weakPoints": diagnosis.weak_report(uid, graph)["weak"][:WEAK_LIMIT],
        "recent": recent,
    }


async def learning_profile(request: Request) -> JSONResponse:
    """GET /api/profile:当前账号的学习画像。"""
    rec = auth.require_auth(request)
    return JSONResponse(summarize(str(rec.get("uid") or "")))
