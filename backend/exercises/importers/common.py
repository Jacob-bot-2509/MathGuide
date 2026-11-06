"""导入器公共工具:文本清洗、语言判定、来源元数据与质量门收尾。"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from .. import schema
from ..gate import gate_exercise

_CJK_RE = re.compile(r"[㐀-鿿]")
_IMAGE_RE = re.compile(r"<image[_0-9]*>", re.I)


class ImportSkip(ValueError):
    """该行不可导入;reason 用于构建统计。"""


def text_of(value: Any) -> str:
    """支持 str、list[str]、None;列表按段落拼接。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n\n".join(parts)
    return str(value).strip()


def language_of(text: str) -> str:
    return "zh" if _CJK_RE.search(text) else "en"


def has_image(question: str, row: dict[str, Any] | None = None) -> bool:
    if _IMAGE_RE.search(question or ""):
        return True
    if not row:
        return False
    if str(row.get("modality", "")).lower().startswith("multi"):
        return True
    return any(row.get(f"image_{index}") not in (None, "", []) for index in range(1, 10))


def finalize(exercise: schema.Exercise) -> schema.Exercise:
    result = gate_exercise(exercise)
    if not result.accepted:
        raise ImportSkip("gate:" + ",".join(result.reasons))
    return replace(exercise, quality=result.to_quality())


def make_exercise(
    *,
    exercise_id: str,
    source: schema.Source,
    language: str,
    question: str,
    answer: str,
    solution: str,
    exercise_type: str,
    difficulty: int,
    primary_topic: str,
    cross_topics: tuple[str, ...] = (),
) -> schema.Exercise:
    data = {
        "id": exercise_id,
        "source": {
            "name": source.name,
            "tier": source.tier,
            "license": source.license,
            "url": source.url,
            "attribution": source.attribution,
            "license_scope": source.license_scope,
        },
        "original_language": language,
        "content": {
            language: {
                "question": question,
                "answer": answer,
                "solution": solution,
            }
        },
        "type": exercise_type,
        "difficulty": difficulty,
        "difficulty_source": "rule",
        "primary_topic": primary_topic,
        "topics": [primary_topic],
        "cross_topics": list(cross_topics),
        "tag_source": "rule",
    }
    return schema.parse_exercise(data)
