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
# \begin{align*} / \end{align*} 的环境名不是正文;不去掉会被当成英文单词。
_ENV_RE = re.compile(r"\\(?:begin|end)\{[^}]*\}")

# 数字等价:只拒绝「源文数字丢失」,译文多出的释义数字不算改数;中文数词按等值
# 归一,否则 3-digit→三位数 会被误判。只收集后接量词/单位的中文数词,避免把
# 「一些」「一般」当成 1。
_CJK_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CJK_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}
_CJK_CLASSIFIERS = "个位种次名片堆倍成分之条张只本组对类步项元米秒年天度角边形维页章节题人户"
_CJK_NUM_RE = re.compile(
    r"[零〇一二两三四五六七八九十百千万亿]+(?=[" + _CJK_CLASSIFIERS + "])"
)
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


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


def _cjk_value(token: str) -> int:
    """把中文数词（十二、二十三、一百零五、一万二千）转成整数。"""
    total = 0
    section = 0
    number = 0
    for char in token:
        if char in _CJK_DIGITS:
            number = _CJK_DIGITS[char]
        else:
            unit = _CJK_UNITS[char]
            if unit >= 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
    return total + section + number


def _numbers(text: str) -> Counter[str]:
    """抽出文本中的数值;占位符里的公式不参与,全角数字与中文数词按等价值归一。"""
    value = _PLACEHOLDER_RE.sub("", text).translate(_FULLWIDTH_DIGITS)
    value = _CJK_NUM_RE.sub(lambda match: str(_cjk_value(match.group(0))), value)
    return Counter(_NUMBER_RE.findall(value))


def _prose(text: str) -> str:
    """去掉占位符、LaTeX 环境/命令与花括号,只留下自然语言。"""
    value = _PLACEHOLDER_RE.sub("", text)
    value = _ENV_RE.sub("", value)
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
    # 只查「源文数字丢失」:译文补充释义数字(quarter→25 美分)不算改数,
    # 但源文里的数一个都不能少,20 被改成 25 会因 20 缺失而拒绝。
    if _numbers(source) - _numbers(translated):
        reasons.append("number_mismatch")

    source_prose = _prose(source)
    # 至少两个英文单词或任意中文才算有正文:纯 LaTeX、单位标签(25 \text{ ft})
    # 不需要翻译,也不应因「没有目标语言」被拒。
    has_words = len(_LATIN_RE.findall(source_prose)) >= 2 or bool(_CJK_RE.search(source_prose))
    translated_prose = _prose(translated)
    if has_words:
        if target_lang == "zh" and not _CJK_RE.search(translated_prose):
            reasons.append("target_language_mismatch")
        if target_lang == "en" and not _LATIN_RE.search(translated_prose):
            reasons.append("target_language_mismatch")

    # 中文没有词间空格,按原始字符数比会系统性偏短;去掉空白再比。
    source_len = max(len(re.sub(r"\s+", "", source)), 1)
    ratio = len(re.sub(r"\s+", "", translated)) / source_len
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
