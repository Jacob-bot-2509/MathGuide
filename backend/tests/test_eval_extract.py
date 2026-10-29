"""答案抽取与数据集加载单测。"""
from __future__ import annotations

import json

import pytest

from evaluation.datasets import dataset_hash, load_items
from evaluation.extract import extract_choice, extract_number, objective_check
from evaluation.types import EvalItem


def test_extract_number_prefers_boxed():
    assert extract_number("过程略，最终 \\boxed{42}") == 42.0
    assert extract_number("答案是 3.5") == 3.5
    assert extract_number("没有数字") is None


def test_extract_choice():
    assert extract_choice("答案是 B") == "B"
    assert extract_choice("应选：C") == "C"
    assert extract_choice("正确答案是：B") == "B"
    # 选项列表在后:必须取显式作答的 B,不能取后面的 "选项 D"
    assert extract_choice("答案：B\n……\n选项 D（曲线的长度）") == "B"
    assert extract_choice("无关文本") == ""


def test_objective_numeric_and_choice():
    item = EvalItem(id="n", question="q", reference_answer="9", answer_type="numeric")
    assert objective_check(item, "所以结果是 9。")[0] is True
    assert objective_check(item, "所以结果是 8。")[0] is False
    # 答案夹带 2σ 等噪声时,不能只看最后一个数字
    item = EvalItem(id="p", question="q", reference_answer="95", answer_type="numeric")
    assert objective_check(item, "约 95%,即 μ±2σ 范围内")[0] is True

    item = EvalItem(id="c", question="q", reference_answer="B", answer_type="choice")
    assert objective_check(item, "答案：B")[0] is True
    assert objective_check(item, "答案：A")[0] is False


def test_objective_numeric_accepts_approximate_reference():
    item = EvalItem(id="a", question="q", reference_answer="约 0.6827",
                    answer_type="numeric")
    assert objective_check(item, "P(-1<X<1) ≈ 0.6826")[0] is True
    # 精确答案不放宽容差
    item = EvalItem(id="e", question="q", reference_answer="9", answer_type="numeric")
    assert objective_check(item, "结果是 9.05")[0] is False


def test_objective_expr_uses_sympy():
    item = EvalItem(id="e", question="q", reference_answer="\\boxed{x^2}",
                    answer_type="expr")
    assert objective_check(item, "化简得 \\boxed{x*x}")[0] is True
    assert objective_check(item, "化简得 \\boxed{x+1}")[0] is False


def test_dataset_load_and_hash(tmp_path):
    path = tmp_path / "data.jsonl"
    rows = [
        {"id": "1", "question": "什么是极限", "reference_answer": "…",
         "answer_type": "concept", "gold_chunk_ids": ["01-limits#1"]},
        {"id": "2", "question": "不可答题", "answerable": False,
         "answer_type": "unanswerable", "reference_answer": ""},
    ]
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                    encoding="utf-8")
    items = load_items(path)
    assert [i.id for i in items] == ["1", "2"]
    assert items[1].answerable is False
    h1 = dataset_hash(items)
    items[0].question = "改了"
    assert dataset_hash(items) != h1


def test_dataset_rejects_bad_answer_type(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":"x","question":"q","answer_type":"unknown"}\n',
                    encoding="utf-8")
    with pytest.raises(ValueError):
        load_items(path)
