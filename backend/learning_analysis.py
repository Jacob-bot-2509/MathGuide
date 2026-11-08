"""学习分析:把知识图谱与诊断记录汇总成可解释的掌握度快照。

职责边界:
- 只读 diagnosis / knowledge_graph,不写任何数据;
- 所有数字由服务端计算,模型只负责解读与组织语言;
- 快照同时供 `/api/profile/analysis`、聊天指令「学习分析」和前端分析面板使用。

口径:
- 已掌握:最近诊断 >= MASTERED_SCORE;
- 薄弱:最近诊断 < MASTERED_SCORE;
- 待复核:按艾宾浩斯遗忘曲线 R(t,s)=exp(-t/tau(s)) 计算,
  tau(s)=TAU_BASE+TAU_STEP*(s-1) 天;R 低于 REVIEW_RETENTION 进入待复核。
  待复核只影响复习优先级,不改写已掌握/薄弱,也不阻断前置门槛;
- 前沿:前置已满足、自身未掌握的知识点;
- 数据质量:0 条为 none,少于 MIN_SAMPLE 条为 sparse,否则 ok。
"""
from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import diagnosis
from knowledge_graph import KnowledgeGraph, KnowledgePoint
from recommendation import MASTERED_SCORE

TAU_BASE = 30.0
TAU_STEP = 15.0
REVIEW_RETENTION = 0.6
MIN_SAMPLE = 8
BOTTLENECK_LIMIT = 5
NEXT_LIMIT = 5
SUGGEST_LIMIT = 5
FOOTER_LIMIT = 8


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_at(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(at, now: datetime) -> int | None:
    parsed = _parse_at(at)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds() // 86400))


def _memory_strength(score: int) -> float:
    """记忆强度(天):艾宾浩斯曲线的时间常数,掌握度越高衰减越慢。"""
    score = max(1, min(5, int(score)))
    return TAU_BASE + TAU_STEP * (score - 1)


def _retention(age: int | None, score: int | None) -> float | None:
    """R(t,s)=exp(-t/tau(s));0 天为 1,随时间单调下降。"""
    if score is None or age is None:
        return None
    if age <= 0:
        return 1.0
    return math.exp(-age / _memory_strength(score))


def _effective_score(score: int | None, retention: float | None) -> float | None:
    """记忆折减后的参考分,仅用于分析展示,不参与掌握度判定。"""
    if score is None or retention is None:
        return None
    return round(1 + (score - 1) * retention, 2)


def _quality(diagnosed: int) -> str:
    if diagnosed <= 0:
        return "none"
    return "sparse" if diagnosed < MIN_SAMPLE else "ok"


def _ratio(part: int, total: int) -> float:
    return round(part / total, 3) if total else 0.0


def _chapter_rows(graph: KnowledgeGraph, info: dict[str, dict]) -> list[dict]:
    rows: dict[str, dict] = {}
    for point_id, point in graph.points.items():
        row = rows.setdefault(point.chapter, {
            "chapter": point.chapter,
            "total": 0,
            "diagnosed": 0,
            "mastered": 0,
            "weak": 0,
            "_scores": [],
        })
        row["total"] += 1
        item = info[point_id]
        if item["score"] is None:
            continue
        row["diagnosed"] += 1
        row["_scores"].append(item["score"])
        if item["score"] >= MASTERED_SCORE:
            row["mastered"] += 1
        else:
            row["weak"] += 1

    result: list[dict] = []
    for row in rows.values():
        scores = row.pop("_scores")
        row["averageScore"] = (
            round(sum(scores) / len(scores), 1) if scores else None)
        row["coverageRatio"] = _ratio(row["diagnosed"], row["total"])
        result.append(row)
    return result


def build_snapshot(uid: str, graph: KnowledgeGraph | None = None,
                   latest_map: dict[str, dict] | None = None,
                   now: datetime | None = None) -> dict:
    """汇总一个账号的学习快照。latest_map/now 仅测试注入用。"""
    graph = graph or diagnosis.get_graph()
    latest = diagnosis.latest(uid) if latest_map is None else latest_map
    now = now or _now()

    info: dict[str, dict] = {}
    for point_id, point in graph.points.items():
        entry = latest.get(point_id) or {}
        score = entry.get("score")
        score = int(score) if isinstance(score, int) else None
        age = _age_days(entry.get("at"), now) if score is not None else None
        retention = _retention(age, score)
        info[point_id] = {
            "point": point,
            "score": score,
            "age": age,
            "retention": retention,
            "stale": retention is not None and retention < REVIEW_RETENTION,
            "effectiveScore": _effective_score(score, retention),
        }

    total = len(graph.points)
    diagnosed = sum(1 for item in info.values() if item["score"] is not None)
    mastered = sum(
        1 for item in info.values()
        if item["score"] is not None and item["score"] >= MASTERED_SCORE)
    weak = sum(
        1 for item in info.values()
        if item["score"] is not None and item["score"] < MASTERED_SCORE)
    stale_count = sum(1 for item in info.values() if item["stale"])

    def gate_ok(point: KnowledgePoint) -> bool:
        # 遗忘只排复习,不撤销前置资格
        return all(
            (info[prereq]["score"] or 0) >= MASTERED_SCORE
            for prereq in point.prerequisites
        )

    frontier = [
        point_id for point_id, point in graph.points.items()
        if (info[point_id]["score"] or 0) < MASTERED_SCORE
        and gate_ok(point)
    ]
    frontier_diagnosed = sum(
        1 for point_id in frontier if info[point_id]["score"] is not None)

    order = {point_id: index for index, point_id in enumerate(graph.topological_order())}

    def _point_row(point_id: str) -> dict:
        point = graph.points[point_id]
        item = info[point_id]
        return {
            "pointId": point_id,
            "name": point.name,
            "chapter": point.chapter,
            "difficulty": point.difficulty,
            "score": item["score"],
            "effectiveScore": item["effectiveScore"],
            "retention": item["retention"],
            "tauDays": (
                round(_memory_strength(item["score"]), 1)
                if item["score"] is not None else None),
            "descendantCount": graph.descendant_count(point_id),
            "stale": item["stale"],
            "reason": "review" if item["score"] is not None else "new",
        }

    bottlenecks = []
    for point_id, item in info.items():
        if item["score"] is None:
            continue
        if not (item["stale"] or item["score"] < MASTERED_SCORE):
            continue
        row = _point_row(point_id)
        if row["stale"]:
            row["reason"] = "stale"
        bottlenecks.append(row)
    bottlenecks.sort(key=lambda row: (
        -row["descendantCount"],
        row["effectiveScore"],
        order[row["pointId"]],
    ))
    bottlenecks = bottlenecks[:BOTTLENECK_LIMIT]

    next_ids = [
        point_id for point_id, point in graph.points.items()
        if info[point_id]["score"] is not None
        and (info[point_id]["score"] < MASTERED_SCORE or info[point_id]["stale"])
        and gate_ok(point)
    ] + [point_id for point_id in frontier if info[point_id]["score"] is None]
    next_steps = [_point_row(point_id) for point_id in next_ids]
    for row in next_steps:
        row["why"] = {
            "code": row["reason"],
            "mastery": row["score"],
            "difficulty": row["difficulty"],
            "retention": row["retention"],
            "tauDays": row["tauDays"],
            "unlocks": row["descendantCount"],
        }
    next_steps.sort(key=lambda row: (
        0 if row["score"] is not None else 1,
        -row["descendantCount"],
        row["difficulty"],
        order[row["pointId"]],
    ))
    next_steps = next_steps[:NEXT_LIMIT]

    suggested = [
        _point_row(point_id)
        for point_id in frontier
        if info[point_id]["score"] is None
    ]
    suggested.sort(key=lambda row: (
        -row["descendantCount"],
        row["difficulty"],
        order[row["pointId"]],
    ))
    suggested = suggested[:SUGGEST_LIMIT]

    stale = [
        {
            **_point_row(point_id),
            "at": (latest.get(point_id) or {}).get("at", ""),
            "days": info[point_id]["age"] or 0,
        }
        for point_id, item in info.items()
        if item["stale"]
    ]
    stale.sort(key=lambda row: (
        row["retention"], -row["days"], order[row["pointId"]]))

    return {
        "generatedAt": now.isoformat(timespec="seconds"),
        "dataQuality": _quality(diagnosed),
        "limits": {
            "reviewRetention": REVIEW_RETENTION,
            "tauBase": TAU_BASE,
            "tauStep": TAU_STEP,
            "minSample": MIN_SAMPLE,
        },
        "coverage": {
            "total": total,
            "diagnosed": diagnosed,
            "ratio": _ratio(diagnosed, total),
            "frontierTotal": len(frontier),
            "frontierDiagnosed": frontier_diagnosed,
            "frontierRatio": _ratio(frontier_diagnosed, len(frontier)),
        },
        "structure": {
            "mastered": mastered,
            "weak": weak,
            "stale": stale_count,
            "undiagnosed": total - diagnosed,
        },
        "chapters": _chapter_rows(graph, info),
        "bottlenecks": bottlenecks,
        "stale": stale,
        "nextSteps": next_steps,
        "suggestedDiagnosis": suggested,
    }


def system_prompt(snapshot: dict, zh: bool = True) -> str:
    """把算好的快照交给模型;只允许解读,不允许补数。"""
    facts = json.dumps(snapshot, ensure_ascii=False, indent=2)
    if zh:
        return (
            "你是 MathGuide 的学习分析师。下面【学习事实】由服务端根据知识图谱和"
            "诊断记录计算得出,是唯一可用的事实来源。\n"
            "硬性要求:\n"
            "1. 只能引用【学习事实】里的数字与知识点;不得编造分数、覆盖率、"
            "章节或前置关系,不得自行估算缺失数据。\n"
            "2. 按以下顺序组织回答:覆盖度 → 掌握结构 → 章节均衡 → 前置瓶颈 → "
            "待复核 → 下一步。\n"
            "3. dataQuality 为 none 或 sparse 时,先明确说明数据不足,"
            "再给已有事实与下一步建议,不要假装掌握情况完整。\n"
            "4. 待复核由服务端按艾宾浩斯遗忘曲线计算。直接引用快照里的 score、"
            "tauDays、retention、days;不要自行重算时间常数或保持率,也不要在正文里"
            "推导公式。遗忘只影响复习优先级,不推翻原始诊断分,也不阻断前置。\n"
            "5. 下一步只从 nextSteps 中选,说明理由;不要把未诊断当作已掌握。\n"
            "6. 不画图,不输出图解标记;语言跟随用户提问。\n\n"
            f"【学习事实】\n{facts}"
        )
    return (
        "You are MathGuide's learning analyst. The LEARNING FACTS below are computed "
        "server-side from the knowledge graph and diagnosis records; they are the only "
        "source of truth.\n"
        "Hard rules:\n"
        "1. Use only the numbers and points in LEARNING FACTS. Do not invent scores, "
        "coverage, chapters or prerequisites, and do not estimate missing data.\n"
        "2. Structure the answer in this order: Coverage -> Mastery structure -> "
        "Chapter balance -> Prerequisite bottlenecks -> Stale reviews -> Next steps.\n"
        "3. If dataQuality is none or sparse, say clearly that the data is "
        "insufficient before giving the available facts and next steps.\n"
        "4. Review-due points are computed server-side with the Ebbinghaus curve. "
        "Quote score, tauDays, retention and days from the snapshot; do not "
        "recompute the time constant or retention, and do not restate the formula. "
        "Forgetting affects review priority only; it does not overrule the "
        "original score or block prerequisites.\n"
        "5. Pick next steps only from nextSteps and explain why. Never treat an "
        "undiagnosed point as mastered.\n"
        "6. Do not draw diagrams or emit diagram markers. Answer in the user's "
        "language.\n\n"
        f"LEARNING FACTS\n{facts}"
    )


def fallback_report(snapshot: dict, zh: bool = True) -> str:
    """模型未配置或未出字时的确定性报告。"""
    coverage = snapshot["coverage"]
    structure = snapshot["structure"]
    if zh:
        lines = [
            "**学习分析 · 掌握度快照**",
            "",
            f"**覆盖度**：已诊断 {coverage['diagnosed']}/{coverage['total']}"
            f"（{round(coverage['ratio'] * 100)}%）；当前可学前沿 "
            f"{coverage['frontierDiagnosed']}/{coverage['frontierTotal']}。",
            f"**掌握结构**：已掌握 {structure['mastered']} · 薄弱 "
            f"{structure['weak']} · 待复核 {structure['stale']} · 未诊断 "
            f"{structure['undiagnosed']}。",
        ]
        chapters = snapshot["chapters"]
        if chapters:
            parts = []
            for row in chapters:
                average = row["averageScore"]
                parts.append(
                    f"{row['chapter']} {row['diagnosed']}/{row['total']}"
                    + (f"（平均 {average}）" if average is not None else ""))
            lines.append("**章节均衡**：" + "；".join(parts) + "。")
        bottlenecks = snapshot["bottlenecks"]
        if bottlenecks:
            lines.append("**前置瓶颈**：" + "；".join(
                f"{row['name']}（影响 {row['descendantCount']} 个后续知识点）"
                for row in bottlenecks) + "。")
        else:
            lines.append("**前置瓶颈**：暂未发现。")
        stale = snapshot["stale"]
        lines.append("**待复核**：" + (
            "；".join(
                f"{row['name']}（{row['days']} 天前，记忆 "
                f"{round((row['retention'] or 0) * 100)}%）"
                for row in stale)
            if stale else "无。"))
        next_steps = snapshot["nextSteps"]
        if next_steps:
            lines.append("**下一步**：" + "；".join(
                f"{row['name']}（{'复习' if row['reason'] == 'review' else '新学'}）"
                for row in next_steps) + "。")
        else:
            lines.append("**下一步**：暂无可推荐知识点,请先补充诊断。")
        if snapshot["dataQuality"] == "none":
            lines.insert(1, "\n> 还没有诊断记录。先做几个知识点的自评,分析才有依据。")
        elif snapshot["dataQuality"] == "sparse":
            lines.insert(1, "\n> 诊断样本偏少,结论只代表已诊断的部分。")
        return "\n".join(lines)

    lines = [
        "**Learning Analysis · Mastery Snapshot**",
        "",
        f"**Coverage**: {coverage['diagnosed']}/{coverage['total']} diagnosed "
        f"({round(coverage['ratio'] * 100)}%); learnable frontier "
        f"{coverage['frontierDiagnosed']}/{coverage['frontierTotal']}.",
        f"**Mastery structure**: mastered {structure['mastered']} · weak "
        f"{structure['weak']} · stale {structure['stale']} · undiagnosed "
        f"{structure['undiagnosed']}.",
    ]
    chapters = snapshot["chapters"]
    if chapters:
        lines.append("**Chapter balance**: " + "; ".join(
            f"{row['chapter']} {row['diagnosed']}/{row['total']}"
            + (f" (avg {row['averageScore']})" if row["averageScore"] is not None else "")
            for row in chapters) + ".")
    bottlenecks = snapshot["bottlenecks"]
    lines.append("**Prerequisite bottlenecks**: " + (
        "; ".join(f"{row['name']} (blocks {row['descendantCount']})"
                  for row in bottlenecks) if bottlenecks else "none found."))
    stale_rows = snapshot["stale"]
    lines.append("**Stale reviews**: " + (
        "; ".join(
            f"{row['name']} ({row['days']} days, retention "
            f"{round((row['retention'] or 0) * 100)}%)"
            for row in stale_rows)
        if stale_rows else "none."))
    next_steps = snapshot["nextSteps"]
    lines.append("**Next steps**: " + (
        "; ".join(f"{row['name']} ({'review' if row['reason'] == 'review' else 'new'})"
                  for row in next_steps)
        if next_steps else "none yet; add more diagnoses."))
    if snapshot["dataQuality"] == "none":
        lines.insert(1, "\n> No diagnosis records yet. Rate a few knowledge points first.")
    elif snapshot["dataQuality"] == "sparse":
        lines.insert(1, "\n> Sparse sample: conclusions cover only diagnosed points.")
    return "\n".join(lines)


def footer_links(snapshot: dict, zh: bool = True) -> str:
    """在回答末尾追加确定性的图谱定位链接,不依赖模型输出格式。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for row in snapshot["bottlenecks"] + snapshot["nextSteps"]:
        if row["pointId"] in seen:
            continue
        seen.add(row["pointId"])
        rows.append(row)
        if len(rows) >= FOOTER_LIMIT:
            break
    if not rows:
        return ""
    links = " · ".join(f"[{row['name']}](cmd://point/{row['pointId']})" for row in rows)
    return f"\n\n{'**定位到图谱**' if zh else '**Open in graph**'}：{links}"


async def analysis_endpoint(request: Request) -> JSONResponse:
    """GET /api/profile/analysis:当前账号的掌握度快照。"""
    rec = auth.require_auth(request)
    snapshot = await asyncio.to_thread(build_snapshot, str(rec.get("uid") or ""))
    return JSONResponse(snapshot)
