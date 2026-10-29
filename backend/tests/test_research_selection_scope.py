"""Selected-document restrictions must survive empty scopes and tree fallback."""
import research_corpus as rc
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def test_empty_selection_does_not_search_all(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "selection-test"})
    rc._ingest("selection-test", "a.txt", b"attention " * 20, "text/plain")
    index = rc._get_index("selection-test")
    assert index.search("attention", doc_ids=set())["hits"] == []
    app = Starlette(routes=[Route("/search", rc.search_docs, methods=["POST"])])
    with TestClient(app) as client:
        assert client.post("/search", json={"query": "attention", "docIds": []}).json()["hits"] == []
        assert client.post("/search", json={"query": "attention"}).json()["hits"]
        assert client.post("/search", json={"query": "attention", "docIds": "invalid"}).status_code == 400


def test_tree_fallback_keeps_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    data = ("Abstract\n" + "background context " * 12 + "\n\n1 Training\n" + "attention training " * 12).encode()
    first = rc._ingest("selection-test", "first.txt", data, "text/plain")
    second = rc._ingest("selection-test", "second.txt", data.replace(b"background", b"alternative"), "text/plain")
    index = rc._get_index("selection-test")
    abstract = next(n for n in index.nodes if n.doc_id == first["docId"] and n.title == "Abstract")
    monkeypatch.setattr(index, "_tree_walk", lambda query, candidates: {abstract.id})
    result = index.search("training", doc_ids={first["docId"]}, use_tree=True)
    assert result["hits"]
    assert {h["docId"] for h in result["hits"]} == {first["docId"]}
    assert first["docId"] != second["docId"]
