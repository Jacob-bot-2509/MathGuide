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


def test_render_math_supports_inline_starting_with_digit():
    html = doc._render_math(html_mod.escape(r"$0 < |x - x_0| < \delta$"))
    assert 'class="mg-math"' in html
    assert r"0 &lt; |x - x_0| &lt; \delta" in html


def test_render_math_supports_display_environments_and_escapes_html():
    text = r"Inline $x^2$ and \(y\), display \[\frac{1}{2}\] and \begin{align*}a&=b\\c&=d\end{align*} <script>alert(1)</script>"
    rendered = doc._render_math(html_mod.escape(text))
    assert rendered.count('class="mg-math"') == 2
    assert rendered.count('class="mg-mathd"') == 2
    assert r'\begin{align*}' in rendered
    assert '&lt;script&gt;' in rendered and '<script>' not in rendered


def test_pdf_renders_real_math_with_edge():
    import pytest
    from io import BytesIO
    from pypdf import PdfReader
    if not doc._find_edge():
        pytest.skip("Edge is unavailable")
    document = {"title": "Test", "sections": [{"heading": "Math", "paragraphs": [
        r"Inline $x^2$; \[\frac{1}{2}\] and \begin{align*}a&=b\\c&=d\end{align*}",
        "\u7b54\u6848: " + r"\frac{10}{11}",
    ]}]}
    data = doc.render_pdf_bytes(document)
    assert data and data.startswith(b"%PDF")
    text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    assert '[Formula render failed]' not in text
    assert r'\frac' not in text and r'\begin' not in text







def test_pdf_renders_source_cross_reference_macro():
    import pytest
    from io import BytesIO
    from pypdf import PdfReader
    if not doc._find_edge():
        pytest.skip("Edge is unavailable")
    text = r"\begin{align*}x&=\knowl{./ref/path}{\text{4.1.3}}\end{align*}"
    document = {"title": "T", "sections": [{"heading": "H", "paragraphs": [text]}]}
    data = doc.render_pdf_bytes(document)
    assert data
    result = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    assert r"\knowl" not in result and "4.1.3" in result



def test_pdf_renders_markdown_escaped_ams_environment():
    import pytest
    from io import BytesIO
    from pypdf import PdfReader
    if not doc._find_edge():
        pytest.skip("Edge is unavailable")
    text = r"\begin{align\*}\dblInt\_{\cS_t}\\,\dee{x}\\\ &=15\pi\end{align\*}"
    document = {"title": "T", "sections": [{"heading": "H", "paragraphs": [text]}]}
    data = doc.render_pdf_bytes(document)
    assert data
    result = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    assert r"\begin" not in result and r"\dblInt" not in result
    assert "[Formula render failed]" not in result


def test_pdf_renders_doubly_escaped_formulas_and_preserves_failed_source():
    import pytest
    from io import BytesIO
    from pypdf import PdfReader
    if not doc._find_edge():
        pytest.skip("Edge is unavailable")
    document = {"title": "Test", "sections": [{"heading": "H", "paragraphs": [
        r"Plane \\(\alpha\\), lines \\(a\\), \\(b\\), angle \\(30^{\circ}\\).",
        r"Triangle $\triangle\(\triangle ABC\\)$; choice $\($ $\)$; $\frac{\cancelto{2}{10}}{\cancelto{3}{12}}$",
        r"Adjacent $①\times 3-$$②\times 2$",
        r"Unsupported: $\notacommand{x}$",
    ]}]}
    data = doc.render_pdf_bytes(document)
    assert data
    text = " ".join(page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages)
    assert "[Formula render failed]" not in text
    assert r"\notacommand" in text
    assert r"\alpha" not in text and r"30^{\circ}" not in text
    assert r"\triangle" not in text and "ABC" in text
    assert r"\cancelto" not in text
    assert r"\(" not in text and r"\)" not in text
