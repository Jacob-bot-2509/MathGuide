"""知识图谱英文名称、章节名与详情翻译的单一来源。

英文 JSON 与中文 CSV 分离维护:
- `point_names.en.json`:知识点 id → 英文名;
- `point_notes.en.json`:知识点 id → {summary, keyPoints[3]};
- 章节英文名内置在下方映射里(章节是稳定分类,不随 CSV 增删)。

任一侧文件缺失或条目为空时,调用方回退中文,接口不报错。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent / "data"

ENGLISH_CHAPTERS: dict[str, str] = {
    "函数与极限": "Functions and Limits",
    "导数与微分": "Derivatives and Differentials",
    "微分中值定理与导数应用": "Mean Value Theorems and Applications of Derivatives",
    "不定积分": "Indefinite Integrals",
    "定积分": "Definite Integrals",
    "定积分的应用": "Applications of Definite Integrals",
    "微分方程": "Differential Equations",
}


@lru_cache(maxsize=1)
def english_names() -> dict[str, str]:
    try:
        raw = json.loads((_DATA_DIR / "point_names.en.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value.strip()
        for key, value in raw.items()
        if isinstance(value, str) and value.strip()
    }


@lru_cache(maxsize=1)
def english_notes() -> dict[str, dict]:
    try:
        raw = json.loads((_DATA_DIR / "point_notes.en.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        summary = value.get("summary")
        points = value.get("keyPoints")
        if not isinstance(summary, str) or not summary.strip():
            continue
        if not isinstance(points, list) or len(points) != 3:
            continue
        if not all(isinstance(item, str) and item.strip() for item in points):
            continue
        out[str(key)] = {"summary": summary.strip(),
                         "keyPoints": [item.strip() for item in points]}
    return out


def english_name(point_id: str) -> str:
    return english_names().get(point_id, "")


def english_note(point_id: str) -> dict:
    return english_notes().get(point_id, {})


def chapter_en(chapter: str) -> str:
    return ENGLISH_CHAPTERS.get(chapter, "")
