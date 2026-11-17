"""习题集生成历史:草稿、确认、用户隔离与注销清理。"""
from __future__ import annotations

import pytest

import db
import exercise_history as history


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mathguide.db")
    db.init()
    yield
    db.reset_for_tests()


def test_draft_not_in_history_and_confirm_promotes(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {"topics": ["algebra"]},
        7, [], "zh", "solutions", "习题集 · 代数",
    )
    assert history.list_documents("u1") == []
    assert history.confirm("u1", doc_id) is True
    rows = history.list_documents("u1")
    assert [row["id"] for row in rows] == [doc_id]
    assert rows[0]["count"] == 0


def test_other_user_cannot_read_or_delete(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {}, 1, [], "zh", "questions", "t")
    history.confirm("u1", doc_id)
    assert history.get_document("u2", doc_id) is None
    assert history.delete_document("u2", doc_id) is False
    assert history.get_document("u1", doc_id) is not None


def test_delete_user_removes_all(temp_db):
    doc_id = history.create_draft(
        "u1", {"title": "t", "sections": []}, {}, 1, [], "zh", "questions", "t")
    history.confirm("u1", doc_id)
    history.delete_user("u1")
    assert history.list_documents("u1") == []
