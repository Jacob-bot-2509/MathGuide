"""指标计算:准确率、幻觉率、检索命中/召回、Wilson 置信区间。

口径:
- accuracy       = 判为正确的可答题 / 已判可答题
- answer_halluc  = 至少 1 条明确错误或编造断言的回答 / 可判定的回答
- claim_halluc   = 明确错误或编造断言数 / 可判定断言数
- fabrication    = 不可答题中未拒答的比例
- hit@k          = top-k 命中任一金标片段的问题比例
- recall@k       = top-k 命中的金标片段数 / 金标片段总数(按题平均)
- mrr@k          = 首个金标片段排名的倒数(按题平均)
"""
from __future__ import annotations

import math


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """二项比例的 Wilson 95% 置信区间。n=0 时返回 (0,1)。"""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _rate(k: int, n: int) -> dict:
    lo, hi = wilson_ci(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def _answer_correct(record: dict) -> bool | None:
    """严格口径不可解析时交给评审,旧记录保留原有口径。"""
    if "objective_correct_strict" in record:
        strict = record["objective_correct_strict"]
        if isinstance(strict, bool):
            return strict
        correct = (record.get("judge") or {}).get("correct")
        return correct if isinstance(correct, bool) else None
    if "objective_correct" in record and record["objective_correct"] is not None:
        return bool(record["objective_correct"])
    judge = record.get("judge") or {}
    correct = judge.get("correct")
    return bool(correct) if isinstance(correct, bool) else None


def _answer_correct_lenient(record: dict) -> bool | None:
    """宽松口径:旧 numeric 规则(回答任意位置出现标准数字即算对)。"""
    if record.get("objective_correct") is not None:
        return bool(record["objective_correct"])
    return _answer_correct(record)


def _claim_states(record: dict) -> list[bool | None]:
    judge = record.get("judge") or {}
    claims = judge.get("claims") or []
    if not isinstance(claims, list):
        return []
    states = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        value = claim.get("supported")
        if value is True:
            states.append(True)
        elif value is False and judge.get("claim_schema") == "truth-v2":
            states.append(False)
        else:
            # Legacy false meant unsupported, which is not necessarily false.
            states.append(None)
    return states


def _claim_verdict(record: dict) -> bool | None:
    states = _claim_states(record)
    if any(state is False for state in states):
        return False
    if states and all(state is True for state in states):
        return True
    return None


def retrieval_metrics(records: list[dict]) -> dict:
    with_gold = [r for r in records if r.get("gold_chunk_ids")]
    if not with_gold:
        return {"n": 0, "hit_rate": None, "recall": None, "mrr": None}
    hits = 0
    recalls: list[float] = []
    rrs: list[float] = []
    for r in with_gold:
        gold = set(r["gold_chunk_ids"])
        ids = [c.get("id") for c in (r.get("retrieval") or {}).get("chunks", [])]
        rank = next((i + 1 for i, cid in enumerate(ids) if cid in gold), None)
        hits += 1 if rank else 0
        recalls.append(len(gold & set(ids)) / len(gold) if gold else 0.0)
        rrs.append(1.0 / rank if rank else 0.0)
    n = len(with_gold)
    return {
        "n": n,
        "hit_rate": _rate(hits, n),
        "recall": round(sum(recalls) / n, 4),
        "mrr": round(sum(rrs) / n, 4),
    }


def compute_metrics(records: list[dict]) -> dict:
    answerable = [r for r in records if r.get("answerable", True) and _answer_correct(r) is not None]
    correct = [r for r in answerable if _answer_correct(r)]
    lenient_answerable = [
        r for r in records
        if r.get("answerable", True) and _answer_correct_lenient(r) is not None
    ]
    lenient_correct = [r for r in lenient_answerable if _answer_correct_lenient(r)]
    claim_records = [r for r in records if r.get("answerable", True) and _claim_states(r)]
    judged = [r for r in claim_records if _claim_verdict(r) is not None]
    halluc_answers = [r for r in judged if _claim_verdict(r) is False]
    states = [state for r in claim_records for state in _claim_states(r)]
    total_claims = sum(state is not None for state in states)
    bad_claims = sum(state is False for state in states)
    unknown_claims = sum(state is None for state in states)
    unknown_answers = sum(_claim_verdict(r) is None for r in claim_records)

    unanswerable = [r for r in records if not r.get("answerable", True)]
    judged_unanswerable = [
        r for r in unanswerable
        if (r.get("judge") and not r["judge"].get("error"))
        or r.get("objective_correct") is not None
    ]
    fabricated = []
    for r in judged_unanswerable:
        judge = r.get("judge") or {}
        judge_correct = judge.get("correct")
        if isinstance(judge_correct, bool):
            # 不可答题的 correct 表示「是否恰当处理」(拒答/声明不存在/指出矛盾)
            if not judge_correct:
                fabricated.append(r)
            continue
        refused = judge.get("refused")
        if isinstance(refused, bool):
            if not refused:
                fabricated.append(r)
        elif _answer_correct(r) is True:
            # 不可答题里 judge 判 correct 且没有 refused 字段:按未拒答处理
            fabricated.append(r)

    judged_all = [r for r in records if r.get("judge") and not (r["judge"].get("error"))]
    judge_roles = {}
    for record in judged_all:
        role = str(record["judge"].get("judge_role") or "unknown")
        judge_roles[role] = judge_roles.get(role, 0) + 1
    run_errors = [r for r in records if r.get("error")]
    judge_errors = [r for r in records if (r.get("judge") or {}).get("error")]
    degraded = [r for r in records if r.get("degraded")]

    summary = {
        "n_items": len(records),
        "retrieval": retrieval_metrics(records),
        "answers": {
            "n_judged_answerable": len(answerable),
            "accuracy": _rate(len(correct), len(answerable)),
            "accuracy_lenient": _rate(len(lenient_correct), len(lenient_answerable)),
            "n_judged_claims": len(judged),
            "answer_hallucination": _rate(len(halluc_answers), len(judged)),
            "claim_hallucination": {
                "bad_claims": bad_claims,
                "total_claims": total_claims,
                "unknown_claims": unknown_claims,
                "unknown_answers": unknown_answers,
                "rate": (bad_claims / total_claims) if total_claims else None,
            },
        },
        "unanswerable": {
            "n": len(judged_unanswerable),
            "fabrication": _rate(len(fabricated), len(judged_unanswerable)),
        },
        "health": {
            "run_errors": len(run_errors),
            "judge_errors": len(judge_errors),
            "judged": len(judged_all),
            "judge_roles": judge_roles,
            "degraded": len(degraded),
            "degraded_rate": (len(degraded) / len(records)) if records else None,
        },
    }
    summary["by_domain"] = _group(records, "domain")
    summary["by_difficulty"] = _group(records, "difficulty")
    summary["by_answer_type"] = _group(records, "answer_type")
    return summary


def _group(records: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(str(r.get(key, "other")), []).append(r)
    out: dict[str, dict] = {}
    for name, rows in sorted(groups.items()):
        answerable = [r for r in rows if r.get("answerable", True) and _answer_correct(r) is not None]
        correct = [r for r in answerable if _answer_correct(r)]
        lenient_answerable = [
            r for r in rows
            if r.get("answerable", True) and _answer_correct_lenient(r) is not None
        ]
        lenient_correct = [r for r in lenient_answerable if _answer_correct_lenient(r)]
        judged = [r for r in rows if r.get("answerable", True) and _claim_verdict(r) is not None]
        halluc = [r for r in judged if _claim_verdict(r) is False]
        out[name] = {
            "n": len(rows),
            "accuracy": _rate(len(correct), len(answerable)),
            "accuracy_lenient": _rate(len(lenient_correct), len(lenient_answerable)),
            "answer_hallucination": _rate(len(halluc), len(judged)),
        }
    return out
