"""科研语料库:切片、章节树、BM25 检索与按用户隔离。"""
from __future__ import annotations

import pytest

import research_corpus as rc


SAMPLE = """Abstract
We study attention mechanisms for long documents.

1 Introduction
Attention lets a model weight relevant context. This section motivates the problem
and summarizes the contributions of the paper.

1.1 Background
Prior work used recurrence; attention removes the sequential bottleneck and allows
parallel computation over tokens.

2 Methods
We define scaled dot-product attention and describe the encoder stack in detail.

2.1 Training
The model is trained with Adam and a linear warmup schedule.

3 Results
The proposed model improves accuracy on long-document benchmarks.

References
[1] Vaswani et al. Attention is all you need.
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


def test_sections_detect_headings_and_levels():
    sections = rc._sections([(1, SAMPLE)])
    titles = [s.title for s in sections]
    assert "Abstract" in titles
    assert "1 Introduction" in titles
    assert "1.1 Background" in titles
    assert rc._heading_level("1 Introduction") == 1
    assert rc._heading_level("1.1 Background") == 2


def test_ingest_builds_tree_and_searches(corpus):
    result = rc._ingest("u-1", "attention.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert result["duplicate"] is False
    assert result["chunks"] >= 3

    index = rc._get_index("u-1")
    out = index.search("attention long documents", top_k=3)
    assert out["mode"] == "bm25"
    assert out["hits"], "BM25 应命中 attention 相关片段"
    hit = out["hits"][0]
    assert hit["docName"] == "attention.txt"
    assert hit["pageStart"] >= 1
    assert "attention" in hit["snippet"].lower()

    nodes = {n.id: n for n in index.nodes}
    intro = next(n for n in index.nodes if n.title.startswith("1 Introduction"))
    background = next(n for n in index.nodes if n.title.startswith("1.1"))
    assert background.parent_id == intro.id
    assert intro.parent_id is None
    assert nodes[background.id].page_start == 1


def test_duplicate_upload_returns_existing_doc(corpus):
    first = rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    second = rc._ingest("u-1", "a-renamed.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert second["duplicate"] is True
    assert second["docId"] == first["docId"]


def test_user_corpora_are_isolated(corpus):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    other = rc._get_index("u-2")
    assert other.chunks == []
    assert other.search("attention")["hits"] == []


def test_chat_hits_use_only_own_corpus(corpus):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    hits = rc.chat_hits("u-1", "attention", top_k=3)
    assert hits and hits[0]["docName"] == "a.txt"
    assert rc.chat_hits("u-2", "attention") == []


def test_delete_removes_doc_and_chunks(corpus):
    info = rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert rc._delete("u-1", info["docId"]) is True
    assert rc._get_index("u-1").chunks == []
    assert rc._delete("u-1", info["docId"]) is False


def test_delete_user_removes_entire_corpus(corpus):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert rc._get_index("u-1").chunks
    rc.delete_user("u-1")
    assert rc.chat_hits("u-1", "attention") == []


def test_rejects_empty_text(corpus):
    with pytest.raises(ValueError):
        rc._ingest("u-1", "empty.txt", b"   \n", "text/plain")


@pytest.fixture()
def api(corpus, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-api"})
    app = Starlette(routes=[
        Route("/api/research/docs", rc.upload_doc, methods=["POST"]),
        Route("/api/research/docs", rc.list_docs),
        Route("/api/research/docs/{doc_id}", rc.delete_doc, methods=["DELETE"]),
        Route("/api/research/search", rc.search_docs, methods=["POST"]),
        Route("/api/research/tree", rc.tree),
    ])
    return TestClient(app)


def test_api_upload_search_tree_delete(api):
    res = api.post(
        "/api/research/docs?name=attention.txt",
        content=SAMPLE.encode("utf-8"),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 200, res.text
    doc_id = res.json()["docId"]

    res = api.post("/api/research/search", json={"query": "attention complexity"})
    assert res.status_code == 200
    body = res.json()
    assert body["hits"] and body["hits"][0]["docId"] == doc_id
    assert body["mode"] == "bm25"

    res = api.get("/api/research/docs")
    assert [d["id"] for d in res.json()["docs"]] == [doc_id]

    res = api.get(f"/api/research/tree?docId={doc_id}")
    assert res.status_code == 200
    assert any(n["title"].startswith("1.1") for n in res.json()["nodes"])

    assert api.delete(f"/api/research/docs/{doc_id}").status_code == 200
    assert api.get("/api/research/docs").json()["docs"] == []
