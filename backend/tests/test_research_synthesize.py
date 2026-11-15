"""synthesize:资料编号提示词与引用区拼装。

引用区是这套"抗编造"设计的最后一道闸:链接与作者**不经过模型**,由后端用真实
SearchHit 元数据拼装。所以这里断言的重点是"引用区只用真实字段,模型输出进不来"。
"""
from __future__ import annotations

import asyncio

from rag.research import llm, synthesize
from rag.research.types import SearchHit


def test_user_prompt_numbers_sources_and_marks_data_table():
    hits = [
        SearchHit(source="arXiv", title="A", snippet="摘要" * 300, authors="张三", year=2024),
        SearchHit(source="zbMATH", title="B", snippet="s", year=0),
    ]
    prompt = synthesize._user_prompt("什么是秩", hits, extra="| x | y |")

    assert "问题:什么是秩" in prompt
    assert "[1] 标题:A(arXiv · 张三 · 2024)" in prompt
    # 摘要截断到 400 字,避免把整段塞进提示词
    truncated = ("摘要" * 300)[:400]
    assert f"    摘要:{truncated}" in prompt
    assert truncated + "摘要" not in prompt
    assert "[2] 标题:B(zbMATH)" in prompt
    assert "研究数据表" in prompt


def test_user_prompt_without_extra_has_no_data_section():
    prompt = synthesize._user_prompt("q", [SearchHit(source="arXiv", title="A")])
    assert "研究数据表" not in prompt


def test_synthesize_stream_uses_language_specific_system_prompt(monkeypatch):
    seen: list[tuple[str, str]] = []

    async def fake_stream(system, user, **_kwargs):
        seen.append((system, user))
        yield "答"
        yield "案"

    monkeypatch.setattr(llm, "stream_chat", fake_stream)

    async def collect(zh: bool) -> str:
        return "".join([chunk async for chunk in synthesize.synthesize_stream(
            "问题", [SearchHit(source="arXiv", title="A")], zh)])

    assert asyncio.run(collect(True)) == "答案"
    assert asyncio.run(collect(False)) == "答案"
    assert seen[0][0] == synthesize.SYSTEM_ZH
    assert seen[1][0] == synthesize.SYSTEM_EN


def test_citations_block_uses_real_metadata_only(monkeypatch):
    hits = [
        SearchHit(source="arXiv", title="标题一", authors="李四", year=2023, url="https://x/1"),
        SearchHit(source="知识库", title="标题二"),
    ]
    block = synthesize.citations_block(hits, zh=True)

    assert block.startswith("\n---\n**参考来源:**")
    assert "> [1] 标题一 — 李四 · 2023 · arXiv" in block
    assert "> [https://x/1](https://x/1)" in block
    # 没有 url 的条目不加链接行
    assert block.count("https://") == 2
    assert "> [2] 标题二 — 知识库" in block


def test_citations_block_english_header_and_empty_hits():
    assert "References:" in synthesize.citations_block([], zh=False)
    assert "参考来源:" in synthesize.citations_block([], zh=True)
