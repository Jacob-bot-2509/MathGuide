"""论文工作台:阅读进度、结构缓存与结构解析。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_corpus as rc

TEXT = """Introduction
We study paper workspaces and reading progress.

2 Methods
The reader keeps annotations and restores the last page.

3 Results
Structure is generated once and cached by content hash.
"""


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    rc._indexes.clear()
    rc._index_paths.clear()
    yield tmp_path
    rc._indexes.clear()
    rc._index_paths.clear()


def _doc(uid: str = "u-ws") -> str:
    return rc._ingest(uid, "workspace.txt", TEXT.encode(), "text/plain",
                      analyze=False)["docId"]


def test_progress_roundtrip(corpus):
    doc_id = _doc()
    assert rc._set_progress("u-ws", doc_id, 3) is True
    row = rc._doc_row("u-ws", doc_id)
    assert row["lastPage"] == 3
    assert row["lastReadAt"] > 0
    docs, _, _ = rc._load_rows("u-ws")
    assert docs[0]["lastPage"] == 3
    assert rc._set_progress("u-ws", "missing", 1) is False


def test_structure_cache_is_keyed_by_content_hash(corpus):
    doc_id = _doc()
    structure = {"question": "Q", "methods": ["M"], "conclusions": ["C"],
                 "limitations": ["L"], "outline": [{"title": "Intro", "children": []}]}
    docs, _, _ = rc._load_rows("u-ws")
    sha = next(d["sha"] for d in docs if d["id"] == doc_id)
    rc._store_structure("u-ws", doc_id, sha, structure)
    assert rc._cached_structure("u-ws", doc_id) == structure
    # 内容哈希变化 = 缓存失效
    rc._store_structure("u-ws", doc_id, "stale-hash", structure)
    assert rc._cached_structure("u-ws", doc_id) is None


def test_delete_removes_structure_cache(corpus):
    doc_id = _doc("u-del")
    docs, _, _ = rc._load_rows("u-del")
    sha = next(d["sha"] for d in docs if d["id"] == doc_id)
    rc._store_structure("u-del", doc_id, sha, {
        "question": "Q", "methods": [], "conclusions": [], "limitations": [],
        "outline": [],
    })
    assert rc._delete("u-del", doc_id) is True
    conn = rc._connect("u-del")
    try:
        assert conn.execute(
            "SELECT 1 FROM doc_insights WHERE doc_id = ?", (doc_id,)
        ).fetchone() is None
    finally:
        conn.close()


def test_parse_structure_tolerates_fences_and_nested_outline():
    parsed = rc._parse_structure(
        '```json\n{"question":"Q","methods":["M"],'
        '"conclusions":["C"],"limitations":"L",'
        '"outline":[{"title":"A","children":[{"title":"A1"}]}]}\n```')
    assert parsed["question"] == "Q"
    assert parsed["limitations"] == ["L"]
    assert parsed["outline"][0]["children"][0]["title"] == "A1"
    with pytest.raises(ValueError):
        rc._parse_structure("not json")


def test_temp_upload_stays_out_of_library(corpus, monkeypatch):
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-drop"})
    monkeypatch.setattr(rc, "_upload_limiter", rc.SlidingWindowLimiter(20, 60))
    app = Starlette(routes=[
        Route("/api/research/docs", rc.upload_doc, methods=["POST"]),
        Route("/api/research/docs", rc.list_docs),
    ])
    client = TestClient(app)
    res = client.post(
        "/api/research/docs?name=dropped.txt&temp=1",
        content=TEXT.encode(), headers={"content-type": "text/plain"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["temp"] is True
    assert body["status"] == "temp"
    assert rc._doc_row("u-drop", body["docId"])["status"] == "temp"
    assert client.get("/api/research/docs").json()["docs"] == []


def test_insights_endpoint_generates_once(corpus, monkeypatch):
    doc_id = _doc("u-ins")
    calls: list[str] = []

    async def fake_build(uid, doc_id):
        calls.append(doc_id)
        docs, _, _ = rc._load_rows(uid)
        sha = next(d["sha"] for d in docs if d["id"] == doc_id)
        structure = {"question": "Q", "methods": ["M"], "conclusions": ["C"],
                     "limitations": ["L"], "outline": []}
        rc._store_structure(uid, doc_id, sha, structure)
        return structure

    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-ins"})
    monkeypatch.setattr(rc, "_build_structure", fake_build)
    monkeypatch.setattr(rc.llm_mod, "is_configured", lambda: True)
    monkeypatch.setattr(rc, "_insights_limiter", rc.SlidingWindowLimiter(20, 60))
    app = Starlette(routes=[
        Route("/api/research/docs/{doc_id}/insights", rc.get_insights),
        Route("/api/research/docs/{doc_id}/insights", rc.generate_insights,
              methods=["POST"]),
        Route("/api/research/docs/{doc_id}/progress", rc.save_progress,
              methods=["POST"]),
    ])
    client = TestClient(app)
    first = client.get(f"/api/research/docs/{doc_id}/insights").json()
    assert first["cached"] is False and first["structure"] is None
    made = client.post(f"/api/research/docs/{doc_id}/insights", json={}).json()
    assert made["cached"] is False and made["structure"]["question"] == "Q"
    again = client.get(f"/api/research/docs/{doc_id}/insights").json()
    assert again["cached"] is True and again["structure"]["question"] == "Q"
    client.post(f"/api/research/docs/{doc_id}/insights", json={})
    assert calls == [doc_id]
    pages = int(rc._doc_row("u-ins", doc_id)["pages"] or 1)
    progress = client.post(f"/api/research/docs/{doc_id}/progress", json={"page": 4})
    assert progress.status_code == 200
    assert rc._doc_row("u-ins", doc_id)["lastPage"] == min(pages, 4)
    too_high = client.post(
        f"/api/research/docs/{doc_id}/progress", json={"page": 999999})
    assert too_high.status_code == 200
    assert too_high.json()["page"] == pages
