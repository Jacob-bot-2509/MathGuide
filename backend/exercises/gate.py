"""三件套质量门:题干、答案、完整过程,以及 LaTeX/OCR/许可检查。

只校验原语种内容;译文完整性由 schema 保证,译文质量由翻译门单独处理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .schema import Exercise

GATE_VERSION = 1
MIN_QUESTION_CHARS = 20
MIN_SOLUTION_CHARS = 80
MIN_SOLUTION_STEPS = 3
MAX_REPLACEMENT_RATIO = 0.02

PROOF_MARKERS = frozenset({"证明见解析", "证毕", "qed", "proof", "证明成立"})
_WS_RE = re.compile(r"\s+")
_MATH_SPACE_RE = re.compile(r"\s*([=+\-*/^<>≤≥≠])\s*")
_DISPLAY_MATH_RE = re.compile(r"\$\$[\s\S]*?\$\$")
_ESCAPED_BRACE_RE = re.compile(r"\\[{}]")
_SIZING_RE = re.compile(r"\\(?:left|right|big|Big|bigg|Bigg)\b")
_SPACING_RE = re.compile(r"\\[,;! ]|\\quad\b|\\qquad\b")
_FRAC_RE = re.compile(r"\\[dt]frac\b")
_RELATION_RE = (
    (re.compile(r"\\(?:leq|le)\b"), "<="),
    (re.compile(r"\\(?:geq|ge)\b"), ">="),
    (re.compile(r"\\(?:neq|ne)\b"), "!="),
)
_WRAP_RE = re.compile(r"\\(?:mathrm|text)\{([^{}]*)\}")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?:\D|$))")


@dataclass(frozen=True)
class GateResult:
    accepted: bool
    reasons: tuple[str, ...]
    answer_in_solution: bool = False
    latex_ok: bool = True
    ocr_ok: bool = True

    def to_quality(self) -> dict[str, object]:
        return {
            "gate_version": GATE_VERSION,
            "answer_in_solution": self.answer_in_solution,
            "latex_ok": self.latex_ok,
            "ocr_ok": self.ocr_ok,
            "manual_review": "pending",
        }


def _clean_math(text: str) -> str:
    """消除排版差异:定界符、\\left/\\right、间距、分数命令、千分位。"""
    value = text.lower()
    for token in ("\\(", "\\)", "\\[", "\\]", "$"):
        value = value.replace(token, "")
    value = _SIZING_RE.sub("", value)
    value = _SPACING_RE.sub("", value)
    value = _FRAC_RE.sub(r"\\frac", value)
    for pattern, replacement in _RELATION_RE:
        value = pattern.sub(replacement, value)
    value = _WRAP_RE.sub(r"\1", value)
    value = _THOUSANDS_RE.sub("", value)
    return value


def normalize(text: str) -> str:
    """比较答案/过程时忽略大小写、空白与数学排版差异。"""
    return _WS_RE.sub("", _clean_math(text))


def normalize_boundary(text: str) -> str:
    """保留词间空格,只压掉数学运算符两侧空白,供边界匹配使用。"""
    value = _clean_math(text)
    value = _MATH_SPACE_RE.sub(r"\1", value)
    return _WS_RE.sub(" ", value).strip()


def latex_balanced(text: str) -> bool:
    """检查常见 LaTeX 定界符与花括号是否成对。"""
    if text.count("$$") % 2:
        return False
    without_display = _DISPLAY_MATH_RE.sub("", text)
    if without_display.count("$") % 2:
        return False
    if text.count("\\(") != text.count("\\)"):
        return False
    if text.count("\\[") != text.count("\\]"):
        return False
    without_escaped = _ESCAPED_BRACE_RE.sub("", text)
    if without_escaped.count("{") != without_escaped.count("}"):
        return False
    if without_escaped.count("\\begin{") != without_escaped.count("\\end{"):
        return False
    return True


def ocr_ok(text: str) -> bool:
    """替换符比例过高视为 OCR/编码损坏。"""
    if not text:
        return True
    return text.count("�") / len(text) <= MAX_REPLACEMENT_RATIO


def _answer_pattern(part: str) -> str:
    body = r"\s*".join(re.escape(char) for char in part)
    if part.isascii() and part.isdigit():
        return rf"(?<![0-9]){body}(?![0-9])"
    prefix = r"(?<![a-z0-9])" if part[0].isascii() and part[0].isalnum() else ""
    suffix = r"(?![a-z0-9])" if part[-1].isascii() and part[-1].isalnum() else ""
    return prefix + body + suffix


def _contains_answer(answer: str, solution: str) -> bool:
    target = normalize(answer)
    haystack = normalize_boundary(solution)
    if not target:
        return False
    parts = [part for part in re.split(r"[,;，；\n]|\bor\b|或", target) if part]
    return all(re.search(_answer_pattern(part), haystack) for part in parts)


def answer_in_solution(exercise: Exercise, solution: str) -> bool:
    answer = exercise.content[exercise.original_language].answer
    if exercise.type == "proof" and normalize(answer) in PROOF_MARKERS:
        steps = exercise.content[exercise.original_language].solution_steps
        return len(solution) >= 2 * MIN_SOLUTION_CHARS or len(steps) >= MIN_SOLUTION_STEPS
    return _contains_answer(answer, solution)


def gate_exercise(exercise: Exercise) -> GateResult:
    """按固定顺序检查;失败原因写入 reasons,便于导入统计。"""
    content = exercise.content[exercise.original_language]
    question = content.question.strip()
    answer = content.answer.strip()
    solution = content.solution.strip()

    reasons: list[str] = []
    if len(question) < MIN_QUESTION_CHARS:
        reasons.append("question_too_short")
    if not answer:
        reasons.append("answer_missing")
    if len(solution) < MIN_SOLUTION_CHARS and len(content.solution_steps) < MIN_SOLUTION_STEPS:
        reasons.append("solution_too_short")
    if normalize(answer) and normalize(answer) == normalize(solution):
        reasons.append("solution_equals_answer")

    in_solution = answer_in_solution(exercise, solution)
    if answer and not in_solution:
        reasons.append("answer_not_in_solution")

    latex_ok = latex_balanced(question + "\n" + answer + "\n" + solution)
    if not latex_ok:
        reasons.append("latex_unbalanced")

    ocr_clean = ocr_ok(question + "\n" + answer + "\n" + solution)
    if not ocr_clean:
        reasons.append("ocr_noise")

    if not (exercise.source.name and exercise.source.license
            and exercise.source.url and exercise.source.attribution):
        reasons.append("license_incomplete")
    if exercise.source.tier == "blocked":
        reasons.append("blocked_source")
    if exercise.quality.get("manual_review") == "rejected":
        reasons.append("manual_rejected")

    return GateResult(
        accepted=not reasons,
        reasons=tuple(reasons),
        answer_in_solution=in_solution,
        latex_ok=latex_ok,
        ocr_ok=ocr_clean,
    )
