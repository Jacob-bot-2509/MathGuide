"""导入器公共工具:文本清洗、语言判定、来源元数据与质量门收尾。"""
from __future__ import annotations

import html
import re
from dataclasses import replace
from typing import Any

from .. import schema
from ..gate import gate_exercise

_CJK_RE = re.compile(r"[㐀-鿿]")
_IMAGE_RE = re.compile(r"<image[_0-9]*>", re.I)
_TAG_RE = re.compile(r"</?[A-Za-z][^<>]{0,24}>")
_LEAK_RES = (
    re.compile(r"请提供需要翻译的[^。\n]{0,40}。?"),
    re.compile(r"请?保留源文本的换行和格式[^。\n]{0,40}。?"),
    re.compile(r"请?保留原文的换行符和格式[^。\n]{0,40}。?"),
    re.compile(r"直接输出翻译结果[^。\n]{0,10}。?"),
    re.compile(r"(?:请)?将(?:上面|上述)的?文本翻译[^。\n]{0,50}。?"),
    re.compile(r"(?:please\s+)?(?:preserve|maintaining)\s+the\s+(?:original\s+)?"
               r"(?:text'?s?\s+)?line\s+breaks[^.\n]{0,90}\.?", re.I),
    re.compile(r"output\s+the\s+translation\s+result\s+directly\.?", re.I),
    re.compile(r"(?:the\s+above\s+text\s+has\s+been\s+translated|"
               r"the\s+original\s+text\s+has\s+been\s+translated)[^.\n]{0,80}\.?", re.I),
    re.compile(r"directly\s+output\s+the\s+translation\s+result\.?", re.I),
)
_LEAK_MARK_RE = re.compile(
    r"请提供需要翻译|保留源文本的换行|保留原文的换行|直接输出翻译结果|"
    r"将(?:上面|上述)的?文本翻译|line\s+breaks\s+and\s+format|"
    r"output\s+the\s+translation\s+result",
    re.I,
)


def clean_text(text: str) -> str:
    """去掉源数据里的 HTML 标签、实体与翻译提示词残留。"""
    value = html.unescape(_TAG_RE.sub("", text or ""))
    for pattern in _LEAK_RES:
        value = pattern.sub(" ", value)
    return " ".join(value.split())


def has_leak(text: str) -> bool:
    return bool(_LEAK_MARK_RE.search(text or ""))


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
    """按正文主导文字判定语种;一个中文人名不应把英文题判成中文。"""
    cjk = len(_CJK_RE.findall(text or ""))
    latin = len(re.findall(r"[A-Za-z]{2,}", text or ""))
    if cjk and cjk >= max(5, latin * 0.5):
        return "zh"
    return "en" if latin else ("zh" if cjk else "en")


def has_image(question: str, row: dict[str, Any] | None = None) -> bool:
    if _IMAGE_RE.search(question or ""):
        return True
    if not row:
        return False
    if str(row.get("modality", "")).lower().startswith("multi"):
        return True
    return any(row.get(f"image_{index}") not in (None, "", []) for index in range(1, 10))


def finalize(exercise: schema.Exercise) -> schema.Exercise:
    content = exercise.content[exercise.original_language]
    if has_leak(content.question) or has_leak(content.answer) or has_leak(content.solution):
        raise ImportSkip("prompt_leak")
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
                "question": clean_text(question),
                "answer": clean_text(answer),
                "solution": clean_text(solution),
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
