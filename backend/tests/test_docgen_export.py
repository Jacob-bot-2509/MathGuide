"""docgen:导出分支(渲染后端失败/Word 公式不兼容)与无证据时的兜底大纲。

这些分支决定"生成文档"这条链路在最坏情况下是给用户可读的 422/500,
还是直接抛异常把请求打断。缺的 84 行里,导出分支和兜底大纲一共约 20 行。
"""
from __future__ import annotations

import asyncio

import pytest
from starlette.responses import Response

import docgen

DOC = {"title": "文档", "sections": [{"heading": "一", "paragraphs": ["正文"]}], "gaps": []}


def test_qa_document_skips_items_without_question_or_answer():
    document = docgen._qa_document(
        [{"question": "", "answer": "有答案"}, {"question": "有题", "answer": ""},
         {"question": "题", "answer": "答"}],
        "zh", "题库")

    assert len(document["sections"]) == 1
    assert document["sections"][0]["heading"].startswith("3. ")


def test_render_pdf_uses_qa_brand_and_returns_attachment(monkeypatch):
    captured = {}

    def fake_render(document, lang, brand):
        captured["brand"] = brand
        return b"%PDF-1.4"

    monkeypatch.setattr(docgen.doc, "render_pdf_bytes", fake_render)

    response = asyncio.run(docgen._render(DOC, "zh", "pdf", "mg-qa"))

    assert isinstance(response, Response)
    assert captured["brand"] == "问题解答 / Q&A"
    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment")


def test_render_pdf_failure_is_500(monkeypatch):
    monkeypatch.setattr(docgen.doc, "render_pdf_bytes", lambda *a, **k: None)

    with pytest.raises(Exception) as excinfo:
        asyncio.run(docgen._render(DOC, "zh", "pdf", "mg-doc"))
    assert getattr(excinfo.value, "status_code", None) == 500


def test_render_docx_formula_error_is_422(monkeypatch):
    def boom(*_args, **_kwargs):
        raise ValueError("array with column rules")

    monkeypatch.setattr(docgen, "_docx_bytes", boom)

    response = asyncio.run(docgen._render(DOC, "zh", "docx", "mg-doc"))
    assert response.status_code == 422
    assert "Formula cannot be converted to Word" in response.body.decode()


def test_render_markdown_path(monkeypatch):
    response = asyncio.run(docgen._render(DOC, "zh", "md", "mg-doc"))
    assert response.media_type == "text/markdown; charset=utf-8"
    assert "attachment" in response.headers["content-disposition"]


def test_fallback_outline_groups_by_title_section_and_marks_evidence():
    evidence = [
        {"id": "E1", "title": "极限", "section": "定义", "text": "x" * 300},
        {"id": "E2", "title": "极限", "section": "性质", "text": "y"},
        {"id": "E3", "title": "", "section": "", "text": "z"},
    ]

    outline = docgen._fallback_outline(evidence, "", "zh")

    headings = [section["heading"] for section in outline["sections"]]
    assert headings[:2] == ["极限", "知识片段"]
    assert outline["sections"][0]["evidence_ids"] == ["E1", "E2"]
    assert outline["sections"][0]["points"] == ["x" * 160]
    assert all(section["has_evidence"] is True for section in outline["sections"])
    assert outline["title"] == "文档"
    assert outline["gaps"] == []


def test_fallback_outline_caps_section_count(monkeypatch):
    monkeypatch.setattr(docgen, "MAX_SECTIONS", 2)
    evidence = [{"id": f"E{i}", "title": f"t{i}", "section": "", "text": "x"} for i in range(5)]

    outline = docgen._fallback_outline(evidence, "请求", "en")

    assert len(outline["sections"]) == 2
    assert outline["title"] == "请求"
