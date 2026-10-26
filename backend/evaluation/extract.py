"""答案抽取与客观判分。

原则:能机器判的先用机器判;解析不确定时返回 None,交给 LLM 评审,
绝不因为解析失败直接判错(避免假阴性污染准确率)。
"""
from __future__ import annotations

import re

from .types import EvalItem

_BOXED_RE = re.compile(r"\\boxed\s*\{([^{}]+)\}")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
_ANSWER_CHOICE_RE = re.compile(
    r"(?:正确答案|答案)\s*(?:是|为)?\s*[:：]?\s*([A-Da-d])\b")
_SELECT_CHOICE_RE = re.compile(
    r"(?:应选|选择)\s*(?:是|为)?\s*[:：]?\s*([A-Da-d])\b")

try:  # sympy 是可选依赖:没装时表达式题自动降级给 LLM 评审
    import sympy as _sympy
except Exception:  # noqa: BLE001
    _sympy = None


def extract_boxed(text: str) -> str:
    matches = _BOXED_RE.findall(text)
    return matches[-1].strip() if matches else ""


def extract_numbers(text: str) -> list[float]:
    """按出现顺序返回所有数字(数值题用:答案里常夹带 2σ、区间端点等噪声)。"""
    nums: list[float] = []
    for raw in _NUMBER_RE.findall(text):
        try:
            nums.append(float(raw))
        except ValueError:
            continue
    return nums


def extract_number(text: str) -> float | None:
    boxed = extract_boxed(text)
    source = boxed or text
    nums = extract_numbers(source)
    return nums[-1] if nums else None


def extract_choice(text: str) -> str:
    # 只认显式作答。"选项 D（…）" 往往是选项说明,不能当答案(否则取到最后一个选项)。
    matches = _ANSWER_CHOICE_RE.findall(text)
    if matches:
        return matches[-1].upper()
    matches = _SELECT_CHOICE_RE.findall(text)
    if matches:
        return matches[-1].upper()
    stripped = text.strip()
    if re.fullmatch(r"[A-Da-d]", stripped):
        return stripped.upper()
    # 没有显式标记时不猜:宁可交给 LLM 评审,也不误判
    return ""


def _clean_expr(expr: str) -> str:
    expr = expr.strip().strip("$").strip()
    expr = expr.replace("\\left", "").replace("\\right", "")
    expr = expr.replace("\\,", "").replace("\\;", "").replace("\\!", "")
    expr = expr.replace("\\cdot", "*").replace("\\times", "*")
    expr = expr.replace("\\pi", "pi")
    expr = re.sub(r"\\frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}", r"((\1)/(\2))", expr)
    expr = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"sqrt(\1)", expr)
    expr = expr.replace("^", "**")
    return expr


def _sympy_equal(a: str, b: str) -> bool | None:
    if _sympy is None:
        return None
    try:
        left = _sympy.sympify(_clean_expr(a))
        right = _sympy.sympify(_clean_expr(b))
        return bool(_sympy.simplify(left - right) == 0)
    except Exception:  # noqa: BLE001 解析失败交给 LLM
        return None


def objective_check(item: EvalItem, answer: str) -> tuple[bool | None, str]:
    """返回 (是否正确, 判分说明)。None 表示无法客观判定。"""
    ref = item.reference_answer.strip()
    if not ref:
        return None, "无标准答案"

    if item.answer_type == "choice":
        got, want = extract_choice(answer), extract_choice(ref)
        if got and want:
            return got == want, f"choice: {got} vs {want}"
        return None, "选项无法解析"

    if item.answer_type == "numeric":
        want = extract_number(ref)
        # 不只看最后一个数字:答案里可能后出现 "2σ""区间端点" 等噪声。
        # 标准答案的数字出现在回答任意位置即判对;这偏宽松,但避免解析假阴性。
        nums = extract_numbers(extract_boxed(answer) or answer)
        if want is None or not nums:
            return None, "数值无法解析"
        scale = max(1.0, abs(want))
        matched = [n for n in nums if abs(n - want) <= 1e-6 * scale]
        return bool(matched), f"numeric: ref={want}, got={matched or nums[-1]}"

    if item.answer_type == "expr":
        got = extract_boxed(answer)
        want = extract_boxed(ref)
        if not got or not want:
            # 标准答案可能不带 boxed,退化为整段比较
            got = got or answer
            want = want or ref
        result = _sympy_equal(got, want)
        if result is None:
            return None, "表达式无法符号化"
        return result, f"expr: {_clean_expr(got)} vs {_clean_expr(want)}"

    return None, "主观题"
