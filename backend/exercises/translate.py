"""双语翻译:公式占位、数字/占位符校验、译文写回。"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from . import schema
from .gate import latex_balanced

LANGUAGES = ("zh", "en")
Translator = Callable[[str, str, str], str]
TranslatorAsync = Callable[[str, str, str], Awaitable[str]]

_MATH_RE = re.compile(
    r"(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$)"
)
# 环境块与 $...$ 必须一次匹配:分两遍会在 $...\begin...\end...$ 里嵌套占位符,
# 还原后留下 [[M1]] 字面量。
_MATH_BLOCK_RE = re.compile(
    r"(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]+?\$"
    r"|\\begin\{([A-Za-z*]+)\}[\s\S]+?\\end\{\2\})"
)
_PLACEHOLDER_RE = re.compile(r"\[\[M\d+\]\]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_CJK_RE = re.compile(r"[㐀-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")
_COMMAND_RE = re.compile(r"\\[A-Za-z]+")
# 连续三个以上、只用空格分隔的英文单词才像句子。公式清洗后剩下的变量名
# (mn_max、ge^-16)不算,避免把纯 LaTeX 当成未翻译的正文。
_PROSE_RUN_RE = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,}){2,}")
_LATIN_RUN_RE = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,}){4,}")
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
_CJK_CLASSIFIERS = "个位种次名片堆倍成分之条张只本组对类步项元米秒年天度角边形维页章节题人户进"
_CJK_NUM_RE = re.compile(
    r"[零〇一二两三四五六七八九十百千万亿]+(?=[" + _CJK_CLASSIFIERS + "])"
)
_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")
# 数学片段已整体换成占位符,译文模板里再出现这些定界符就是模型自己加的。
_STRAY_MATH_RE = re.compile(r"(?<!\\)\$|\\\(|\\\[|\\begin\{")
_LEAK_RE = re.compile(
    r"请提供需要翻译|保留源文本的换行|保留原文的换行|直接输出翻译结果|"
    r"将(?:上面|上述)的?文本翻译|line\s+breaks\s+and\s+format|"
    r"output\s+the\s+translation\s+result",
    re.I,
)


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

    value = _MATH_BLOCK_RE.sub(replace, text)
    return value, tuple(placeholders)


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
    # Markdown/编号列表的 "1." "2)" 是序号不是题面数据,译文常改写成中文序号。
    value = re.sub(r"(?m)^\s*\d+[.)]\s+", " ", value)
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
    if _STRAY_MATH_RE.search(translated):
        reasons.append("stray_math_delimiter")
    if _LEAK_RE.search(translated):
        reasons.append("prompt_leak")
    if not latex_balanced(translated):
        reasons.append("unbalanced_latex")

    source_prose = _prose(source)
    # 连续三个空格分隔的英文单词、或任意中文,才算有需要翻译的正文。
    has_words = bool(_PROSE_RUN_RE.search(source_prose) or _CJK_RE.search(source_prose))
    translated_prose = _prose(translated)
    if target_lang == "zh" and _LATIN_RUN_RE.search(translated_prose):
        reasons.append("untranslated_prose")
    if target_lang == "en" and len(_CJK_RE.findall(translated_prose)) >= 10:
        reasons.append("residual_chinese")
    if has_words:
        if target_lang == "zh" and not _CJK_RE.search(translated_prose):
            reasons.append("target_language_mismatch")
        if target_lang == "en" and not _LATIN_RE.search(translated_prose):
            reasons.append("target_language_mismatch")

    # 长度比只看正文:LaTeX 命令、公式、占位符不计长度。中文没有词间空格,
    # 按原始字符数比会系统性偏短;去掉空白再比,阈值也按正文定。
    source_len = max(len(re.sub(r"\s+", "", source_prose)), 1)
    translated_len = len(re.sub(r"\s+", "", translated_prose))
    ratio = translated_len / source_len
    # 中文译文篇幅天然只有英文原文的 0.2~0.4,下限按目标语言区分。
    lower = 0.15 if target_lang == "zh" else 0.25
    if source_len >= 10 and (ratio < lower or ratio > 4.0):
        reasons.append("length_ratio_out_of_range")
    return TranslationCheck(ok=not reasons, reasons=tuple(reasons))


def _prose_in_math(text: str) -> bool:
    """中文题干被整段包在 $...$ 里时,公式占位会吞掉正文。"""
    template, _ = extract_math(text)
    if not _CJK_RE.search(text):
        return False
    return not _CJK_RE.search(_prose(template))


def _cjk_in_math(text: str) -> bool:
    """公式片段里藏着成段中文(整段被 $...$ 包住,但外面还有少量中文)。"""
    _, placeholders = extract_math(text)
    return any(len(_CJK_RE.findall(segment)) >= 3 for segment in placeholders)


def _needs_raw_translation(text: str, target_lang: str) -> bool:
    return target_lang == "en" and (_prose_in_math(text) or _cjk_in_math(text))


def _mostly_cjk(text: str) -> bool:
    cjk = len(_CJK_RE.findall(text))
    return cjk >= 5 and cjk >= len(text) * 0.2


def validate_prose_math(source: str, translated: str, target_lang: str) -> TranslationCheck:
    """校验“正文包在公式里”的译文:数字和 LaTeX 命令不能丢,不能残留中文。"""
    reasons: list[str] = []
    if _numbers(source) - _numbers(translated):
        reasons.append("number_mismatch")
    missing_commands = Counter(_COMMAND_RE.findall(source)) - Counter(
        _COMMAND_RE.findall(translated)
    )
    if missing_commands:
        reasons.append("command_mismatch")
    if not latex_balanced(translated):
        reasons.append("unbalanced_latex")
    if _LEAK_RE.search(translated):
        reasons.append("prompt_leak")
    if target_lang == "en":
        if not _PROSE_RUN_RE.search(_prose(translated)):
            reasons.append("target_language_mismatch")
        if len(_CJK_RE.findall(translated)) >= 4:
            reasons.append("residual_chinese")
    source_len = max(len(re.sub(r"\s+", "", source)), 1)
    ratio = len(re.sub(r"\s+", "", translated)) / source_len
    if source_len >= 10 and (ratio < 0.5 or ratio > 3.0):
        reasons.append("length_ratio_out_of_range")
    return TranslationCheck(ok=not reasons, reasons=tuple(reasons))


async def _translate_prose_math_async(text, source_lang, target_lang, translator):
    translated = await translator(text, source_lang, target_lang)
    if not isinstance(translated, str):
        raise TranslationError(("translator_returned_non_string",))
    check = validate_prose_math(text, translated, target_lang)
    if not check.ok:
        raise TranslationError(check.reasons)
    return translated.strip()


def _translate_prose_math(text, source_lang, target_lang, translator):
    translated = translator(text, source_lang, target_lang)
    if not isinstance(translated, str):
        raise TranslationError(("translator_returned_non_string",))
    check = validate_prose_math(text, translated, target_lang)
    if not check.ok:
        raise TranslationError(check.reasons)
    return translated.strip()


async def _translate_field_async(text, source_lang, target_lang, translator):
    if _needs_raw_translation(text, target_lang):
        return await _translate_prose_math_async(text, source_lang, target_lang, translator)
    return await _translate_text_async(text, source_lang, target_lang, translator)


def _translate_field(text, source_lang, target_lang, translator):
    if _needs_raw_translation(text, target_lang):
        return _translate_prose_math(text, source_lang, target_lang, translator)
    return _translate_text(text, source_lang, target_lang, translator)


def _answer_needs_translation(answer: str) -> bool:
    """选项字母、单个变量、纯公式不翻译;只翻译有自然语言的答案。

    否则 A→「一个」、B→「乙」、ABD→「安韵」这类误译会直接毁掉判分。
    """
    prose = _prose(answer).strip()
    if not prose:
        return False
    if re.fullmatch(r"[A-Ea-e]{1,5}", prose):
        return False
    if re.fullmatch(r"[A-Za-z]", prose):
        return False
    if _CJK_RE.search(prose):
        return True
    return len(_LATIN_RE.findall(prose)) >= 2


def _strip_stray_math(text: str) -> str:
    """译文模板里的数学定界符是模型自己加的;数学已在占位符里,直接剥掉。"""
    value = re.sub(r"(?<!\\)\$", "", text)
    value = re.sub(r"\\[()\[\]]", "", value)
    return re.sub(r"\\(?:begin|end)\{[A-Za-z*]+\}", "", value)


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
    translated_template = _strip_stray_math(translated_template)
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
    question = _translate_field(source.question, exercise.original_language, target_lang, translator)
    answer = (
        _translate_field(source.answer, exercise.original_language, target_lang, translator)
        if _answer_needs_translation(source.answer)
        else source.answer
    )
    solution = _translate_field(source.solution, exercise.original_language, target_lang, translator)
    steps = tuple(
        _translate_field(step, exercise.original_language, target_lang, translator)
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
    translated_template = _strip_stray_math(translated_template)
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
    question = await _translate_field_async(
        source.question, exercise.original_language, target_lang, translator
    )
    answer = (
        await _translate_field_async(
            source.answer, exercise.original_language, target_lang, translator
        )
        if _answer_needs_translation(source.answer)
        else source.answer
    )
    solution = await _translate_field_async(
        source.solution, exercise.original_language, target_lang, translator
    )
    steps = tuple([
        await _translate_field_async(
            step, exercise.original_language, target_lang, translator
        )
        for step in source.solution_steps
    ])
    return _apply_translation(exercise, target_lang, question, answer, solution, steps, model)
