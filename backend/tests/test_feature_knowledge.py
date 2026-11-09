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
