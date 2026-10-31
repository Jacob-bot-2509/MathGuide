"""数据表公式匹配金标准(离线,不调模型)。

用法(backend 目录下):
    python tools/eval_table_formula.py

指标:
    top1_target        Top-1 候选命中目标列
    mapping_correct    Top-1 变量映射与期望一致
    backcalc_pass      Top-1 反算全部通过
    role_accuracy      列角色推断与期望一致

通过线:全部 100%;新增真实样本时先跑此脚本再改算法。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research_tables as rt  # noqa: E402

CASES = [
    {
        "name": "速度=位移/时间",
        "table": {
            "columns": [
                {"key": "A", "label": "位移", "type": "number", "unit": "m"},
                {"key": "B", "label": "时间", "type": "number", "unit": "s"},
                {"key": "C", "label": "速度", "type": "number"},
            ],
            "rows": [["1", "2", "0.5"], ["3", "4", "0.75"]],
            "formulas": {"C": "=A2/B2"},
        },
        "saved": [{
            "id": "f1", "target": "速度", "expr": "位移/时间",
            "variables": ["位移", "时间"],
            "variableMap": {"位移": "A", "时间": "B"},
            "units": {"位移": "m", "时间": "s", "速度": "m/s"},
        }],
        "target": "C",
        "mapping": {"位移": "A", "时间": "B"},
        "roles": {"A": "measured", "B": "measured", "C": "calculated"},
    },
    {
        "name": "密度=质量/体积",
        "table": {
            "columns": [
                {"key": "A", "label": "质量", "type": "number", "unit": "g"},
                {"key": "B", "label": "体积", "type": "number", "unit": "cm3"},
                {"key": "C", "label": "密度", "type": "number"},
            ],
            "rows": [["10", "2", "5"], ["20", "4", "5"]],
            "formulas": {"C": "=A2/B2"},
        },
        "saved": [{
            "id": "f2", "target": "密度", "expr": "质量/体积",
            "variables": ["质量", "体积"],
            "variableMap": {"质量": "A", "体积": "B"},
            "units": {"质量": "g", "体积": "cm3", "密度": "g/cm3"},
        }],
        "target": "C",
        "mapping": {"质量": "A", "体积": "B"},
        "roles": {"A": "measured", "B": "measured", "C": "calculated"},
    },
    {
        "name": "编号列识别",
        "table": {
            "columns": [
                {"key": "A", "label": "样本编号", "type": "text"},
                {"key": "B", "label": "位移", "type": "number", "unit": "m"},
                {"key": "C", "label": "时间", "type": "number", "unit": "s"},
                {"key": "D", "label": "速度", "type": "number"},
            ],
            "rows": [["s1", "1", "2", "0.5"], ["s2", "3", "4", "0.75"]],
            "formulas": {"D": "=B2/C2"},
        },
        "saved": [],
        "target": "",
        "mapping": {},
        "roles": {"A": "identifier", "B": "measured", "C": "measured", "D": "calculated"},
    },
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    top1 = mapping = backcalc = roles = 0
    total = len(CASES)
    for case in CASES:
        table = case["table"]
        candidates = rt._match_formula_candidates(table, case["saved"])
        top = candidates[0] if candidates else None
        expect_candidate = bool(case["saved"])
        target_ok = (not expect_candidate) or bool(top and top["columnKey"] == case["target"])
        mapping_ok = (not expect_candidate) or bool(top and top["mapping"] == case["mapping"])
        calc_ok = (not expect_candidate) or bool(
            top and top["validation"]
            and top["validation"]["compared"] > 0
            and top["validation"]["matched"] == top["validation"]["compared"])
        inferred = {c["key"]: c.get("role")
                    for c in rt._infer_roles(table["columns"], table["formulas"])}
        role_ok = all(inferred.get(k) == v for k, v in case["roles"].items())
        top1 += int(target_ok)
        mapping += int(mapping_ok)
        backcalc += int(calc_ok)
        roles += int(role_ok)
        print(f"[{case['name']}] target={target_ok} mapping={mapping_ok} "
              f"backcalc={calc_ok} roles={role_ok}")
    print(f"top1={top1}/{total} mapping={mapping}/{total} "
          f"backcalc={backcalc}/{total} roles={roles}/{total}")
    return 0 if all(x == total for x in (top1, mapping, backcalc, roles)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
