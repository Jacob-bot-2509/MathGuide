from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_corpus as rc
import research_papers as rp


def test_temp_endpoints_return_stored_format_after_doi_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    monkeypatch.setattr(rc, "_rate", lambda *args: None)
    text = "DOI 10.1234/example " + "Research results and full discussion. " * 10
    html = f"<html><body>{text}</body></html>".encode()
    pdf = b"%PDF-1.4 fake content"
    monkeypatch.setattr(rc, "_pdf_pages", lambda data: [(1, text), (2, text)])
    uid = ["pdf-first"]
    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": uid[0]})

    async def download_page(url):
        return html

    pdf_urls = []

    async def download_pdf(url):
        pdf_urls.append(url)
        return pdf

    monkeypatch.setattr(rp.lit, "download_allowed_page", download_page)
    monkeypatch.setattr(rp.lit, "download_allowed_pdf", download_pdf)
    app = Starlette(routes=[
        Route("/page", rp.create_temp_page, methods=["POST"]),
        Route("/pdf", rp.create_temp, methods=["POST"]),
    ])
    with TestClient(app) as client:
        first = client.post("/pdf", json={"url": "https://arxiv.org/pdf/1"}).json()
        second = client.post("/page", json={"url": "https://europepmc.org/article/MED/1"}).json()
        assert first["kind"] == second["kind"] == "pdf"
        assert second["duplicate"] and second["docId"] == first["docId"]
        assert second["pages"] == first["pages"] == 2
        uid[0] = "html-first"
        first = client.post("/page", json={"url": "https://europepmc.org/article/MED/1"}).json()
        second = client.post("/pdf", json={"url": "https://arxiv.org/pdf/1"}).json()
        assert first["kind"] == second["kind"] == "text"
        assert second["duplicate"] and second["docId"] == first["docId"]
        assert second["pages"] == first["pages"] == 1
        uid[0] = "arxiv-abstract"
        arxiv = client.post("/page", json={"url": "https://arxiv.org/abs/1706.03762v1"}).json()
        assert arxiv["kind"] == "pdf" and arxiv["pages"] == 2
        assert pdf_urls[-1] == "https://arxiv.org/pdf/1706.03762v1"
    rc._indexes.clear()
    rc._index_paths.clear()
