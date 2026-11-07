"""习题集生成:按板块/难度/语言抽题,输出可交给 doc.render 的段落式文档。

不调用 LLM,不改写题目;缺译默认排除,allowPartial 时才保留原文并标注。
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse

from chat import _rate_check, require_auth
from exercises.schema import SchemaError
from exercises.store import ExerciseStore, tiers_from_env
from exercises.taxonomy import CATEGORY_KEYS
from http_utils import read_json_object

DATA_DIR = Path(__file__).resolve().parent / "data" / "exercises" / "final"
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
    topics = [str(item) for item in body.get("topics", []) if str(item) in CATEGORY_KEYS]
    cross = [str(item) for item in body.get("crossTopics", []) if str(item)]
    types = [str(item) for item in body.get("types", []) if str(item)]
    raw = body.get("difficulty")
    if isinstance(raw, list) and len(raw) == 2:
        try:
            difficulty = (max(1, int(raw[0])), min(5, int(raw[1])))
        except (TypeError, ValueError):
            difficulty = (1, 5)
    else:
        difficulty = (1, 5)
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
    }


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


def _select(store: ExerciseStore, filters: dict, lang: str, allow_partial: bool, seed: int):
    params = {
        "topics": filters["topics"],
        "cross_topics": filters["cross_topics"],
        "types": filters["types"],
        "difficulty": filters["difficulty"],
    }
    language = "both" if lang == "both" else lang
    selected = list(store.sample(filters["count"], seed=seed, lang=language, **params))
    if allow_partial and len(selected) < filters["count"]:
        seen = {item.id for item in selected}
        for item in store.sample(filters["count"], seed=seed, lang="any", **params):
            if item.id not in seen:
                selected.append(item)
                seen.add(item.id)
            if len(selected) >= filters["count"]:
                break
    return selected[: filters["count"]]


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
            result.append(f"{'答案' if code == 'zh' else 'Answer'}: {content.answer}")
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
        result.append(f"{number}. {'答案' if code == 'zh' else 'Answer'}: {content.answer}")
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
    return {
        "title": "习题集" if lang != "en" else "Exercise Set",
        "abstract": (
            f"由 MathGuide 题库按条件抽取 {len(items)} 题;语言:{lang};模式:{mode}。"
            if lang != "en" else
            f"{len(items)} exercises selected from the MathGuide bank; language: {lang}; mode: {mode}."
        ),
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
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))
    body = await read_json_object(request)
    filters = _filters(body)
    lang = _lang(body.get("lang"))
    allow_partial = bool(body.get("allowPartial"))
    store = _store()
    available = _available(store, filters)
    selected = _select(store, filters, lang, allow_partial, int(body.get("seed", 20261106)))
    gaps = [topic for topic in filters["topics"] if topic not in {item.primary_topic for item in selected}]
    return JSONResponse({
        "available": available,
        "selected": len(selected),
        "missing": max(0, filters["count"] - len(selected)),
        "gaps": gaps,
        "coverage": store.coverage(),
    })


async def generate(request: Request) -> JSONResponse:
    rec = require_auth(request)
    _rate_check(str(rec.get("uid") or rec.get("phone") or ""))
    body = await read_json_object(request)
    filters = _filters(body)
    lang = _lang(body.get("lang"))
    mode = body.get("mode") if body.get("mode") in MODES else "questions"
    allow_partial = bool(body.get("allowPartial"))
    store = _store()
    selected = _select(store, filters, lang, allow_partial, int(body.get("seed", 20261106)))
    if not selected:
        return JSONResponse({
            "error": "no_evidence",
            "available": _available(store, filters),
        }, status_code=422)
    document = _document(selected, lang, mode, allow_partial, filters)
    return JSONResponse({
        "document": document,
        "selected": len(selected),
        "missing": max(0, filters["count"] - len(selected)),
        "gaps": [],
    })
