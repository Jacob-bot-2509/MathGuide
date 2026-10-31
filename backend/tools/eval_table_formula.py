"""数据表公式匹配金标准(离线,不调模型)。

用法(backend 目录下):
    python tools/eval_table_formula.py

指标:
    top1_target        Top-1 候选身份和目标列均正确
    mapping_correct    Top-1 变量映射与期望一致
    backcalc_pass      Top-1 反算全部通过
    no_candidate       空公式库不返回候选
    role_accuracy      列角色推断与期望一致

匹配、映射和反算只统计有候选公式的样本;空库单独计数。
这组手工合成样本仅用于回归,不能代表真实场景准确率。
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
        }, {
            "id": "f1-distractor", "target": "速度", "expr": "位移*时间",
            "variables": ["位移", "时间"],
            "variableMap": {"位移": "A", "时间": "B"},
            "units": {"位移": "m", "时间": "s", "速度": "m/s"},
        }],
        "candidate": "f1",
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
        "candidate": "f2",
        "target": "C",
        "mapping": {"质量": "A", "体积": "B"},
        "roles": {"A": "measured", "B": "measured", "C": "calculated"},
    },
    {
        "name": "功=力×距离",
        "table": {
            "columns": [
                {"key": "A", "label": "力", "type": "number", "unit": "N"},
                {"key": "B", "label": "距离", "type": "number", "unit": "m"},
                {"key": "C", "label": "功", "type": "number"},
            ],
            "rows": [["2", "3", "6"], ["4", "5", "20"]],
            "formulas": {"C": "=A2*B2"},
        },
        "saved": [{
            "id": "f3", "target": "功", "expr": "力*距离",
            "variables": ["力", "距离"],
            "variableMap": {"力": "A", "距离": "B"},
            "units": {"力": "N", "距离": "m", "功": "J"},
        }],
        "candidate": "f3",
        "target": "C",
        "mapping": {"力": "A", "距离": "B"},
        "roles": {"A": "measured", "B": "measured", "C": "calculated"},
    },
    {
        "name": "浓度=溶质/溶液",
        "table": {
            "columns": [
                {"key": "A", "label": "溶质质量", "type": "number", "unit": "g"},
                {"key": "B", "label": "溶液体积", "type": "number", "unit": "L"},
                {"key": "C", "label": "浓度", "type": "number"},
            ],
            "rows": [["10", "2", "5"], ["18", "3", "6"]],
            "formulas": {"C": "=A2/B2"},
        },
        "saved": [{
            "id": "f4", "target": "浓度", "expr": "溶质质量/溶液体积",
            "variables": ["溶质质量", "溶液体积"],
            "variableMap": {"溶质质量": "A", "溶液体积": "B"},
            "units": {"溶质质量": "g", "溶液体积": "L", "浓度": "g/L"},
        }],
        "candidate": "f4",
        "target": "C",
        "mapping": {"溶质质量": "A", "溶液体积": "B"},
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
    top1 = mapping = backcalc = roles = empty_ok = 0
    positive_total = empty_total = 0
    total = len(CASES)
    for case in CASES:
        table = case["table"]
        candidates = rt._match_formula_candidates(table, case["saved"])
        top = candidates[0] if candidates else None
        if case["saved"]:
            positive_total += 1
            target_ok = bool(top and top["formulaId"] == case["candidate"]
                             and top["columnKey"] == case["target"])
            mapping_ok = bool(top and top["mapping"] == case["mapping"])
            calc_ok = bool(top and top["validation"]
                           and top["validation"]["compared"] > 0
                           and top["validation"].get("unverified") == 0
                           and top["validation"].get("calculationErrors") == 0
                           and top["validation"]["matched"] == top["validation"]["compared"])
            top1 += int(target_ok)
            mapping += int(mapping_ok)
            backcalc += int(calc_ok)
            detail = f"target={target_ok} mapping={mapping_ok} backcalc={calc_ok}"
        else:
            empty_total += 1
            no_candidate = not candidates
            empty_ok += int(no_candidate)
            detail = f"no_candidate={no_candidate}"
        inferred = {c["key"]: c.get("role")
                    for c in rt._infer_roles(table["columns"], table["formulas"])}
        role_ok = all(inferred.get(k) == v for k, v in case["roles"].items())
        roles += int(role_ok)
        print(f"[{case['name']}] {detail} roles={role_ok}")
    print(f"top1={top1}/{positive_total} mapping={mapping}/{positive_total} "
          f"backcalc={backcalc}/{positive_total} no_candidate={empty_ok}/{empty_total} "
          f"roles={roles}/{total}")
    return 0 if (top1 == mapping == backcalc == positive_total
                 and empty_ok == empty_total and roles == total) else 1


if __name__ == "__main__":
    raise SystemExit(main())
