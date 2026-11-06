"""习题 JSONL schema:结构校验、双语内容、来源许可与稳定哈希。

只做结构约束;题干/答案/过程的质量门槛在 gate.py。
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import taxonomy

LANGUAGE_ORDER: tuple[str, ...] = ("en", "zh")
TIERS: tuple[str, ...] = ("safe", "research", "blocked")
EXERCISE_TYPES: tuple[str, ...] = (
    "choice",
    "fill",
    "compute",
    "proof",
    "apply",
    "comprehensive",
)
DIFFICULTY_SOURCES: tuple[str, ...] = ("source", "rule", "manual")
TRANSLATION_STATUSES: tuple[str, ...] = ("native", "machine", "reviewed")
TAG_SOURCES: tuple[str, ...] = ("rule", "llm", "manual")
MANUAL_REVIEW_STATES: tuple[str, ...] = ("passed", "pending", "rejected")

_HASH_PREFIX = "sha256:"
_SPACE_RE = re.compile(r"\s+")


class SchemaError(ValueError):
    """习题字段不合法。"""


@dataclass(frozen=True)
class Source:
    name: str
    tier: str
    license: str
    url: str
    attribution: str
    license_scope: str = "dataset"


@dataclass(frozen=True)
class Translation:
    status: str = "native"
    model: str = ""
    version: int = 1
    reviewed: bool = False


@dataclass(frozen=True)
class LocalizedContent:
    question: str
    answer: str
    solution: str
    solution_steps: tuple[str, ...] = ()
    translation: Translation = field(default_factory=Translation)


@dataclass(frozen=True)
class Exercise:
    id: str
    source: Source
    original_language: str
    content: dict[str, LocalizedContent]
    type: str
    difficulty: int
    difficulty_source: str
    primary_topic: str
    topics: tuple[str, ...]
    cross_topics: tuple[str, ...]
    tag_source: str
    quality: dict[str, Any]
    hash: str

    @property
    def available_languages(self) -> tuple[str, ...]:
        """按固定顺序返回内容完整的语种,不受 JSON 键顺序影响。"""
        return tuple(lang for lang in LANGUAGE_ORDER if lang in self.content)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": {
                "name": self.source.name,
                "tier": self.source.tier,
                "license": self.source.license,
                "url": self.source.url,
                "attribution": self.source.attribution,
                "license_scope": self.source.license_scope,
            },
            "original_language": self.original_language,
            "content": {
                lang: {
                    "question": item.question,
                    "answer": item.answer,
                    "solution": item.solution,
                    "solution_steps": list(item.solution_steps),
                    "translation": {
                        "status": item.translation.status,
                        "model": item.translation.model,
                        "version": item.translation.version,
                        "reviewed": item.translation.reviewed,
                    },
                }
                for lang, item in self.content.items()
            },
            "type": self.type,
            "difficulty": self.difficulty,
            "difficulty_source": self.difficulty_source,
            "primary_topic": self.primary_topic,
            "topics": list(self.topics),
            "cross_topics": list(self.cross_topics),
            "tag_source": self.tag_source,
            "quality": dict(self.quality),
            "hash": self.hash,
        }


def question_hash(text: str) -> str:
    """题干归一化哈希:忽略大小写与全部空白,保留标点/公式。"""
    normalized = _SPACE_RE.sub("", text).lower()
    return _HASH_PREFIX + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{path} 必须是非空字符串")
    text = value.strip()
    if not text:
        raise SchemaError(f"{path} 不能为空")
    return text


def _optional_text(value: Any, path: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SchemaError(f"{path} 必须是字符串")
    return value.strip()


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{path} 必须是对象")
    return value


def _parse_source(value: Any) -> Source:
    raw = _mapping(value, "source")
    tier = _text(raw.get("tier"), "source.tier")
    if tier not in TIERS:
        raise SchemaError(f"source.tier 不合法: {tier}")
    license_scope = raw.get("license_scope", "dataset")
    if license_scope not in ("dataset", "item"):
        raise SchemaError(f"source.license_scope 不合法: {license_scope}")
    return Source(
        name=_text(raw.get("name"), "source.name"),
        tier=tier,
        license=_text(raw.get("license"), "source.license"),
        url=_text(raw.get("url"), "source.url"),
        attribution=_text(raw.get("attribution"), "source.attribution"),
        license_scope=license_scope,
    )


def _parse_translation(value: Any, path: str) -> Translation:
    raw = _mapping(value, path)
    status = _text(raw.get("status"), f"{path}.status")
    if status not in TRANSLATION_STATUSES:
        raise SchemaError(f"{path}.status 不合法: {status}")
    model = _optional_text(raw.get("model", ""), f"{path}.model")
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SchemaError(f"{path}.version 必须是正整数")
    reviewed = raw.get("reviewed", status in ("native", "reviewed"))
    if not isinstance(reviewed, bool):
        raise SchemaError(f"{path}.reviewed 必须是布尔值")
    return Translation(status=status, model=model, version=version, reviewed=reviewed)


def _parse_localized(value: Any, path: str, lang: str, original: str) -> LocalizedContent:
    raw = _mapping(value, path)
    steps = raw.get("solution_steps", [])
    if not isinstance(steps, (list, tuple)):
        raise SchemaError(f"{path}.solution_steps 必须是数组")
    clean_steps = tuple(_text(step, f"{path}.solution_steps") for step in steps)
    translation_value = raw.get("translation")
    if translation_value is None:
        translation = Translation(
            status="native" if lang == original else "machine",
            reviewed=lang == original,
        )
    else:
        translation = _parse_translation(translation_value, f"{path}.translation")
    return LocalizedContent(
        question=_text(raw.get("question"), f"{path}.question"),
        answer=_text(raw.get("answer"), f"{path}.answer"),
        solution=_text(raw.get("solution"), f"{path}.solution"),
        solution_steps=clean_steps,
        translation=translation,
    )


def _parse_quality(value: Any) -> dict[str, Any]:
    if value is None:
        return {
            "gate_version": 1,
            "answer_in_solution": False,
            "latex_ok": False,
            "ocr_ok": False,
            "manual_review": "pending",
        }
    raw = _mapping(value, "quality")
    version = raw.get("gate_version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SchemaError("quality.gate_version 必须是正整数")
    for key in ("answer_in_solution", "latex_ok", "ocr_ok"):
        if not isinstance(raw.get(key, False), bool):
            raise SchemaError(f"quality.{key} 必须是布尔值")
    review = raw.get("manual_review", "pending")
    if review not in MANUAL_REVIEW_STATES:
        raise SchemaError(f"quality.manual_review 不合法: {review}")
    return {
        "gate_version": version,
        "answer_in_solution": raw.get("answer_in_solution", False),
        "latex_ok": raw.get("latex_ok", False),
        "ocr_ok": raw.get("ocr_ok", False),
        "manual_review": review,
    }


def parse_exercise(value: Mapping[str, Any]) -> Exercise:
    """把一行 JSON 转成 Exercise;任何结构问题抛 SchemaError。"""
    raw = _mapping(value, "exercise")
    exercise_id = _text(raw.get("id"), "id")
    source = _parse_source(raw.get("source"))

    original = _text(raw.get("original_language"), "original_language")
    if original not in LANGUAGE_ORDER:
        raise SchemaError(f"original_language 不合法: {original}")

    content_raw = _mapping(raw.get("content"), "content")
    if not content_raw:
        raise SchemaError("content 不能为空")
    content: dict[str, LocalizedContent] = {}
    for lang, block in content_raw.items():
        if lang not in LANGUAGE_ORDER:
            raise SchemaError(f"content 含未知语言: {lang}")
        content[lang] = _parse_localized(block, f"content.{lang}", lang, original)
    if original not in content:
        raise SchemaError(f"content 缺少原语种 {original}")

    exercise_type = _text(raw.get("type"), "type")
    if exercise_type not in EXERCISE_TYPES:
        raise SchemaError(f"type 不合法: {exercise_type}")

    difficulty = raw.get("difficulty")
    if isinstance(difficulty, bool) or not isinstance(difficulty, int) or not 1 <= difficulty <= 5:
        raise SchemaError("difficulty 必须是 1~5 的整数")

    difficulty_source = _text(raw.get("difficulty_source"), "difficulty_source")
    if difficulty_source not in DIFFICULTY_SOURCES:
        raise SchemaError(f"difficulty_source 不合法: {difficulty_source}")

    primary = _text(raw.get("primary_topic"), "primary_topic")
    topics_raw = raw.get("topics", [])
    cross_raw = raw.get("cross_topics", [])
    if not isinstance(topics_raw, (list, tuple)):
        raise SchemaError("topics 必须是数组")
    if not isinstance(cross_raw, (list, tuple)):
        raise SchemaError("cross_topics 必须是数组")
    try:
        topics, cross = taxonomy.validate_topics(
            primary,
            [_text(item, "topics") for item in topics_raw],
            [_text(item, "cross_topics") for item in cross_raw],
        )
    except taxonomy.TaxonomyError as exc:
        raise SchemaError(str(exc)) from exc

    tag_source = _text(raw.get("tag_source"), "tag_source")
    if tag_source not in TAG_SOURCES:
        raise SchemaError(f"tag_source 不合法: {tag_source}")

    quality = _parse_quality(raw.get("quality"))
    hash_value = raw.get("hash")
    if hash_value is None:
        hash_value = question_hash(content[original].question)
    else:
        hash_value = _text(hash_value, "hash")

    return Exercise(
        id=exercise_id,
        source=source,
        original_language=original,
        content=content,
        type=exercise_type,
        difficulty=difficulty,
        difficulty_source=difficulty_source,
        primary_topic=primary,
        topics=topics,
        cross_topics=cross,
        tag_source=tag_source,
        quality=quality,
        hash=hash_value,
    )
