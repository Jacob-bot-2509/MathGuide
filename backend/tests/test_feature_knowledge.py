"""产品能力说明必须能被普通聊天检索到。"""
from __future__ import annotations

from pathlib import Path

import rag
from rag.documents import load_knowledge

KNOWLEDGE = Path(__file__).resolve().parent.parent / "knowledge"


def test_ebbinghaus_feature_doc_is_retrievable():
    chunks = load_knowledge(KNOWLEDGE)

    assert any("艾宾浩斯" in chunk.text for chunk in chunks)
    assert any("retention" in chunk.text.lower() for chunk in chunks)


def test_feature_doc_keywords_do_not_trigger_math_question():
    import json

    text = (KNOWLEDGE / "00-mathguide-features.md").read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("keywords:"))
    keywords = set(json.loads(line.split(":", 1)[1].strip()))

    assert "艾宾浩斯" in keywords
    assert "retention" in keywords
    assert not (keywords & {"复习", "学习进度", "掌握度", "知识图谱", "学习分析"})
