from evaluation.judges import _normalize
from evaluation.metrics import compute_metrics
from evaluation.report import write_outputs
from evaluation.types import EvalItem


def test_judge_claim_values_require_actual_booleans():
    item = EvalItem(id="x", question="q")
    data = {"claims": [
        {"text": "supported", "supported": True},
        {"text": "wrong", "supported": False},
        {"text": "unknown", "supported": None},
        {"text": "invalid", "supported": "false"},
    ]}
    result = _normalize(data, item)
    assert [c["supported"] for c in result["claims"]] == [True, False, None, None]
    assert result["claim_schema"] == "truth-v2"


def test_report_failures_follow_strict_accuracy(tmp_path):
    records = [
        {"id": "strict-correct", "question": "q", "objective_correct_strict": True, "objective_correct": False},
        {"id": "strict-wrong", "question": "q", "objective_correct_strict": False, "objective_correct": True,
         "objective_detail_strict": "strict failure"},
    ]
    _, _, path = write_outputs(tmp_path, records, compute_metrics(records), {})
    report = path.read_text(encoding="utf8")
    assert "strict-wrong" in report and "strict failure" in report
    assert "strict-correct" not in report


def test_unknown_and_legacy_claims_are_not_fabricated_or_silently_omitted(tmp_path):
    records = [
        {"id": "a", "question": "q", "judge": {"claim_schema": "truth-v2", "judge_role": "deep", "claims": [
            {"text": "verified", "supported": True}, {"text": "unknown", "supported": None}]}},
        {"id": "b", "question": "q", "judge": {"claim_schema": "truth-v2", "judge_role": "backup", "claims": [
            {"text": "wrong", "supported": False}, {"text": "unknown", "supported": None}]}},
        {"id": "c", "question": "q", "judge": {"claims": [{"text": "legacy unsupported", "supported": False}]}},
        {"id": "d", "question": "q", "judge": {"claim_schema": "truth-v2", "claims": [{"text": "verified", "supported": True}]}},
    ]
    summary = compute_metrics(records)
    claims = summary["answers"]["claim_hallucination"]
    assert (claims["bad_claims"], claims["total_claims"], claims["unknown_claims"]) == (1, 3, 3)
    assert claims["unknown_answers"] == 2
    assert summary["answers"]["answer_hallucination"]["k"] == 1
    assert summary["answers"]["answer_hallucination"]["n"] == 2
    assert summary["health"]["judge_roles"] == {"deep": 1, "backup": 1, "unknown": 2}
    _, _, path = write_outputs(tmp_path, records, summary, {"judge_role": "backup"})
    report = path.read_text(encoding="utf8")
    assert "未能判定的断言:3" in report
    assert "deep" in report and "独立性" in report
