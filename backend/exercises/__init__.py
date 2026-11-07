"""习题库:结构校验、质量门、去重、词表与存储。"""
from __future__ import annotations

from .schema import Exercise, LocalizedContent, SchemaError, Source, Translation, parse_exercise

__all__ = [
    "Exercise",
    "LocalizedContent",
    "SchemaError",
    "Source",
    "Translation",
    "parse_exercise",
]
