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


def test_doi_is_extracted_and_deduplicates(corpus):
    text_a = SAMPLE + "\nDOI: 10.1234/example.2026.001\n"
    first = rc._ingest("u-1", "a.txt", text_a.encode("utf-8"), "text/plain")
    docs, _, _ = rc._load_rows("u-1")
    assert docs[0]["doi"] == "10.1234/example.2026.001"
    assert docs[0]["title"]
    assert docs[0]["year"] == 2026

    # 不同正文、同一 DOI:按 DOI 去重,返回同一篇
    text_b = text_a.replace("We study attention", "A revised version studies attention")
    second = rc._ingest("u-1", "a-v2.txt", text_b.encode("utf-8"), "text/plain")
    assert second["duplicate"] is True
    assert second["docId"] == first["docId"]


def test_chunk_pages_follow_actual_lines():
    pages = [(1, "1 Introduction\n" + "A" * 600), (2, "B" * 600)]
    sections = rc._sections(pages)
    chunks = rc._chunk_section(sections[0])
    assert chunks[0][1] == 1
    assert any(end == 2 for _, _, end in chunks)


def test_clear_all_docs(corpus):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert rc._clear_all("u-1") == 1
    docs, nodes, chunks = rc._load_rows("u-1")
    assert docs == [] and nodes == [] and chunks == []


def test_delete_user_removes_entire_corpus(corpus):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    assert rc._get_index("u-1").chunks
    rc.delete_user("u-1")
    assert rc.chat_hits("u-1", "attention") == []


def test_llm_tree_walk_selects_and_expands_nodes(corpus, monkeypatch):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    index = rc._get_index("u-1")

    monkeypatch.setenv("MG_TREE_WALK", "1")
    monkeypatch.setattr(rc.llm_mod, "is_configured", lambda: True)

    def fake_llm(system, user, **kwargs):
        first = user.split("候选章节:\n", 1)[1].splitlines()[0]
        return '["%s"]' % first.split(" | ")[0]

    monkeypatch.setattr(rc, "_llm_sync", fake_llm)
    node_ids = index._tree_walk("attention", list(range(len(index.nodes))))
    assert node_ids
    assert index.nodes[0].id in node_ids


def test_tree_walk_off_by_default(corpus, monkeypatch):
    rc._ingest("u-1", "a.txt", SAMPLE.encode("utf-8"), "text/plain")
    index = rc._get_index("u-1")
    monkeypatch.delenv("MG_TREE_WALK", raising=False)
    monkeypatch.setattr(rc.llm_mod, "is_configured", lambda: True)
    assert index._tree_walk("attention", list(range(len(index.nodes)))) is None


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
        Route("/api/research/projects", rc.list_projects),
        Route("/api/research/projects", rc.create_project, methods=["POST"]),
        Route("/api/research/projects/{project_id}", rc.update_project, methods=["POST"]),
        Route("/api/research/projects/{project_id}", rc.delete_project, methods=["DELETE"]),
    ])
    return TestClient(app)


def test_api_projects_and_project_scoped_search(api):
    project = api.post("/api/research/projects", json={"title": "Attention"}).json()["project"]
    pid = project["id"]

    updated = api.post(f"/api/research/projects/{pid}",
                       json={"goal": "了解复杂度瓶颈", "status": "active"}).json()["project"]
    assert updated["goal"] == "了解复杂度瓶颈"
    assert updated["status"] == "active"

    res = api.post(
        "/api/research/docs?name=attention.txt&projectId=" + pid,
        content=SAMPLE.encode("utf-8"),
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 200

    docs = api.get("/api/research/docs").json()["docs"]
    assert docs[0]["projectId"] == pid

    scoped = api.post("/api/research/search",
                      json={"query": "attention", "projectId": pid}).json()
    assert scoped["hits"]

    assert api.delete(f"/api/research/projects/{pid}").status_code == 200
    docs = api.get("/api/research/docs").json()["docs"]
    assert len(docs) == 1 and docs[0]["projectId"] is None


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
