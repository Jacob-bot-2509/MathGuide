"""Evidence-based repairs applied on read; original source records remain intact."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


# For f(x)=2x^3-3x, f'(x_0)=6x_0^2-3. Substitution into the tangent
# equation gives 4x_0^3-6x_0^2+t+3=0. The upstream transcription lost ^.
_TANGENT_REPAIRS = (
    ("y-y\u2092=(6x_2_0-3)(x-x\u2092)", "y-y_0=(6x_0^2-3)(x-x_0)"),
    ("t-y\u2092=(6x_2_0-3)(1-x\u2092)", "t-y_0=(6x_0^2-3)(1-x_0)"),
    ("4x_3_0-6x_2_0+t+3=0", "4x_0^3-6x_0^2+t+3=0"),
)


def repair_source(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    if value.get("id") != "olympiadbench:OE_TO_maths_zh_CEE:3163":
        return value
    source = value.get("source")
    content = value.get("content")
    if not isinstance(source, Mapping) or source.get("name") != "OlympiadBench" or not isinstance(content, Mapping):
        return value
    repaired_content = dict(content)
    changed = False
    for language, block in content.items():
        if not isinstance(block, Mapping):
            continue
        question, solution = block.get("question"), block.get("solution")
        if not isinstance(question, str) or "f(x)=2x^3-3x" not in question or not isinstance(solution, str):
            continue
        if not all(old in solution for old, _ in _TANGENT_REPAIRS):
            continue
        for old, new in _TANGENT_REPAIRS:
            solution = solution.replace(old, new)
        repaired_content[language] = {**block, "solution": solution}
        changed = True
    return {**value, "content": repaired_content} if changed else value
