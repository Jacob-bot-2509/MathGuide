"""临时论文:状态隔离、文件/文本接口与外部 PDF 入库。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route

import research_corpus as rc
import research_lit as lit
import research_papers as rp

TEXT = """Introduction
We study temporary papers and their annotations.

2 Methods
The reader highlights passages and keeps notes tied to this document.

3 Results
Temporary documents stay out of the reviewed library until imported.
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


def test_temp_doc_is_hidden_from_library_and_default_search(corpus):
    temp = rc._ingest("u-t", "temp.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    normal = rc._ingest("u-n", "normal.txt", TEXT.encode(), "text/plain")
    assert temp["status"] == "temp"

    docs, _, _ = rc._load_rows("u-t")
    assert docs[0]["status"] == "temp"

    index = rc._get_index("u-t")
    assert index.search("annotations")["hits"] == []
    scoped = index.search("annotations", doc_ids={temp["docId"]})
    assert scoped["hits"]

    # 普通文档仍可检索
    index_n = rc._get_index("u-n")
    assert index_n.search("annotations")["hits"]


def test_doc_file_and_text_endpoints(corpus, monkeypatch):
    from starlette.testclient import TestClient

    temp = rc._ingest("u-file", "paper.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-file"})
    app = Starlette(routes=[
        Route("/api/research/docs/{doc_id}/file", rc.doc_file),
        Route("/api/research/docs/{doc_id}/text", rc.doc_text),
        Route("/api/research/docs", rc.list_docs),
    ])
    client = TestClient(app)
    doc_id = temp["docId"]

    listed = client.get("/api/research/docs").json()["docs"]
    assert listed == []

    res = client.get(f"/api/research/docs/{doc_id}/file")
    assert res.status_code == 200
    assert res.content == TEXT.encode()
    assert "inline" in res.headers["content-disposition"]

    text = client.get(f"/api/research/docs/{doc_id}/text?page=1").json()
    assert text["total"] == 1
    assert "annotations" in text["text"]

    assert client.get("/api/research/docs/nope/text").status_code == 404


def test_temp_endpoint_downloads_only_allowed_urls(corpus, monkeypatch):
    from starlette.testclient import TestClient

    async def fake_download(url: str) -> bytes:
        return TEXT.encode()

    monkeypatch.setattr(rp.lit, "download_allowed_pdf", fake_download)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-temp"})
    app = Starlette(routes=[
        Route("/api/research/papers/temp", rp.create_temp, methods=["POST"]),
    ])
    client = TestClient(app)

    bad = client.post("/api/research/papers/temp",
                      json={"url": "https://example.com/paper.pdf"})
    assert bad.status_code == 400

    ok = client.post("/api/research/papers/temp",
                     json={"url": "https://arxiv.org/pdf/2501.00001.pdf"})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "temp"
    assert body["docId"]
    assert body["pages"] >= 1


def test_allowlist_still_rejects_http():
    assert not lit._pdf_url_allowed("http://arxiv.org/pdf/1.pdf")


def test_annotation_crud(corpus, monkeypatch):
    from starlette.testclient import TestClient

    temp = rc._ingest("u-anno", "paper.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u-anno"})
    app = Starlette(routes=[
        Route("/api/research/docs/{doc_id}/annotations", rc.list_annotations),
        Route("/api/research/docs/{doc_id}/annotations", rc.save_annotation,
              methods=["POST"]),
        Route("/api/research/docs/{doc_id}/annotations/{annotation_id}",
              rc.delete_annotation, methods=["DELETE"]),
    ])
    client = TestClient(app)
    doc_id = temp["docId"]

    created = client.post(f"/api/research/docs/{doc_id}/annotations", json={
        "page": 1, "quote": "temporary papers", "note": "key sentence",
        "rects": [[0.1, 0.2, 0.3, 0.04]], "color": "yellow",
    })
    assert created.status_code == 200, created.text
    item = created.json()["annotation"]
    assert item["quote"] == "temporary papers"
    assert item["rects"] == [[0.1, 0.2, 0.3, 0.04]]

    listed = client.get(f"/api/research/docs/{doc_id}/annotations").json()["annotations"]
    assert [a["id"] for a in listed] == [item["id"]]

    updated = client.post(f"/api/research/docs/{doc_id}/annotations", json={
        "id": item["id"], "page": 1, "quote": "temporary papers",
        "note": "edited note", "rects": [],
    }).json()["annotation"]
    assert updated["note"] == "edited note"

    bad = client.post(f"/api/research/docs/{doc_id}/annotations", json={
        "page": 0, "quote": "x"})
    assert bad.status_code == 400

    assert client.delete(
        f"/api/research/docs/{doc_id}/annotations/{item['id']}").status_code == 200
    assert client.get(
        f"/api/research/docs/{doc_id}/annotations").json()["annotations"] == []


def test_import_temp_paper_promotes_status(corpus, monkeypatch):
    from starlette.testclient import TestClient

    temp = rc._ingest("u-imp", "paper.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-imp"})
    app = Starlette(routes=[
        Route("/api/research/papers/import", rp.import_paper, methods=["POST"]),
    ])
    client = TestClient(app)
    doc_id = temp["docId"]

    first = client.post("/api/research/papers/import", json={"docId": doc_id})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "imported"

    docs, _, _ = rc._load_rows("u-imp")
    assert docs[0]["status"] == "imported"

    again = client.post("/api/research/papers/import", json={"docId": doc_id})
    assert again.status_code == 200
    assert again.json()["duplicate"] is True

    assert client.post("/api/research/papers/import",
                       json={"docId": "missing"}).status_code == 404


def test_import_can_drop_annotations(corpus):
    temp = rc._ingest("u-keep", "paper.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    doc_id = temp["docId"]
    rc._save_annotation("u-keep", doc_id, {
        "page": 1, "quote": "temporary papers", "rects": [],
    })
    assert rc._list_annotations("u-keep", doc_id)

    rc._import_temp("u-keep", doc_id, None, keep_annotations=False)
    assert rc._list_annotations("u-keep", doc_id) == []


def test_locate_returns_scoped_passages(corpus, monkeypatch):
    from starlette.testclient import TestClient

    doc = rc._ingest("u-loc", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-loc"})
    app = Starlette(routes=[
        Route("/api/research/papers/{doc_id}/locate", rp.locate, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post(f"/api/research/papers/{doc['docId']}/locate",
                      json={"query": "reader highlights passages"})
    assert res.status_code == 200, res.text
    passages = res.json()["passages"]
    assert passages
    assert passages[0]["page"] >= 1
    assert passages[0]["quote"]

    missing = client.post("/api/research/papers/nope/locate", json={"query": "x"})
    assert missing.status_code == 404


def test_history_delete_restore_and_purge(corpus):
    first = rc._ingest("u-hist", "a.txt", TEXT.encode(), "text/plain",
                       status="temp", analyze=False)
    second = rc._ingest("u-hist", "b.txt",
                        (TEXT + "\nUnique follow-up paragraph.").encode(),
                        "text/plain", status="temp", analyze=False)
    rc._save_annotation("u-hist", first["docId"], {
        "page": 1, "quote": "temporary papers", "rects": [],
    })

    items = rc._history_items("u-hist")
    assert len(items) == 2
    assert items[0]["annotations"] + items[1]["annotations"] == 1

    assert rc._history_delete("u-hist", first["docId"]) is True
    assert len(rc._history_items("u-hist")) == 1
    trash = rc._history_trash("u-hist")
    assert [t["id"] for t in trash] == [first["docId"]]
    assert 28 <= trash[0]["daysLeft"] <= 30

    assert rc._history_restore("u-hist", first["docId"]) is True
    assert len(rc._history_items("u-hist")) == 2
    assert rc._list_annotations("u-hist", first["docId"])

    # 模拟 30 天到期:清理后文档、批注一起消失
    import time as _time
    assert rc._history_delete("u-hist", second["docId"]) is True
    conn = rc._connect("u-hist")
    try:
        conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?",
                     (_time.time() - 1, second["docId"]))
        conn.commit()
    finally:
        conn.close()
    assert rc.purge_expired_history("u-hist") == 1
    remaining = {d["id"] for d in rc._load_rows("u-hist")[0]}
    assert second["docId"] not in remaining


def test_temp_capacity_evicts_oldest_unannotated(corpus, monkeypatch):
    monkeypatch.setattr(rc, "TEMP_DOC_LIMIT", 2)
    a = rc._ingest("u-evict", "a.txt", TEXT.encode(), "text/plain",
                   status="temp", analyze=False)
    b = rc._ingest("u-evict", "b.txt",
                   (TEXT + "\nSecond unique body.").encode(),
                   "text/plain", status="temp", analyze=False)
    rc._save_annotation("u-evict", a["docId"], {
        "page": 1, "quote": "temporary papers", "rects": [],
    })

    c = rc._ingest("u-evict", "c.txt",
                   (TEXT + "\nThird unique body.").encode(),
                   "text/plain", status="temp", analyze=False)
    ids = {d["id"] for d in rc._load_rows("u-evict")[0]}
    assert a["docId"] in ids  # 有批注,不淘汰
    assert b["docId"] not in ids  # 最旧且无批注,被淘汰
    assert c["docId"] in ids
    assert rc._list_annotations("u-evict", a["docId"])

    rc._save_annotation("u-evict", c["docId"], {
        "page": 1, "quote": "temporary papers", "rects": [],
    })
    with pytest.raises(ValueError):
        rc._ingest("u-evict", "d.txt",
                   (TEXT + "\nFourth unique body.").encode(),
                   "text/plain", status="temp", analyze=False)


def test_explain_region_endpoint(corpus, monkeypatch):
    import base64
    from starlette.testclient import TestClient

    doc = rc._ingest("u-vis", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-vis"})
    monkeypatch.setattr(rp.vision, "is_configured", lambda: True)
    monkeypatch.setattr(rp.vision, "_limiter", type("L", (), {
        "allow": lambda self, uid: True,
    })())
    monkeypatch.setattr(rp.vision, "explain_image",
                        lambda mime, data, question: f"示意说明:{question}")
    app = Starlette(routes=[
        Route("/api/research/papers/{doc_id}/explain-region",
              rp.explain_region, methods=["POST"]),
    ])
    client = TestClient(app)
    image = {
        "mime": "image/png",
        "data": base64.b64encode(b"fake png").decode(),
    }
    res = client.post(
        f"/api/research/papers/{doc['docId']}/explain-region",
        json={"image": image, "question": "这张图说明什么"})
    assert res.status_code == 200, res.text
    assert "这张图说明什么" in res.json()["answer"]

    bad = client.post(
        f"/api/research/papers/{doc['docId']}/explain-region",
        json={"image": {"mime": "application/pdf", "data": "eA=="}})
    assert bad.status_code == 400
