"""模块完整性:同一模块内不允许顶层函数/类重名覆盖。"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_duplicate_top_level_definitions():
    """后定义的同名函数会静默覆盖先定义(曾导致 get_doc/list_annotations
    助手被 HTTP 处理器覆盖)。这里把这类问题挡在测试阶段。"""
    problems: list[str] = []
    for path in sorted(ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: collections.Counter[str] = collections.Counter()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] += 1
        for name, count in names.items():
            if count > 1:
                problems.append(f"{path.name}:{name} x{count}")
    assert not problems, "顶层定义重名: " + ", ".join(problems)
