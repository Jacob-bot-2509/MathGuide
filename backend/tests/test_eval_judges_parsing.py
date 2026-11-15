"""evaluation/judges:评审器输出解析与归一的边界。

这些函数决定了"评审结果能不能被信任":模型返回带 ``` 围栏、返回数组、返回脏字段
都必须走确定的路径 —— 解析错就会把"未判定"记成"幻觉",直接影响对外数字。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from evaluation import judges


def _chunk(title="T", section="S", text="x" * 2000):
    return SimpleNamespace(title=title, section=section, text=text)


def test_context_marks_missing_sources():
    assert judges._context([]) == "(无检索资料)"


def test_context_numbers_and_truncates_chunks():
    chunks = [_chunk("A", "s1", "a" * 5000), _chunk("B", "s2", "b" * 10), _chunk("C", "s3", "c")]

    text = judges._context(chunks, limit=2, per_chunk=100)

    assert text.startswith("[1] A · s1\n")
    assert "a" * 100 in text and "a" * 101 not in text
    assert "[2] B · s2" in text
    # limit=2:第 3 条不进上下文,避免把评委 prompt 撑爆
    assert "[3]" not in text


def test_parse_json_accepts_fenced_output():
    raw = '```json\n{"correct": true, "claims": []}\n```'
    assert judges._parse_json(raw) == {"correct": True, "claims": []}


def test_parse_json_extracts_object_from_prose():
    assert judges._parse_json('结论如下 {"correct": false} 以上') == {"correct": False}


def test_parse_json_rejects_missing_object():
    with pytest.raises(ValueError, match="不含 JSON 对象"):
        judges._parse_json("模型只说了人话")


def test_parse_json_rejects_input_without_object():
    # 只有数组/纯文本时找不到 {...},按"不含 JSON 对象"拒绝
    with pytest.raises(ValueError, match="不含 JSON 对象"):
        judges._parse_json("[1, 2, 3]")


def test_normalize_skips_malformed_claims_and_clamps_fields():
    data = {
        "claims": [
            "不是对象",                                  # 跳过
            {"text": "   "},                             # 空文本跳过
            {"text": "y" * 500, "supported": "maybe", "reason": "r" * 500},
            {"text": "有依据", "supported": True},
        ],
    }

    result = judges._normalize(data, SimpleNamespace(answerable=True))

    claims = result["claims"]
    assert len(claims) == 2
    # supported 只接受布尔:字符串这类噪声记 null(未判定),不能算成"幻觉"
    assert claims[0]["supported"] is None
    assert len(claims[0]["text"]) == 300
    assert len(claims[0]["reason"]) == 200
    assert claims[1]["supported"] is True
    assert result["claim_schema"] == "truth-v2"


def test_normalize_accepts_legacy_refused_field_for_unanswerable_items():
    """旧评审只给 refused 没给 correct 时:不可答题的拒答视为"恰当处理"。"""
    result = judges._normalize({"refused": True}, SimpleNamespace(answerable=False))
    assert result["correct"] is True

    result = judges._normalize({"refused": False}, SimpleNamespace(answerable=False))
    assert result["correct"] is False


def test_normalize_drops_invalid_score_and_correct_values():
    result = judges._normalize(
        {"correct": "yes", "score": 0.7, "refused": "no"},
        SimpleNamespace(answerable=True))
    assert result["correct"] is None
    assert result["score"] is None
    assert result["refused"] is None
