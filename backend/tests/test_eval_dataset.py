"""评测集 course-50:规模、字段完整性与 gold chunk 有效性。"""
from __future__ import annotations

from pathlib import Path

from evaluation.datasets import load_items
from rag.documents import load_knowledge

BACKEND = Path(__file__).resolve().parent.parent
DATASET = BACKEND / "evaluation" / "data" / "course-50.jsonl"


def _items():
    return load_items(DATASET)


def test_dataset_has_exactly_50_items():
    assert len(_items()) == 50


def test_ids_are_unique():
    ids = [item.id for item in _items()]
    assert len(ids) == len(set(ids))


def test_fields_are_complete():
    for item in _items():
        assert item.question
        assert item.domain
        assert 1 <= item.difficulty <= 5
        if item.answerable:
            assert item.reference_answer, item.id
        else:
            assert item.answer_type == "unanswerable", item.id
            assert not item.reference_answer, item.id


def test_gold_chunk_ids_exist_in_knowledge_base():
    valid = {chunk.id for chunk in load_knowledge(BACKEND / "knowledge")}
    for item in _items():
        for chunk_id in item.gold_chunk_ids:
            assert chunk_id in valid, f"{item.id}: 未知 gold chunk {chunk_id}"


def test_covers_required_answer_types():
    types = {item.answer_type for item in _items()}
    for required in ("concept", "numeric", "expr", "proof"):
        assert required in types, required
