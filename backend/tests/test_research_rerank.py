"""rerank:LLM 精排与规则分的混合,以及"精排失败必须退回纯规则排序"。

这个文件此前 55%。没覆盖的正好是最要紧的部分:解析模型输出的各种脏形态
(对象/数组/编号越界/非数字),以及超时、未配置、异常时的回退 ——
精排一旦抛错而不能回退,整条深度搜索就 500。
"""
from __future__ import annotations

import asyncio

import pytest

from rag.research import llm, rerank
from rag.research.types import SearchHit


def _hits(n: int) -> list[SearchHit]:
    return [SearchHit(source="arXiv", title=f"t{i}", snippet=f"s{i}", score=float(-i))
            for i in range(n)]


class FakeLLM:
    """把 stream_chat 换成可控的异步生成器。"""

    def __init__(self, reply: str = "", *, configured: bool = True,
                 raises: Exception | None = None, delay: float = 0.0):
        self.reply = reply
        self.configured = configured
        self.raises = raises
        self.delay = delay
        self.prompts: list[str] = []

    def patch(self, monkeypatch):
        def is_configured(_role="main"):
            return self.configured

        async def stream_chat(_system, user, **_kwargs):
            self.prompts.append(user)
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.raises:
                raise self.raises
            yield self.reply

        monkeypatch.setattr(llm, "is_configured", is_configured)
        monkeypatch.setattr(llm, "stream_chat", stream_chat)
        return self


# ---------- 短路径:不调模型 ----------

def test_fewer_than_two_candidates_skips_llm(monkeypatch):
    fake = FakeLLM('{"1": 90}').patch(monkeypatch)
    hits = _hits(1)
    result = asyncio.run(rerank.rerank("q", hits))
    assert result == hits
    assert fake.prompts == []


def test_unconfigured_role_skips_llm(monkeypatch):
    fake = FakeLLM('{"1": 90}', configured=False).patch(monkeypatch)
    hits = _hits(3)
    assert asyncio.run(rerank.rerank("q", hits)) == hits
    assert fake.prompts == []


# ---------- 正常精排 ----------

def test_object_scores_are_mixed_with_rule_scores(monkeypatch):
    FakeLLM('{"1": 100, "2": 0}').patch(monkeypatch)
    hits = _hits(2)          # 规则分 0 与 -1
    result = asyncio.run(rerank.rerank("q", hits))

    # 混合分 = 规则分×0.5 + LLM分×0.05
    assert result[0].title == "t0"
    assert result[0].score == pytest.approx(0 * 0.5 + 100 * 0.05)
    assert result[1].score == pytest.approx(-1 * 0.5 + 0 * 0.05)


def test_array_form_with_ids_and_plain_numbers(monkeypatch):
    # 数组形态:[{"id": 2, "score": 80}, 40] → 第 2 项先按 id=2 记 80,
    # 随后同位置被裸数字 40 覆盖(按位置回填);第 1 项没给分 → 中性 50
    FakeLLM('[{"id": 2, "score": 80}, 40]').patch(monkeypatch)
    hits = _hits(2)
    result = asyncio.run(rerank.rerank("q", hits))
    scores = {hit.title: hit.score for hit in result}
    assert scores["t1"] == pytest.approx(-1 * 0.5 + 40 * 0.05)
    assert scores["t0"] == pytest.approx(0 * 0.5 + 50 * 0.05)


def test_prompt_only_asks_for_json_and_mentions_candidates(monkeypatch):
    fake = FakeLLM('{"1": 50, "2": 50}').patch(monkeypatch)
    asyncio.run(rerank.rerank("什么是秩", _hits(2)))
    prompt = fake.prompts[0]
    assert "什么是秩" in prompt
    assert "只输出 JSON" in prompt


# ---------- 解析脏输出 ----------

@pytest.mark.parametrize("reply,expected", [
    ("前言 {\"1\": 70} 后记", 70.0),      # 前后有噪声文字
    ('{"9": 70, "1": 70}', 70.0),          # 编号越界应忽略,不越界的那条生效
    ('{"x": 70}', None),                   # 编号非数字 → 抛错(上层回退)
    ("no json here", None),                # 完全没有 JSON
])
def test_parse_handles_dirty_output(reply, expected):
    if expected is None:
        with pytest.raises((ValueError, KeyError)):
            rerank._parse(reply, 1)
    else:
        assert rerank._parse(reply, 1)[0] == expected


def test_parse_defaults_missing_entries_to_neutral_score():
    assert rerank._parse('{"1": 90}', 3) == [90.0, 50.0, 50.0]


# ---------- 回退路径 ----------

def test_llm_exception_falls_back_to_rule_order(monkeypatch):
    FakeLLM(raises=RuntimeError("boom")).patch(monkeypatch)
    hits = _hits(3)
    result = asyncio.run(rerank.rerank("q", hits))
    # 原样返回(纯规则排序),不影响调用方
    assert [hit.title for hit in result] == ["t0", "t1", "t2"]
    assert [hit.score for hit in result] == [0.0, -1.0, -2.0]


def test_timeout_falls_back(monkeypatch):
    # 模型迟迟不回 → wait_for 触发超时 → 原样返回纯规则顺序
    FakeLLM('{"1": 10}', delay=0.2).patch(monkeypatch)
    hits = _hits(2)
    result = asyncio.run(rerank.rerank("q", hits, timeout=0.01))
    assert [hit.title for hit in result] == ["t0", "t1"]
    assert [hit.score for hit in result] == [0.0, -1.0]


def test_unparseable_reply_falls_back(monkeypatch):
    FakeLLM("模型没按要求输出").patch(monkeypatch)
    hits = _hits(2)
    result = asyncio.run(rerank.rerank("q", hits))
    assert [hit.title for hit in result] == ["t0", "t1"]


def test_candidates_beyond_limit_are_kept_after_head(monkeypatch):
    FakeLLM('{"1": 100}').patch(monkeypatch)
    hits = _hits(rerank.MAX_CANDIDATES + 3)
    result = asyncio.run(rerank.rerank("q", hits))
    # 尾部候选不被精排,但仍全部返回
    assert len(result) == len(hits)
    assert {hit.title for hit in result} == {hit.title for hit in hits}
