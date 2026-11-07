"""双语翻译:公式占位、数字/占位符校验、译文写回。"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from . import schema

LANGUAGES = ("zh", "en")
Translator = Callable[[str, str, str], str]
TranslatorAsync = Callable[[str, str, str], Awaitable[str]]

_MATH_RE = re.compile(
    r"(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)"
)
_PLACEHOLDER_RE = re.compile(r"\[\[M\d+\]\]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_CJK_RE = re.compile(r"[㐀-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")
_COMMAND_RE = re.compile(r"\\[A-Za-z]+")


@dataclass(frozen=True)
class TranslationCheck:
    ok: bool
    reasons: tuple[str, ...]


class TranslationError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = tuple(reasons)
        super().__init__(", ".join(self.reasons))


def extract_math(text: str) -> tuple[str, tuple[str, ...]]:
    """把数学片段换成 [[M1]] 占位符;返回模板与按顺序的片段。"""
    placeholders: list[str] = []

    def replace(match: re.Match[str]) -> str:
        placeholders.append(match.group(1))
        return f"[[M{len(placeholders)}]]"

    return _MATH_RE.sub(replace, text), tuple(placeholders)


def restore_math(template: str, placeholders: Sequence[str]) -> str:
    value = template
    for index, math in enumerate(placeholders, 1):
        value = value.replace(f"[[M{index}]]", math)
    return value


def _numbers(text: str) -> Counter[str]:
    without_placeholders = _PLACEHOLDER_RE.sub("", text)
    return Counter(_NUMBER_RE.findall(without_placeholders))


def _prose(text: str) -> str:
    """去掉占位符、LaTeX 命令与花括号,只留下自然语言。"""
    value = _PLACEHOLDER_RE.sub("", text)
    value = _COMMAND_RE.sub("", value)
    return value.replace("{", "").replace("}", "")


def validate_translation(
    source: str,
    translated: str,
    placeholders: Sequence[str],
    target_lang: str,
) -> TranslationCheck:
    reasons: list[str] = []
    expected = Counter(f"[[M{index}]]" for index in range(1, len(placeholders) + 1))
    actual = Counter(_PLACEHOLDER_RE.findall(translated))
    if expected != actual:
        reasons.append("placeholder_mismatch")
    if _numbers(source) != _numbers(translated):
        reasons.append("number_mismatch")

    source_prose = _prose(source)
    has_words = bool(_LATIN_RE.search(source_prose) or _CJK_RE.search(source_prose))
    translated_prose = _prose(translated)
    if has_words:
        if target_lang == "zh" and not _CJK_RE.search(translated_prose):
            reasons.append("target_language_mismatch")
        if target_lang == "en" and not _LATIN_RE.search(translated_prose):
            reasons.append("target_language_mismatch")

    source_len = max(len(source), 1)
    ratio = len(translated) / source_len
    if source_len >= 10 and (ratio < 0.25 or ratio > 4.0):
        reasons.append("length_ratio_out_of_range")
    return TranslationCheck(ok=not reasons, reasons=tuple(reasons))


def _translate_text(
    text: str,
    source_lang: str,
    target_lang: str,
    translator: Translator,
) -> str:
    template, placeholders = extract_math(text)
    translated_template = translator(template, source_lang, target_lang)
    if not isinstance(translated_template, str):
        raise TranslationError(("translator_returned_non_string",))
    check = validate_translation(template, translated_template, placeholders, target_lang)
    if not check.ok:
        raise TranslationError(check.reasons)
    return restore_math(translated_template, placeholders)


def _apply_translation(
    exercise: schema.Exercise,
    target_lang: str,
    question: str,
    answer: str,
    solution: str,
    steps: Sequence[str],
    model: str,
) -> schema.Exercise:
    data = exercise.to_dict()
    data["content"][target_lang] = {
        "question": question,
        "answer": answer,
        "solution": solution,
        "solution_steps": list(steps),
        "translation": {
            "status": "machine",
            "model": model,
            "version": 1,
            "reviewed": False,
        },
    }
    return schema.parse_exercise(data)


def _check_target(exercise: schema.Exercise, target_lang: str) -> None:
    if target_lang not in LANGUAGES:
        raise TranslationError((f"unsupported_target:{target_lang}",))
    if target_lang == exercise.original_language:
        raise TranslationError(("target_equals_original",))
    if target_lang in exercise.content:
        raise TranslationError(("already_translated",))


def translate_exercise(
    exercise: schema.Exercise,
    target_lang: str,
    translator: Translator,
    *,
    model: str = "",
) -> schema.Exercise:
    """生成目标语言内容;失败抛 TranslationError,原对象不变。"""
    _check_target(exercise, target_lang)
    source = exercise.content[exercise.original_language]
    question = _translate_text(source.question, exercise.original_language, target_lang, translator)
    answer = _translate_text(source.answer, exercise.original_language, target_lang, translator)
    solution = _translate_text(source.solution, exercise.original_language, target_lang, translator)
    steps = tuple(
        _translate_text(step, exercise.original_language, target_lang, translator)
        for step in source.solution_steps
    )
    return _apply_translation(exercise, target_lang, question, answer, solution, steps, model)


async def _translate_text_async(
    text: str,
    source_lang: str,
    target_lang: str,
    translator: TranslatorAsync,
) -> str:
    template, placeholders = extract_math(text)
    translated_template = await translator(template, source_lang, target_lang)
    if not isinstance(translated_template, str):
        raise TranslationError(("translator_returned_non_string",))
    check = validate_translation(template, translated_template, placeholders, target_lang)
    if not check.ok:
        raise TranslationError(check.reasons)
    return restore_math(translated_template, placeholders)


async def translate_exercise_async(
    exercise: schema.Exercise,
    target_lang: str,
    translator: TranslatorAsync,
    *,
    model: str = "",
) -> schema.Exercise:
    _check_target(exercise, target_lang)
    source = exercise.content[exercise.original_language]
    question = await _translate_text_async(
        source.question, exercise.original_language, target_lang, translator
    )
    answer = await _translate_text_async(
        source.answer, exercise.original_language, target_lang, translator
    )
    solution = await _translate_text_async(
        source.solution, exercise.original_language, target_lang, translator
    )
    steps = tuple([
        await _translate_text_async(
            step, exercise.original_language, target_lang, translator
        )
        for step in source.solution_steps
    ])
    return _apply_translation(exercise, target_lang, question, answer, solution, steps, model)
