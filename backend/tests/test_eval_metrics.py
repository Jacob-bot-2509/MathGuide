"""评测指标单测:不联网、不调 LLM。"""
from __future__ import annotations

from evaluation.metrics import compute_metrics, wilson_ci


def test_wilson_ci_bounds_and_width():
    lo, hi = wilson_ci(50, 100)
    assert 0.39 < lo < 0.41
    assert 0.59 < hi < 0.61
    assert wilson_ci(0, 0) == (0.0, 1.0)


def test_metrics_accuracy_hallucination_retrieval():
    records = [
        {
            "id": "a", "domain": "导数", "difficulty": 1, "answer_type": "concept",
            "answerable": True, "gold_chunk_ids": ["c1"],
            "objective_correct": None,
            "retrieval": {"chunks": [{"id": "c1"}, {"id": "c2"}]},
            "judge": {
                "correct": True,
                "claims": [
                    {"text": "x", "supported": True},
                    {"text": "y", "supported": True},
                ],
            },
        },
        {
            "id": "b", "domain": "导数", "difficulty": 2, "answer_type": "concept",
            "answerable": True, "gold_chunk_ids": ["c9"],
            "objective_correct": None,
            "retrieval": {"chunks": [{"id": "c1"}]},
            "judge": {
                "correct": False,
                "claims": [
                    {"text": "u", "supported": False},
                    {"text": "v", "supported": True},
                ],
            },
        },
        {
            "id": "c", "domain": "不可答", "difficulty": 1, "answer_type": "unanswerable",
            "answerable": False, "gold_chunk_ids": [],
            "retrieval": {"chunks": []},
            "judge": {"correct": False, "refused": False, "claims": []},
        },
    ]
    s = compute_metrics(records)

    assert s["answers"]["n_judged_answerable"] == 2
    assert s["answers"]["accuracy"]["rate"] == 0.5
    assert s["answers"]["answer_hallucination"]["rate"] == 0.5
    assert s["answers"]["claim_hallucination"]["bad_claims"] == 1
    assert s["answers"]["claim_hallucination"]["total_claims"] == 4
    assert s["unanswerable"]["fabrication"]["rate"] == 1.0
    assert s["retrieval"]["n"] == 2
    assert s["retrieval"]["hit_rate"]["rate"] == 0.5
    assert s["retrieval"]["recall"] == 0.5
    assert round(s["retrieval"]["mrr"], 4) == 0.5
    assert s["by_domain"]["导数"]["n"] == 2


def test_unanswerable_correct_nonexistence_is_not_fabrication():
    """模型正确指出「不存在」但没用拒答措辞,不能算编造。"""
    records = [{
        "id": "u", "domain": "反例辨析", "difficulty": 3,
        "answer_type": "unanswerable", "answerable": False,
        "gold_chunk_ids": [], "retrieval": {"chunks": []},
        "judge": {"correct": True, "refused": False, "claims": []},
    }]
    s = compute_metrics(records)
    assert s["unanswerable"]["fabrication"]["rate"] == 0.0


def test_unanswerable_wrong_handling_is_fabrication():
    records = [{
        "id": "u", "domain": "反例辨析", "difficulty": 3,
        "answer_type": "unanswerable", "answerable": False,
        "gold_chunk_ids": [], "retrieval": {"chunks": []},
        "judge": {"correct": False, "refused": False, "claims": []},
    }]
    s = compute_metrics(records)
    assert s["unanswerable"]["fabrication"]["rate"] == 1.0
