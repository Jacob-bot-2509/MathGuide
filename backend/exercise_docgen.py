"""习题集生成:按板块/难度/语言抽题,输出可交给 doc.render 的段落式文档。

不调用 LLM,不改写题目;缺译默认排除,allowPartial 时才保留原文并标注。

当前题库绑定:临时题库(bilingual/all.jsonl + staging)作为正式后端库使用;
人工复验完成后替换为 verified 数据即可,接口与前端无需改动。
"""
from __future__ import annotations

import random
from collections.abc import Iterable
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

import math_render
import quota
import exercise_history
from chat import _rate_check, require_auth
from exercises.schema import SchemaError
from exercises.store import ExerciseStore, tiers_from_env
from exercises.taxonomy import CATEGORY_KEYS
from http_utils import read_json_object

DATA_DIR = Path(__file__).resolve().parent / "data" / "exercises" / "staging"
BILINGUAL_FILE = Path(__file__).resolve().parent / "data" / "exercises" / "bilingual" / "all.jsonl"
MAX_COUNT = 100
MODES = ("questions", "answers", "solutions", "combined")

TOPIC_LABELS = {
    "analysis": ("数学分析", "Mathematical Analysis"),
    "algebra": ("高等代数", "Advanced Algebra"),
    "geometry": ("空间解析几何", "Analytic Geometry"),
    "ode": ("微分方程", "Differential Equations"),
    "probability": ("概率论与数理统计", "Probability & Statistics"),
    "complex": ("复变函数", "Complex Analysis"),
    "numberTheory": ("数论", "Number Theory"),
    "topology": ("拓扑学", "Topology"),
}

# 需求文本里的确定性约束词。只做显式命中,不做语义猜测:
# 用户写「证明题 / 基础 / 泰勒」时,题库筛选立刻收窄;没写就不过滤。
_TYPE_HINTS = (
    ("证明", "proof"), ("proof", "proof"),
    ("计算", "compute"), ("compute", "compute"),
    ("选择", "choice"), ("choice", "choice"),
    ("填空", "fill"), ("fill", "fill"),
    ("应用", "apply"), ("apply", "apply"),
    ("综合", "comprehensive"), ("comprehensive", "comprehensive"),
)
_EASY_HINTS = ("基础", "简单", "入门", "easy", "basic", "beginner")
_MEDIUM_HINTS = ("中等", "medium", "intermediate")
_HARD_HINTS = ("困难", "挑战", "难题", "提高", "hard", "advanced", "challenge")
_CROSS_HINTS = (
    ("泰勒", "taylor"), ("taylor", "taylor"),
    ("傅里叶", "fourier-series"), ("fourier", "fourier-series"),
    ("格林", "green-theorem"), ("green", "green-theorem"),
    ("斯托克斯", "stokes-theorem"), ("stokes", "stokes-theorem"),
    ("特征值", "eigen"), ("eigen", "eigen"),
    ("二次型", "quadratic-form"), ("quadratic form", "quadratic-form"),
    ("最小二乘", "least-squares"), ("least squares", "least-squares"),
    ("雅可比", "jacobian"), ("jacobian", "jacobian"),
    ("留数", "residue"), ("residue", "residue"),
    ("幂级数", "power-series"), ("power series", "power-series"),
    ("欧拉", "euler-formula"), ("euler", "euler-formula"),
    ("柯西黎曼", "cauchy-riemann"), ("cauchy-riemann", "cauchy-riemann"),
    ("散度", "divergence-theorem"), ("divergence", "divergence-theorem"),
    ("线面积分", "line-surface-integral"),
    ("卷积", "convolution"),
    ("马尔可夫", "markov-chain"), ("markov", "markov-chain"),
)


def _requirement_filters(requirement: str) -> dict:
    """从自由描述中提取题型/难度/交叉知识点;显式字段优先。"""
    text = (requirement or "").lower()
    types: list[str] = []
    for hint, value in _TYPE_HINTS:
        if hint in text and value not in types:
            types.append(value)
    if any(hint in text for hint in _HARD_HINTS):
        difficulty = (4, 5)
    elif any(hint in text for hint in _MEDIUM_HINTS):
        difficulty = (3, 3)
    elif any(hint in text for hint in _EASY_HINTS):
        difficulty = (1, 2)
    else:
        difficulty = None
    cross: list[str] = []
    for hint, value in _CROSS_HINTS:
        if hint in text and value not in cross:
            cross.append(value)
    return {"types": types, "difficulty": difficulty, "cross_topics": cross}


_STORE_CACHE: dict[str, tuple[tuple[int, int], ExerciseStore]] = {}


def _store() -> ExerciseStore:
    tiers = tiers_from_env()
    if BILINGUAL_FILE.is_file():
        stamp = (BILINGUAL_FILE.stat().st_mtime_ns, BILINGUAL_FILE.stat().st_size)
        cached = _STORE_CACHE.get("bilingual")
        if cached and cached[0] == stamp:
            return cached[1]
        try:
            store = ExerciseStore.from_jsonl([BILINGUAL_FILE], tiers=tiers)
        except SchemaError:
            # 翻译进程正在写最后一行时可能读到半行;退回完整单语库。
            return ExerciseStore.from_directory(DATA_DIR, tiers=tiers)
        _STORE_CACHE["bilingual"] = (stamp, store)
        return store
    return ExerciseStore.from_directory(DATA_DIR, tiers=tiers)


def _lang(value: object, text: str = "") -> str:
    return value if value in ("zh", "en", "both") else ("zh" if text else "zh")


def _labels(topic: str, lang: str) -> str:
    zh, en = TOPIC_LABELS.get(topic, (topic, topic))
    return zh if lang != "en" else en


def _filters(body: dict) -> dict:
    requirement = str(body.get("requirement") or "").strip()[:200]
    inferred = _requirement_filters(requirement)
    topics = [str(item) for item in body.get("topics", []) if str(item) in CATEGORY_KEYS]
    cross = [str(item) for item in body.get("crossTopics", []) if str(item)]
    types = [str(item) for item in body.get("types", []) if str(item)]
    if not cross:
        cross = inferred["cross_topics"]
    if not types:
        types = inferred["types"]
    raw = body.get("difficulty")
    difficulty = None
    if isinstance(raw, list) and len(raw) == 2:
        try:
            difficulty = (max(1, int(raw[0])), min(5, int(raw[1])))
        except (TypeError, ValueError):
            difficulty = None
    if difficulty is None:
        difficulty = inferred["difficulty"] or (1, 5)
    count = body.get("count", 20)
    try:
        count = max(1, min(MAX_COUNT, int(count)))
    except (TypeError, ValueError):
        count = 20
    return {
        "topics": topics,
        "cross_topics": cross,
        "types": types,
        "difficulty": difficulty,
        "count": count,
        "requirement": requirement,
    }


def _exclude_ids(body: dict) -> list[str]:
    raw = body.get("excludeIds")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)][:200]


def _history_title(filters: dict, lang: str, count: int) -> str:
    labels = [
        TOPIC_LABELS.get(topic, (topic, topic))[1 if lang == "en" else 0]
        for topic in filters["topics"]
    ]
    scope = "、".join(labels) if labels else ("全部" if lang != "en" else "All")
    if lang == "en":
        return f"Exercise Set · {scope} · {count}"
    return f"习题集 · {scope} · {count} 题"


def _available(store: ExerciseStore, filters: dict) -> dict[str, int]:
    base = store.filter(
        topics=filters["topics"],
        cross_topics=filters["cross_topics"],
        types=filters["types"],
        difficulty=filters["difficulty"],
    )
    return {
        "zh": sum(1 for item in base if "zh" in item.available_languages),
        "en": sum(1 for item in base if "en" in item.available_languages),
        "both": sum(1 for item in base if len(item.available_languages) == 2),
    }


def _sample(items: list, count: int, seed: int) -> list:
    ordered = sorted(items, key=lambda item: item.id)
    if count <= 0:
        return []
    if count >= len(ordered):
        return ordered
    return random.Random(seed).sample(ordered, count)


def _select(
    store: ExerciseStore,
    filters: dict,
    lang: str,
    allow_partial: bool,
    seed: int,
    exclude_ids: Iterable[str] = (),
) -> tuple[list, int]:
    """按条件抽样;排除上一批,池子不足时补回少量重复并报告数量。"""
    params = {
        "topics": filters["topics"],
        "cross_topics": filters["cross_topics"],
        "types": filters["types"],
        "difficulty": filters["difficulty"],
    }
    exclude = {str(item) for item in exclude_ids}
    language = "both" if lang == "both" else lang
    pool = list(store.filter(lang=language, **params))
    fresh = [item for item in pool if item.id not in exclude]
    seen = [item for item in pool if item.id in exclude]
    selected = _sample(fresh, filters["count"], seed)
    reused = 0
    if len(selected) < filters["count"] and seen:
        extra = _sample(seen, filters["count"] - len(selected), seed + 1)
        selected.extend(extra)
        reused += len(extra)
    if allow_partial and len(selected) < filters["count"]:
        chosen = {item.id for item in selected}
        fallback = [
            item for item in store.filter(lang="any", **params)
            if item.id not in chosen
        ]
        fresh_any = [item for item in fallback if item.id not in exclude]
        seen_any = [item for item in fallback if item.id in exclude]
        extra = _sample(fresh_any, filters["count"] - len(selected), seed + 2)
        selected.extend(extra)
        if len(selected) < filters["count"] and seen_any:
            more = _sample(seen_any, filters["count"] - len(selected), seed + 3)
            selected.extend(more)
            reused += len(more)
    return selected[: filters["count"]], reused


def _missing_reason(item, lang: str) -> str:
    return "原文（无中文版）" if lang == "zh" else "original (no English version)"


def _blocks(item, lang: str, mode: str, number: int, allow_partial: bool) -> list[str]:
    languages = []
    if lang == "both":
        languages = [code for code in ("zh", "en") if code in item.content]
    elif lang in item.content:
        languages = [lang]
    elif allow_partial:
        languages = [item.original_language]
    if not languages:
        return []

    result: list[str] = []
    for code in languages:
        content = item.content[code]
        prefix = ""
        if lang == "both":
            prefix = "[中文] " if code == "zh" else "[EN] "
        number_prefix = f"{number}. " if code == languages[0] else ""
        result.append(f"{number_prefix}{prefix}{content.question}")
        if mode in ("answers", "solutions"):
            result.append(f"{'答案' if code == 'zh' else 'Answer'}: {math_render.formula_answer(content.answer)}")
        if mode == "solutions":
            result.append(f"{'解析' if code == 'zh' else 'Solution'}: {content.solution}")
        if lang != "both" and code != lang and allow_partial:
            result.append(_missing_reason(item, lang))
    return result


def _answer_blocks(item, lang: str, number: int, allow_partial: bool) -> list[str]:
    languages = []
    if lang == "both":
        languages = [code for code in ("zh", "en") if code in item.content]
    elif lang in item.content:
        languages = [lang]
    elif allow_partial:
        languages = [item.original_language]
    result = []
    for code in languages:
        content = item.content[code]
        result.append(f"{number}. {'答案' if code == 'zh' else 'Answer'}: {math_render.formula_answer(content.answer)}")
        result.append(f"{'解析' if code == 'zh' else 'Solution'}: {content.solution}")
    return result


def _document(items, lang: str, mode: str, allow_partial: bool, filters: dict) -> dict:
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item.primary_topic, []).append(item)

    sections = []
    number = 0
    for topic in CATEGORY_KEYS:
        if topic not in groups:
            continue
        paragraphs = []
        for item in groups[topic]:
            number += 1
            paragraphs.extend(_blocks(item, lang, "questions" if mode == "combined" else mode,
                                      number, allow_partial))
        if paragraphs:
            sections.append({"heading": _labels(topic, lang), "paragraphs": paragraphs})

    if mode == "combined":
        answers = []
        number = 0
        for topic in CATEGORY_KEYS:
            for item in groups.get(topic, []):
                number += 1
                answers.extend(_answer_blocks(item, lang, number, allow_partial))
        if answers:
            sections.append({
                "heading": "参考答案" if lang != "en" else "Answer Key",
                "paragraphs": answers,
            })

    refs = {}
    for item in items:
        refs[item.source.name] = {
            "title": item.source.name,
            "source": item.source.license,
            "url": item.source.url,
        }
    references = [
        {"id": index + 1, "title": ref["title"], "source": ref["source"], "url": ref["url"]}
        for index, ref in enumerate(refs.values())
    ]
    requirement = str(filters.get("requirement") or "").strip()
    title = requirement[:80] or ("习题集" if lang != "en" else "Exercise Set")
    abstract = (
        f"按你的要求「{requirement}」从 MathGuide 题库抽取 {len(items)} 题;语言:{lang};模式:{mode}。"
        if lang != "en" else
        f"{len(items)} exercises selected from the MathGuide bank for: {requirement}. "
        f"Language: {lang}; mode: {mode}."
    )
    if not requirement:
        abstract = (
            f"由 MathGuide 题库按条件抽取 {len(items)} 题;语言:{lang};模式:{mode}。"
            if lang != "en" else
            f"{len(items)} exercises selected from the MathGuide bank; language: {lang}; mode: {mode}."
        )
    return {
        "title": title,
        "abstract": abstract,
        "keywords": [_labels(topic, lang) for topic in groups],
        "sections": sections,
        "references": references,
        "exercise_meta": {
            "lang": lang,
            "mode": mode,
            "count": len(items),
            "filters": filters,
        },
    }


async def plan(request: Request) -> JSONResponse:
    rec = require_auth(request)
    quota.check(str(rec.get("uid") or ""))
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))
    body = await read_json_object(request)
    filters = _filters(body)
    lang = _lang(body.get("lang"))
    allow_partial = bool(body.get("allowPartial"))
    store = _store()
    available = _available(store, filters)
    seed = int(body.get("seed", 20261106))
    exclude_ids = _exclude_ids(body)
    selected, reused = _select(
        store, filters, lang, allow_partial, seed, exclude_ids)
    gaps = [topic for topic in filters["topics"] if topic not in {item.primary_topic for item in selected}]
    preview = [
        {
            "id": item.id,
            "topic": item.primary_topic,
            "type": item.type,
            "question": item.content[item.original_language].question[:80],
        }
        for item in selected[:3]
    ]
    return JSONResponse({
        "available": available,
        "selected": len(selected),
        "missing": max(0, filters["count"] - len(selected)),
        "gaps": gaps,
        "coverage": store.coverage(),
        "seed": seed,
        "preview": preview,
        "batchIds": [item.id for item in selected],
        "reusedCount": reused,
    })


async def generate(request: Request) -> JSONResponse:
    rec = require_auth(request)
    quota.check(str(rec.get("uid") or ""))
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))
    body = await read_json_object(request)
    filters = _filters(body)
    lang = _lang(body.get("lang"))
    mode = body.get("mode") if body.get("mode") in MODES else "questions"
    allow_partial = bool(body.get("allowPartial"))
    store = _store()
    seed = int(body.get("seed", 20261106))
    exclude_ids = _exclude_ids(body)
    selected, _ = _select(store, filters, lang, allow_partial, seed, exclude_ids)
    if not selected:
        return JSONResponse({
            "error": "no_evidence",
            "available": _available(store, filters),
        }, status_code=422)
    document = _document(selected, lang, mode, allow_partial, filters)
    uid = str(rec.get("uid") or "")
    draft_id = ""
    try:
        draft_id = exercise_history.create_draft(
            uid, document, filters, seed, exclude_ids, lang, mode,
            _history_title(filters, lang, len(selected)),
        )
    except Exception as exc:  # noqa: BLE001 历史失败不能阻断下载
        print(f"[exercise] 历史草稿写入失败: {exc}")
    return JSONResponse({
        "document": document,
        "selected": len(selected),
        "missing": max(0, filters["count"] - len(selected)),
        "gaps": [],
        "draftId": draft_id,
    })


async def history_list(request: Request) -> JSONResponse:
    rec = require_auth(request)
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    uid = str(rec.get("uid") or "")
    return JSONResponse(
        {"items": exercise_history.list_documents(uid, limit)},
        headers={"Cache-Control": "no-store"},
    )


async def history_get(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    detail = exercise_history.get_document(uid, request.path_params["doc_id"])
    if detail is None:
        return JSONResponse({"error": "not_found"}, status_code=404,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse(detail, headers={"Cache-Control": "no-store"})


async def history_delete(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not exercise_history.delete_document(uid, request.path_params["doc_id"]):
        return JSONResponse({"error": "not_found"}, status_code=404,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


async def history_confirm(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    if not exercise_history.confirm(uid, request.path_params["doc_id"]):
        return JSONResponse({"error": "not_found"}, status_code=404,
                            headers={"Cache-Control": "no-store"})
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
