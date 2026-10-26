"""doc.py:LLM 输出规整、引用字段消毒、CSP 与请求体校验。"""
from __future__ import annotations

import html as html_mod

import doc
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient


def test_safe_url_only_allows_http_schemes():
    assert doc._safe_url("https://example.com/a") == "https://example.com/a"
    assert doc._safe_url("HTTP://example.com") == "HTTP://example.com"
    assert doc._safe_url("javascript:alert(1)") == ""
    assert doc._safe_url("file:///C:/Windows/win.ini") == ""
    assert doc._safe_url("data:text/html,x") == ""
    assert doc._safe_url(None) == ""


def test_normalize_doc_coerces_ids_and_drops_bad_urls():
    obj = {
        "title": "T",
        "keywords": "极限",  # 裸字符串也应作为单个关键词
        "sections": [{"heading": "H", "paragraphs": ["p"]}],
        "references": [
            {"id": '<img src="file:///C:/Windows/win.ini">', "title": "bad",
             "source": "s", "url": "javascript:alert(1)"},
            {"id": 2, "title": "good", "source": "s", "url": "https://example.com"},
        ],
    }
    normalized = doc._normalize_doc(obj, "fallback", "zh")
    assert normalized["keywords"] == ["极限"]
    assert normalized["references"][0]["id"] == 1
    assert normalized["references"][0]["url"] == ""
    assert normalized["references"][1]["url"] == "https://example.com"


def test_render_html_escapes_id_and_adds_csp():
    normalized = doc._normalize_doc({
        "title": "T",
        "sections": [{"heading": "H", "paragraphs": ["p"]}],
        "references": [{"id": 1, "title": "t", "source": "s", "url": "https://e.com"}],
    }, "fallback", "zh")
    html = doc._render_html(normalized, "zh", doc._katex_dir())
    assert "Content-Security-Policy" in html
    assert "nonce-" in html
    assert '<script nonce="' in html
    assert "javascript:" not in html
    assert "file:///C:/Windows" not in html


def test_render_html_is_safe_even_if_caller_skips_normalization():
    """纵深防御:即使调用方绕过 _normalize_doc 传入恶意 id/url,渲染层也必须消毒。"""
    malicious = {
        "title": "T",
        "abstract": "",
        "keywords": [],
        "sections": [{"heading": "H", "paragraphs": ["p"]}],
        "references": [{"id": '<img src="file:///C:/Windows/win.ini">',
                        "title": "t", "source": "s", "url": "javascript:alert(1)"}],
    }
    html = doc._render_html(malicious, "zh", doc._katex_dir())
    assert "<img" not in html
    assert '<img src="file:///' not in html
    assert "javascript:alert(1)" not in html
    assert html_mod.escape('<img src="file:///C:/Windows/win.ini">') in html


def test_extract_json_tolerates_fences_and_noise():
    assert doc._extract_json('```json\n{"sections": []}\n```') == {"sections": []}
    assert doc._extract_json('noise {"sections": [1]} more') == {"sections": [1]}
    assert doc._extract_json("no json here") is None
    assert doc._extract_json("{broken") is None
    assert doc._extract_json("[1, 2]") is None  # 非对象


def test_fallback_doc_splits_paragraphs():
    result = doc._fallback_doc("第一段\n\n第二段", "zh")
    assert result["sections"][0]["paragraphs"] == ["第一段", "第二段"]


def test_export_pdf_rejects_empty_or_malformed_body(monkeypatch):
    monkeypatch.setattr(doc, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route("/api/doc/export", doc.export_pdf, methods=["POST"])])
    client = TestClient(app, raise_server_exceptions=False)

    res = client.post("/api/doc/export", content=b"{not json",
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 400

    res = client.post("/api/doc/export", json={"content": "  ", "lang": "zh"})
    assert res.status_code == 400
