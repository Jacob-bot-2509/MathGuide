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
_DISPLAY_MATH_RE = re.compile(r"\$\$[\s\S]*?\$\$")
_ESCAPED_BRACE_RE = re.compile(r"\\[{}]")


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


def normalize(text: str) -> str:
    """比较答案/过程时忽略大小写、空白与数学定界符。"""
    value = _WS_RE.sub("", text.lower())
    for token in ("\\(", "\\)", "\\[", "\\]", "$"):
        value = value.replace(token, "")
    return value


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


def _contains_answer(answer: str, solution: str) -> bool:
    target = normalize(answer)
    haystack = normalize(solution)
    if not target:
        return False
    parts = [part for part in re.split(r"[,;，；]", target) if part]
    for part in parts:
        if part.isascii() and part.isdigit():
            pattern = rf"(?<![0-9]){re.escape(part)}(?![0-9])"
            if not re.search(pattern, haystack):
                return False
        elif part.isascii() and part.isalnum():
            pattern = rf"(?<![a-z0-9]){re.escape(part)}(?![a-z0-9])"
            if not re.search(pattern, haystack):
                return False
        elif part not in haystack:
            return False
    return True


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
