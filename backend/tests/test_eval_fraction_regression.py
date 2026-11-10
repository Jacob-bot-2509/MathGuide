from evaluation.extract import extract_boxed, objective_check
from evaluation.types import EvalItem


def test_strict_numeric_handles_nested_boxed_fraction_without_guessing():
    item = EvalItem(id="fraction", question="q", reference_answer="0.5", answer_type="numeric")
    answer = r"\boxed{\frac{1}{2}}"
    assert extract_boxed(answer) == r"\frac{1}{2}"
    assert objective_check(item, answer, strict=True)[0] is True
    item.reference_answer = "2"
    assert objective_check(item, answer, strict=True)[0] is False
    assert objective_check(item, r"\boxed{\sqrt{2}}", strict=True)[0] is None
    assert objective_check(item, r"\boxed{\frac{1}{0}}", strict=True)[0] is None
    assert objective_check(item, r"\boxed{2} then \boxed{", strict=True)[0] is None


def test_strict_metrics_do_not_silently_fall_back_to_lenient_result():
    from evaluation.metrics import _answer_correct, _answer_correct_lenient

    record = {"objective_correct_strict": None, "objective_correct": True, "judge": {"correct": False}}
    assert _answer_correct(record) is False
    assert _answer_correct_lenient(record) is True
    record["judge"] = {}
    assert _answer_correct(record) is None
    assert _answer_correct({"objective_correct": True}) is True


def test_nested_boxed_expression_is_compared_as_an_expression():
    item = EvalItem(id="expr", question="q", reference_answer=r"\frac{1}{2}", answer_type="expr")
    assert objective_check(item, r"\boxed{\frac{1}{2}}")[0] is True
