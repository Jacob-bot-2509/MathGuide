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


def test_temp_paper_rejects_publisher_host(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route(
        "/api/research/papers/temp", rp.create_temp, methods=["POST"])])
    client = TestClient(app)
    res = client.post("/api/research/papers/temp", json={
        "url": "https://link.springer.com/content/pdf/1.pdf",
    })
    assert res.status_code == 400


def test_temp_page_rejects_untrusted_host(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route(
        "/api/research/papers/temp-page", rp.create_temp_page,
        methods=["POST"])])
    client = TestClient(app)
    res = client.post("/api/research/papers/temp-page", json={
        "url": "https://evil.example/paper",
    })
    assert res.status_code == 400


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    rc._indexes.clear()
    rc._index_paths.clear()
    yield tmp_path
    rc._indexes.clear()
    rc._index_paths.clear()


def test_ingest_persists_source_metadata(corpus):
    result = rc._ingest(
        "u-meta", "meta.txt", TEXT.encode(), "text/plain", None,
        status="temp", analyze=False, metadata={
            "issn": "0028-0836",
            "publisher": "Springer Nature",
            "articleType": "research",
            "peerReviewed": True,
            "oaStatus": "gold",
            "license": "cc_by",
            "landingUrl": "https://example.org/paper",
            "retractionStatus": "none",
            "accessSource": "oa",
        })
    row = rc._doc_row("u-meta", result["docId"])
    assert row["issn"] == "0028-0836"
    assert row["publisher"] == "Springer Nature"
    assert row["peerReviewed"] is True
    assert row["oaStatus"] == "gold"
    assert row["accessSource"] == "oa"
    assert row["landingUrl"] == "https://example.org/paper"
    assert rc._clean_doc_meta(
        {"landingUrl": "https://user:pass@example.org/paper"}
    )["landing_url"] == ""


def test_temp_doc_is_hidden_from_library_and_default_search(corpus):
    temp = rc._ingest("u-t", "temp.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    normal = rc._ingest("u-n", "normal.txt", TEXT.encode(), "text/plain")
    assert normal["status"] != "temp"
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


# ---------------------------------------------------------------------------
# 追加:临时入库的失败映射、浏览历史、选区解释/表格抽取的降级。
# 为什么重要:这一层是"外部世界 → 站内"的接缝,失败必须落到明确的
# 400/404/429/502/503,而不是 500;历史接口删错就是把用户批注弄丢。
# ---------------------------------------------------------------------------

def test_temp_page_maps_ingest_and_download_failures(corpus, monkeypatch):
    """落地页入库:解析失败 → 400,下载失败 → 502(两者不能混)。

    前端按状态码区分"换个链接"还是"稍后重试"。
    """
    import httpx
    from starlette.testclient import TestClient

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-page"})
    monkeypatch.setattr(rp.rc, "_rate", lambda *args: None)
    app = Starlette(routes=[Route("/page", rp.create_temp_page, methods=["POST"])])
    client = TestClient(app)
    url = "https://europepmc.org/article/MED/1"

    async def bad_page(target):
        return b"\x00\x01binary junk"   # 解析不出正文 → ValueError

    monkeypatch.setattr(rp.lit, "download_allowed_page", bad_page)
    assert client.post("/page", json={"url": url}).status_code == 400

    async def timeout_page(target):
        raise httpx.ReadTimeout("slow upstream")

    monkeypatch.setattr(rp.lit, "download_allowed_page", timeout_page)
    assert client.post("/page", json={"url": url}).status_code == 502

    async def boom_page(target):
        raise ValueError("正文为空")

    monkeypatch.setattr(rp.lit, "download_allowed_page", boom_page)
    assert client.post("/page", json={"url": url}).status_code == 400


def test_temp_pdf_maps_value_and_transport_errors(corpus, monkeypatch):
    """PDF 入库:内容不合格 → 400,传输失败 → 502;元数据只接受 dict。"""
    import httpx
    from starlette.testclient import TestClient

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-pdf"})
    monkeypatch.setattr(rp.rc, "_rate", lambda *args: None)
    app = Starlette(routes=[Route("/pdf", rp.create_temp, methods=["POST"])])
    client = TestClient(app)
    url = "https://arxiv.org/pdf/2501.00002.pdf"

    async def broken_pdf(target):
        return b"%PDF-1.4 broken body"

    monkeypatch.setattr(rp.lit, "download_allowed_pdf", broken_pdf)
    res = client.post("/pdf", json={"url": url, "metadata": "not-a-dict"})
    assert res.status_code == 400

    async def down(target):
        raise httpx.ConnectError("connection reset")

    monkeypatch.setattr(rp.lit, "download_allowed_pdf", down)
    res = client.post("/pdf", json={"url": url})
    assert res.status_code == 502


def test_pdf_and_page_names_are_derived_from_url_path():
    """下载文件名从 URL 路径推:没有文件名给兜底名,后缀不匹配就补上。

    名字为空会让阅读器把整篇当"未命名",导出与批注都挂在一个空名上。
    """
    assert rp._pdf_name("https://arxiv.org/pdf/") == "paper.pdf"
    assert rp._pdf_name("https://arxiv.org/pdf/2501.00001v1") == "2501.00001v1.pdf"
    assert rp._pdf_name("https://arxiv.org/pdf/2501.00001.pdf") == "2501.00001.pdf"
    assert rp._page_name("https://europepmc.org/article/") == "paper.html"
    assert rp._page_name("https://europepmc.org/article/MED/1") == "1.html"
    assert rp._page_name("https://europepmc.org/article/MED/1.htm") == "1.htm"
    assert len(rp._pdf_name("https://arxiv.org/pdf/" + "n" * 400)) == 200


def test_history_list_and_trash_endpoints(corpus, monkeypatch):
    """历史列表与回收站:temp 文档进列表,软删后进回收站。

    回收站是"误删恢复"的唯一入口,列表口径错了用户就找不回论文。
    """
    from starlette.testclient import TestClient

    kept = rc._ingest("u-hist-api", "a.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    removed = rc._ingest("u-hist-api", "b.txt",
                         (TEXT + "\nUnique second body.").encode(),
                         "text/plain", status="temp", analyze=False)
    rc._history_delete("u-hist-api", removed["docId"])
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-hist-api"})
    app = Starlette(routes=[
        Route("/history", rp.history_list),
        Route("/history/trash", rp.history_trash),
    ])
    client = TestClient(app)
    items = client.get("/history").json()["items"]
    assert [item["id"] for item in items] == [kept["docId"]]
    trash = client.get("/history/trash").json()["items"]
    assert [item["id"] for item in trash] == [removed["docId"]]
    assert trash[0]["daysLeft"] >= 28
    assert client.get("/history").headers["cache-control"] == "no-store"


def test_history_delete_hard_soft_and_missing(corpus, monkeypatch):
    """history_delete:硬删立即真空,软删保留 30 天;不存在 → 404。

    硬/软删弄反了就是把用户的批注一次性抹掉,所以分别断言返回的 days。
    """
    from starlette.testclient import TestClient

    soft = rc._ingest("u-del", "soft.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    hard = rc._ingest("u-del", "hard.txt",
                      (TEXT + "\nAnother body.").encode(),
                      "text/plain", status="temp", analyze=False)
    vacuumed: list[str] = []
    monkeypatch.setattr(rp.rc, "_vacuum", lambda uid: vacuumed.append(uid))
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-del"})
    app = Starlette(routes=[
        Route("/history/{doc_id}", rp.history_delete, methods=["DELETE"]),
        Route("/history/{doc_id}/restore", rp.history_restore, methods=["POST"]),
    ])
    client = TestClient(app)

    soft_res = client.delete(f"/history/{soft['docId']}")
    assert soft_res.status_code == 200
    assert soft_res.json() == {"ok": True, "hard": False, "days": rc.HISTORY_TTL_DAYS}
    assert vacuumed == []                    # 软删不做真空

    hard_res = client.delete(f"/history/{hard['docId']}?hard=yes")
    assert hard_res.status_code == 200
    assert hard_res.json() == {"ok": True, "hard": True, "days": 0}
    assert vacuumed == ["u-del"]

    assert client.delete("/history/does-not-exist").status_code == 404
    restored = client.post(f"/history/{soft['docId']}/restore")
    assert restored.status_code == 200 and restored.json() == {"ok": True}
    assert client.post("/history/does-not-exist/restore").status_code == 404


def test_history_retention_loop_purges_daily_and_survives_failure(monkeypatch):
    """每日清理循环:清理失败只记警告,不能停掉后续日期的清理。

    一次异常就终止循环的话,过期历史会永久留在库里。
    """
    import asyncio as _asyncio

    events: list[str] = []
    sleeps: list[int] = []

    class Stop(Exception):
        pass

    async def fake_sleep(seconds):
        sleeps.append(int(seconds))
        if len(sleeps) == 3:
            raise Stop

    def purge():
        events.append("purge")
        if len(events) == 1:
            raise RuntimeError("db locked")
        return 0

    monkeypatch.setattr(rp.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(rp.rc, "purge_expired_history_all", purge)
    with pytest.raises(Stop):
        _asyncio.run(rp.history_retention_loop())
    assert events == ["purge", "purge"]      # 失败后仍然继续下一轮
    assert sleeps == [24 * 60 * 60] * 3


def _vision_app(monkeypatch, uid: str):
    from starlette.testclient import TestClient

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": uid})
    app = Starlette(routes=[
        Route("/papers/{doc_id}/explain-region", rp.explain_region, methods=["POST"]),
        Route("/papers/{doc_id}/extract-table", rp.extract_table, methods=["POST"]),
    ])
    return TestClient(app)


def test_explain_region_status_mapping(corpus, monkeypatch):
    """选区解释的状态码:404 文档缺失 / 503 未配模型 / 429 限流 / 400 图片或内容 / 502 上游。

    这些分支各自对应一句不同的用户提示,混成一个 500 就没法排查。
    """
    doc = rc._ingest("u-explain", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    client = _vision_app(monkeypatch, "u-explain")
    image = {"mime": "image/png", "data": "aGVsbG8="}
    path = f"/papers/{doc['docId']}/explain-region"

    monkeypatch.setattr(rp.vision, "is_configured", lambda: False)
    assert client.post(path, json={"image": image}).status_code == 503
    assert client.post("/papers/nope/explain-region",
                       json={"image": image}).status_code == 404

    monkeypatch.setattr(rp.vision, "is_configured", lambda: True)
    monkeypatch.setattr(rp.vision, "_limiter", type("L", (), {
        "allow": lambda self, uid: False})())
    assert client.post(path, json={"image": image}).status_code == 429

    monkeypatch.setattr(rp.vision, "_limiter", type("L", (), {
        "allow": lambda self, uid: True})())
    assert client.post(path, json={"image": {"mime": "application/pdf",
                                             "data": "eA=="}}).status_code == 400

    def bad_image(payload):
        raise ValueError("图片解码失败")

    monkeypatch.setattr(rp.vision, "_decode_image", bad_image)
    assert client.post(path, json={"image": image}).status_code == 400

    monkeypatch.setattr(rp.vision, "_decode_image", lambda payload: ("image/png", b"x"))

    def rejected(mime, data, question):
        raise ValueError("该图不含可解释内容")

    monkeypatch.setattr(rp.vision, "explain_image", rejected)
    assert client.post(path, json={"image": image}).status_code == 400

    def upstream_down(mime, data, question):
        raise RuntimeError("vision 服务 502")

    monkeypatch.setattr(rp.vision, "explain_image", upstream_down)
    res = client.post(path, json={"image": image})
    assert res.status_code == 502


def test_extract_table_status_mapping_and_page_coercion(corpus, monkeypatch):
    """表格抽取:422 内容不可用 / 502 上游故障;page 脏值归零并夹到合法范围。

    page 直接 int() 会让前端传 "abc" 时 500;返回体里的 page 用来定位原页。
    """
    doc = rc._ingest("u-table", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    client = _vision_app(monkeypatch, "u-table")
    path = f"/papers/{doc['docId']}/extract-table"
    image = {"mime": "image/png", "data": "aGVsbG8="}

    monkeypatch.setattr(rp.vision, "is_configured", lambda: False)
    assert client.post(path, json={"image": image}).status_code == 503
    assert client.post("/papers/nope/extract-table",
                       json={"image": image}).status_code == 404

    monkeypatch.setattr(rp.vision, "is_configured", lambda: True)
    monkeypatch.setattr(rp.vision, "_limiter", type("L", (), {
        "allow": lambda self, uid: False})())
    assert client.post(path, json={"image": image}).status_code == 429

    monkeypatch.setattr(rp.vision, "_limiter", type("L", (), {
        "allow": lambda self, uid: True})())
    # 非图片内容 → 400(用真实 _decode_image 判 mime)
    assert client.post(path, json={"image": {"mime": "application/pdf",
                                            "data": "eA=="}}).status_code == 400

    def bad_image(payload):
        raise ValueError("图片解码失败")

    monkeypatch.setattr(rp.vision, "_decode_image", bad_image)
    assert client.post(path, json={"image": image}).status_code == 400

    monkeypatch.setattr(rp.vision, "_decode_image", lambda payload: ("image/png", b"x"))

    def bad_table(mime, data):
        raise ValueError("该图不是表格")

    monkeypatch.setattr(rp.vision, "extract_table", bad_table)
    assert client.post(path, json={"image": image, "page": "abc"}).status_code == 422

    def down(mime, data):
        raise RuntimeError("vision 服务超时")

    monkeypatch.setattr(rp.vision, "extract_table", down)
    assert client.post(path, json={"image": image}).status_code == 502

    monkeypatch.setattr(rp.vision, "extract_table",
                        lambda mime, data: {"columns": [], "rows": []})
    ok = client.post(path, json={"image": image, "page": "999999"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["page"] == 100000          # 上限夹紧
    assert body["docId"] == doc["docId"]
    assert body["docName"] == "paper.txt"
    assert body["table"] == {"columns": [], "rows": []}
    # 脏 page → 0
    assert client.post(path, json={"image": image, "page": "abc"}).json()["page"] == 0


def test_locate_requires_query_and_reports_mode(corpus, monkeypatch):
    """locate:缺 query → 400;返回体里的 mode 决定前端给一句还是一段。"""
    from starlette.testclient import TestClient

    doc = rc._ingest("u-loc2", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-loc2"})
    app = Starlette(routes=[
        Route("/papers/{doc_id}/locate", rp.locate, methods=["POST"])])
    client = TestClient(app)
    path = f"/papers/{doc['docId']}/locate"

    assert client.post(path, json={"query": "   "}).status_code == 400

    definition = client.post(path, json={"query": "什么是 annotations"})
    assert definition.status_code == 200
    assert definition.json()["passages"][0]["mode"] == "sentence"

    explain = client.post(path, json={"query": "解释这段 temporary papers"})
    assert explain.json()["passages"][0]["mode"] == "paragraph"

    auto = client.post(path, json={"query": "temporary papers"})
    assert auto.json()["passages"][0]["mode"] == "auto"
    assert auto.json()["passages"][0]["page"] >= 1


def test_locate_mode_and_trim_quote_granularity():
    """粒度判定与裁剪:术语提问只给一句,解释给三段,空片段给空串。

    裁剪错了用户看到的引用会与问题无关(点"定义"却返回整段)。
    """
    assert rp._locate_mode("What is a spectral gap?") == "sentence"
    assert rp._locate_mode("define spectral gap") == "sentence"
    assert rp._locate_mode("概括这一段") == "paragraph"
    assert rp._locate_mode("summarize the paragraph") == "paragraph"
    assert rp._locate_mode("spectral gaps") == "auto"

    text = "First sentence. Second one about gaps. Third. Fourth. Fifth."
    # 术语提问:只给命中术语所在的那一句
    assert rp._trim_quote(text, "gaps", "sentence") == "Second one about gaps."
    # 解释提问:给三段
    trimmed = rp._trim_quote(text, "gaps", "paragraph")
    assert trimmed.startswith("Second one about gaps.")
    assert trimmed.count(".") == 3
    # auto:给两句
    assert rp._trim_quote(text, "gaps", "auto").count(".") == 2
    # 空输入 → 空串(前端据此不显示引用块)
    assert rp._trim_quote("   ", "gaps", "auto") == ""
    # 只有标点、没有可切分的句子:退成整段但不超过 500 字
    assert rp._trim_quote("...", "gaps", "auto") == "..."
    assert rp._trim_quote("....", "gaps", "auto") == "...."
    # 无句末标点的长串:按"两句"仍只有一段,整体截到 600 字以内
    assert rp._trim_quote("x" * 900, "gaps", "auto") == "x" * 600
    # 术语完全不在片段里:从第一句开始摘
    assert rp._trim_quote(text, "zzz", "auto").startswith("First sentence.")


def test_import_paper_validates_body_and_maps_errors(corpus, monkeypatch):
    """导入临时论文:缺 docId → 400,底层 ValueError → 400,文件没了 → 404。

    这三条必须分开,否则用户分不清"参数错""内容坏"还是"已被清理"。
    """
    from starlette.testclient import TestClient

    temp = rc._ingest("u-imp2", "paper.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-imp2"})
    app = Starlette(routes=[Route("/import", rp.import_paper, methods=["POST"])])
    client = TestClient(app)

    assert client.post("/import", json={"projectId": None}).status_code == 400

    def gone(uid, doc_id, project, keep):
        raise FileNotFoundError(doc_id)

    monkeypatch.setattr(rp.rc, "import_temp_doc", gone)
    assert client.post("/import", json={"docId": temp["docId"]}).status_code == 404

    def rejected(uid, doc_id, project, keep):
        raise ValueError("该论文不在临时区")

    monkeypatch.setattr(rp.rc, "import_temp_doc", rejected)
    assert client.post("/import", json={"docId": temp["docId"]}).status_code == 400

    seen: dict = {}

    def ok(uid, doc_id, project, keep):
        seen.update({"uid": uid, "doc_id": doc_id, "project": project, "keep": keep})
        return {"docId": doc_id, "status": "imported"}

    monkeypatch.setattr(rp.rc, "import_temp_doc", ok)
    res = client.post("/import", json={
        "docId": temp["docId"], "projectId": "p-1", "keepAnnotations": False})
    assert res.status_code == 200
    assert res.json() == {"docId": temp["docId"], "status": "imported"}
    # projectId 是字符串 → 透传;keepAnnotations=False 也要透传
    assert seen == {"uid": "u-imp2", "doc_id": temp["docId"],
                    "project": "p-1", "keep": False}

    client.post("/import", json={"docId": temp["docId"], "projectId": 123})
    assert seen["project"] is None      # 数字型 projectId 直接丢弃




