"""答案抽取与客观判分。

原则:能机器判的先用机器判;解析不确定时返回 None,交给 LLM 评审,
绝不因为解析失败直接判错(避免假阴性污染准确率)。
"""
from __future__ import annotations

import re

from .types import EvalItem

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
    result = ""
    for match in re.finditer(r"\\boxed\s*\{", text):
        result = ""
        depth = 1
        pos = match.end()
        while pos < len(text) and depth:
            if text[pos] == "\\" and pos + 1 < len(text) and text[pos + 1] in "{}":
                pos += 2
                continue
            depth += (text[pos] == "{") - (text[pos] == "}")
            pos += 1
        if depth == 0:
            result = text[match.end():pos - 1].strip()
    return result


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


def _strict_scalar(value: str) -> float | None:
    """Parse a complete numeric value without treating a fraction's denominator as its answer."""
    import math

    value = value.strip().strip("$").strip()
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    frac = re.fullmatch(rf"([+-]?)\\(?:d|t)?frac\s*\{{\s*({number})\s*\}}\s*\{{\s*({number})\s*\}}", value)
    slash = re.fullmatch(rf"({number})\s*/\s*({number})", value)
    try:
        if frac:
            result = float(frac.group(2)) / float(frac.group(3))
            if frac.group(1) == "-":
                result = -result
        elif slash:
            result = float(slash.group(1)) / float(slash.group(2))
        elif re.fullmatch(number, value):
            result = float(value)
        else:
            return None
        return result if math.isfinite(result) else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def objective_check(item: EvalItem, answer: str,
                    strict: bool = False) -> tuple[bool | None, str]:
    """返回 (是否正确, 判分说明)。None 表示无法客观判定。

    strict=True 用于评测口径:数值题只认 \boxed{} 或最后一个数字,
    避免「回答任意位置出现标准数字」把错误答案判对。默认 False 保持旧行为。
    """
    ref = item.reference_answer.strip()
    if not ref:
        return None, "无标准答案"

    if item.answer_type == "choice":
        got, want = extract_choice(answer), extract_choice(ref)
        if got and want:
            return got == want, f"choice: {got} vs {want}"
        return None, "选项无法解析"

    if item.answer_type == "numeric":
        if strict:
            want = _strict_scalar(extract_boxed(ref) or ref)
            boxed = extract_boxed(answer)
            if boxed:
                got = _strict_scalar(boxed)
            elif r"\boxed" in answer:
                got = None
            elif re.search(r"\\(?:d|t)?frac\b|\d\s*/\s*\d", answer):
                got = _strict_scalar(answer)
            else:
                got = extract_number(answer)
            if want is None or got is None:
                return None, "数值无法可靠解析"
            approximate = any(marker in ref or marker in answer for marker in ("约", "大约", "≈", "~"))
            tolerance = (0.01 if approximate else 1e-6) * max(1.0, abs(want))
            return abs(got - want) <= tolerance, f"numeric-strict: ref={want}, got={got}"
        want = extract_number(ref)
        # 不只看最后一个数字:答案里可能后出现 "2σ""区间端点" 等噪声。
        # 标准答案的数字出现在回答任意位置即判对;这偏宽松,但避免解析假阴性。
        nums = extract_numbers(extract_boxed(answer) or answer)
        if want is None or not nums:
            return None, "数值无法解析"
        scale = max(1.0, abs(want))
        # 参考答案或回答明确写「约/≈」时按近似值处理(1%),否则只认精确值
        approximate = any(marker in ref or marker in answer
                          for marker in ("约", "大约", "≈", "~"))
        tolerance = (0.01 if approximate else 1e-6) * scale
        matched = [n for n in nums if abs(n - want) <= tolerance]
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
