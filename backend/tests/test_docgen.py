"""docgen.py:问答提取、问答/文档渲染、严格依据的大纲与分节生成。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import docgen

ANSWER = "导数是函数在一点的瞬时变化率。\n\n记作 $f'(x)$。"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(docgen, "require_auth", lambda request: {"uid": "u-1"})
    monkeypatch.setattr(docgen, "_rate_check", lambda uid: None)
    monkeypatch.setattr(docgen, "_record", lambda *a, **k: None)
    app = Starlette(routes=[
        Route("/api/doc/questions", docgen.questions, methods=["POST"]),
        Route("/api/doc/qa", docgen.qa_export, methods=["POST"]),
        Route("/api/doc/outline", docgen.outline, methods=["POST"]),
        Route("/api/doc/generate", docgen.generate, methods=["POST"]),
        Route("/api/doc/render", docgen.render, methods=["POST"]),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_questions_extracts_pairs_and_filters_commands(client):
    res = client.post("/api/doc/questions", json={"messages": [
        {"role": "user", "content": "什么是导数"},
        {"role": "assistant", "content": ANSWER},
        {"role": "user", "content": "章节知识导航", "cmd": "章节知识导航"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "什么是极限"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "什么是导数"},
        {"role": "assistant", "content": "重复问题"},
    ]})
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["question"] for item in items] == ["什么是导数", "什么是极限"]
    assert items[0]["has_answer"] is True
    assert items[1]["has_answer"] is False


def test_qa_export_markdown_uses_original_answer(client):
    res = client.post("/api/doc/qa", json={
        "items": [{"question": "什么是导数", "answer": ANSWER}],
        "source": "当前对话",
        "lang": "zh",
        "format": "md",
    })
    assert res.status_code == 200
    assert "text/markdown" in res.headers["content-type"]
    body = res.content.decode("utf-8")
    assert "# 问题解答文档" in body
    assert "什么是导数" in body
    assert "瞬时变化率" in body
    assert "当前对话" in body


def test_qa_export_docx_is_valid_zip(client):
    res = client.post("/api/doc/qa", json={
        "items": [{"question": "什么是导数", "answer": ANSWER}], "lang": "zh", "format": "docx",
    })
    assert res.status_code == 200
    assert res.content[:2] == b"PK"
    assert "wordprocessingml" in res.headers["content-type"]


def test_qa_export_rejects_empty_items(client):
    assert client.post("/api/doc/qa", json={"items": []}).status_code == 400
    assert client.post("/api/doc/qa", json={
        "items": [{"question": "q", "answer": "a"}],
        "source": "x", "format": "md"}).status_code == 200


def test_render_rejects_oversized_document(client):
    document = {"title": "T", "sections": [
        {"heading": "H", "paragraphs": ["x" * 100_001]},
    ]}
    assert client.post("/api/doc/render", json={"document": document}).status_code == 413


def test_outline_without_evidence_is_422(client, monkeypatch):
    monkeypatch.setattr(docgen.rag, "search", lambda query, top_k: [])
    res = client.post("/api/doc/outline", json={"request": "写一份泰勒展开讲义"})
    assert res.status_code == 422
    assert res.json()["error"] == "no_evidence"


def test_generate_requires_evidence_and_builds_document(client, monkeypatch):
    chunk = SimpleNamespace(
        id="c1", title="泰勒展开", section="定义",
        text="泰勒展开用多项式逼近函数。", keywords=[], category="analysis")
    monkeypatch.setattr(docgen.rag, "search", lambda query, top_k: [(chunk, 1.0)])
    monkeypatch.setattr(docgen.rag.llm, "is_configured", lambda role="main": True)

    async def fake_llm(system, user, *, max_tokens):
        return "泰勒展开把函数写成幂级数。\n\n收敛半径决定适用范围。"

    monkeypatch.setattr(docgen, "_collect_llm", fake_llm)
    body = {
        "request": "写一份泰勒展开讲义",
        "lang": "zh",
        "outline": {"title": "泰勒展开", "sections": [
            {"heading": "定义", "points": ["幂级数"], "evidence_ids": ["E1"]},
            {"heading": "无依据章节", "points": [], "evidence_ids": []},
        ]},
    }
    res = client.post("/api/doc/generate", json=body)
    assert res.status_code == 200
    data = res.json()
    assert data["document"]["title"] == "泰勒展开"
    assert data["document"]["sections"][0]["heading"] == "定义"
    assert data["document"]["references"][0]["title"] == "泰勒展开"
    assert data["gaps"] == ["无依据章节"]


def test_normalize_outline_marks_missing_evidence():
    evidence = [{"id": "E1", "title": "T", "section": "S", "text": "x"}]
    plan = docgen._normalize_outline({
        "title": "Doc",
        "sections": [
            {"heading": "A", "points": ["p"], "evidence_ids": ["E1"]},
            {"heading": "B", "points": ["q"], "evidence_ids": ["missing"]},
        ],
    }, evidence, "req", "zh")
    assert plan["sections"][0]["has_evidence"] is True
    assert plan["sections"][1]["has_evidence"] is False
    assert "B" in plan["gaps"]


def test_clean_markdown_strips_visible_syntax_not_math():
    text = "### 标题\n\n> 引用\n\n---\n\n* 条目 [是](cmd://nb/yes)\n\n公式 $f'(x)$ 保留"
    cleaned = docgen._clean_markdown(text)
    assert "###" not in cleaned and "> 引用" not in cleaned and "---" not in cleaned
    assert "[是]" not in cleaned and "cmd://" not in cleaned
    assert "$f'(x)$" in cleaned
    assert "• 条目" in cleaned


def test_word_export_contains_editable_math_for_all_supported_delimiters(client):
    from io import BytesIO
    from zipfile import ZipFile
    document = {"title": "Math $x$", "sections": [{"heading": "H", "paragraphs": [
        r"Inline $x^2$, \(\frac{1}{2}\), \[y=3\], $$\begin{aligned}a&=b\\c&=d\end{aligned}$$",
        r"\begin{align*}\dblInt_S \vF\cdot\hn\,\dee{S}&=\tripInt_V 1\end{align*}",
        r"\begin{align*}\overbrace{x}^{n}&=x\end{align*}",
        "\u7b54\u6848: " + r"\frac{10}{11}",
    ]}]}
    res = client.post("/api/doc/render", json={"document": document, "format": "docx"})
    assert res.status_code == 200
    with ZipFile(BytesIO(res.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf8")
    assert xml.count('<m:oMath>') == 8
    assert '<m:f>' in xml and '<m:groupChr>' in xml
    assert r'\frac' not in xml and r'\dblInt' not in xml


def test_word_export_reports_unsupported_formula(client):
    document = {"title": "T", "sections": [{"heading": "H", "paragraphs": [r"$\notacommand{x}$"]}]}
    res = client.post("/api/doc/render", json={"document": document, "format": "docx"})
    from io import BytesIO
    from zipfile import ZipFile
    assert res.status_code == 200
    with ZipFile(BytesIO(res.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf8")
    assert r"\notacommand{x}" in xml


def test_normalize_does_not_cut_long_paragraphs_inside_formula():
    import doc
    paragraph = "a" * 8000 + r"$\frac{1}{2}$"
    result = doc._normalize_doc({"sections": [{"heading": "H", "paragraphs": [paragraph]}]}, "", "zh")
    assert result["sections"][0]["paragraphs"][0] == paragraph


def test_bare_exercise_answers_are_marked_as_math():
    import math_render
    assert math_render.formula_answer(r"\alpha") == r"\(\alpha\)"
    assert math_render.formula_answer("x^2+1") == r"\(x^2+1\)"
    assert math_render.formula_answer("ordinary answer") == "ordinary answer"
    assert math_render.formula_answer(r"\(x^2\)") == r"\(x^2\)"


def test_shared_parser_accepts_doubled_and_mixed_delimiter_escapes():
    import math_render
    text = r"plane \\(\alpha\\), lines \\(a\\), \(b\\), \\(c\), \\[30^{\circ}\\]"
    formulas = [(display, value) for is_math, display, value in math_render.segments(text) if is_math]
    assert formulas == [(False, r"\alpha"), (False, "a"), (False, "b"), (False, "c"), (True, r"30^{\circ}")]
    assert all(math_render.to_omml(value) is not None for _, value in formulas)


def test_common_corpus_macros_convert_to_word():
    import math_render
    assert math_render.to_omml(r"\hk + \cC + \diff{x}{t} + \overparen{AB} + \mbox{height}") is not None




def test_markdown_cleanup_preserves_formula_before_splitting():
    formula = r"$$\begin{aligned}a__b&=[x](y)\\c&=\boxed{x_1}\end{aligned}$$"
    text = "**Heading**\n\n" + formula.replace(r"\\c", "\\\\\n\nc") + "\n\nTail"
    paragraphs = docgen._paragraphs(text)
    assert len(paragraphs) == 3
    assert "a__b" in paragraphs[1] and "[x](y)" in paragraphs[1]
    assert r"\boxed{x_1}" in paragraphs[1]
    assert "\n\n" in paragraphs[1]



def test_markdown_cleanup_preserves_incomplete_streaming_math():
    text = "Before\n\n" + r"$$\begin{aligned}a__b&=[x](y)" + "\n\n" + r"c**d"
    paragraphs = docgen._paragraphs(text)
    assert paragraphs == ["Before", text.split("\n\n", 1)[1]]



def test_unfinished_math_preserves_later_complete_formula():
    text = r"Text \[unfinished and $x^2$"
    assert docgen._clean_markdown(text) == text


def test_word_keeps_tex_when_one_formula_is_unsupported(client):
    from io import BytesIO
    from zipfile import ZipFile
    document = {"title": "T", "sections": [{"heading": "H", "paragraphs": [
        r"Before $\boxed{x_1}$; $\notacommand{x}$; after \(y^2\).",
    ]}]}
    response = client.post("/api/doc/render", json={"document": document, "format": "docx"})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf8")
    assert xml.count("<m:oMath>") == 2
    assert r"\notacommand{x}" in xml




def test_markdown_escaped_environment_is_repaired_without_changing_text():
    import math_render
    source = r"\begin{align\*}\dblInt\_{\cS_t}\\,\dee{x}\\\ &=15\pi+\text{file\_1}+\mathrm{A\_1}\end{align\*}"
    parts = list(math_render.segments(source))
    assert len(parts) == 1 and parts[0][0] and parts[0][1]
    prepared = math_render.prepare(parts[0][2])
    assert r"\begin{align*}" in prepared
    assert r"\dblInt_{\cS_t}\,\dee{x}\\ &" in prepared
    assert r"\text{file\_1}" in prepared and r"\mathrm{A\_1}" in prepared
    assert math_render.to_omml(parts[0][2]) is not None


def test_frontend_math_macros_match_document_export():
    import json
    import math_render
    from pathlib import Path
    macros = Path(__file__).resolve().parents[2] / "frontend" / "src" / "utils" / "mathMacros.json"
    assert json.loads(macros.read_text(encoding="utf8")) == math_render.MACROS





def test_markdown_export_standardizes_environments_and_expands_macros():
    import math_render
    text = r"Inline \(x^2\). \begin{align*}\dblInt_{\cS_t}\,\dee{x}&=\pdiff{}{x}x\\&=\half\end{align*}"
    output = math_render.markdown(text)
    assert "$x^2$" in output and "\n$$\n" in output
    assert all(command not in output for command in (r"\dblInt", r"\cS", r"\dee", r"\pdiff", r"\half"))
    assert r"\iint" in output and r"\mathcal{S}" in output and r"\partial" in output
    assert math_render.to_omml(next(value for is_math, _, value in math_render.segments(output) if is_math and r"\begin" in value)) is not None


def test_macro_expansion_preserves_missing_arguments():
    import math_render
    assert math_render.expand_macros(r"\dee") == r"\dee"
    assert r"\mathrm{d}" in math_render.expand_macros(r"\dee{x}")


def test_mixed_markdown_escaped_environment_delimiters():
    import math_render
    text = r"\begin{align\*}x&=y\end{align*}"
    parts = list(math_render.segments(text))
    assert len(parts) == 1 and parts[0][0]
    assert math_render.prepare(parts[0][2]) == r"\begin{align*}x&=y\end{align*}"





def test_word_handles_source_macros_and_alignat_environment():
    import math_render
    formulas = [
        r"\set{(x,y)}{x^2+y^2\le1}",
        r"\begin{alignat*}{2}x&=y &&=z\\a&=b &&=c\end{alignat*}",
        r"\iint_{\Atop{x=0}{\rm face}}1+\knowl{./ref}{\text{4.1.3}}+\PageIndex{21}",
        "\\begin{align*}x\\\ny&=z\\end{align*}",
    ]
    for formula in formulas:
        assert math_render.to_omml(formula) is not None


def test_markdown_expansion_continues_after_escaped_newline():
    import math_render
    source = "\\begin{align*}x\\\ny&=\\dee{x}\\end{align*}"
    output = math_render.markdown(source)
    assert r"\dee" not in output and r"\mathrm{d}" in output





def test_markdown_preserves_formula_boundaries_after_multiline_inline_math():
    import math_render
    source = "\\(x+\ny\\) and \\(z^2\\)"
    output = math_render.markdown(source)
    formulas = [value for is_math, _, value in math_render.segments(output) if is_math]
    assert formulas == ["x+ y", "z^2"]







def test_safe_normalization_for_source_escapes_and_standard_tex():
    import math_render
    examples = [
        (r"\\dfrac{x}{\\sqrt{y}}", r"\dfrac{x}{\sqrt{y}}"),
        (r"\root 3 \of {x \root 3 \of {x}}", r"\sqrt[3]{x \sqrt[3]{x}}"),
        (r"15(_x_+40)=900", r"15(x+40)=900"),
        (r"(1)\[x+1\]", r"(1)[x+1]"),
        (r"n\in N^{\*}", r"n\in N^{*}"),
        (r"\begin{cases}x=1\\\\y=2\\end{cases}", r"\begin{cases}x=1\\y=2\end{cases}"),
    ]
    for original, expected in examples:
        assert math_render.prepare(original) == expected
        assert math_render.to_omml(original) is not None

    unaffected = r"\begin{aligned}x_1&=1\\y_2&=2\end{aligned}+\text{file\_1}+\mathrm{A_B}+\operatorname{foo_bar}"
    assert math_render.prepare(unaffected) == unaffected


def test_inline_display_environment_is_treated_as_display_math():
    import math_render
    text = r"$\begin{align*}x&=y\\a&=b\end{align*}$"
    parts = list(math_render.segments(text))
    assert len(parts) == 1 and parts[0][0] and parts[0][1]
    inline = list(math_render.segments(r"$\begin{aligned}x&=y\end{aligned}$"))
    assert len(inline) == 1 and inline[0][0] and not inline[0][1]





def test_text_underscore_and_escaped_unicode_surd_preserve_their_symbols():
    import math_render
    from lxml import etree
    tex = r"S_{\text {_NUA }}" + r"+\boxed{" + "\\" + "\u221a" + "}"
    prepared = math_render.prepare(tex)
    assert r"\text {\_NUA }" in prepared
    assert r"\surd" in prepared
    xml = etree.tostring(math_render.to_omml(tex), encoding="unicode")
    assert "\u221a" in xml and "_NUA" in xml





def test_adjacent_inline_formulas_keep_their_operator_and_round_trip():
    import math_render

    source = r"$①\times 3-$$②\times 2$"
    protected, formulas = math_render.isolate(source)
    assert math_render.restore(protected, formulas) == source
    parts = list(math_render.segments(source))
    assert parts == [(True, False, r"①\times 3-{}②\times 2")]
    assert math_render.to_omml(parts[0][2]) is not None
    assert list(math_render.segments(r"$$x+y$$")) == [(True, True, "x+y")]


def test_cancelto_keeps_crossed_value_arrow_and_result():
    import math_render
    from lxml import etree

    tex = r"\frac{\cancelto{2}{10}}{\cancelto{3}{12}}"
    xml = etree.tostring(math_render.to_omml(tex), encoding="unicode")
    assert xml.count("<m:strikeBLTR") == 2
    assert "\u2197" in xml and ">2<" in xml and ">10<" in xml and ">3<" in xml and ">12<" in xml
    expanded = math_render.expand_macros(tex)
    assert r"\cancelto" not in expanded and r"\cancel" in expanded and r"\nearrow" in expanded


def test_word_export_keeps_cancellation_as_editable_math(client):
    from io import BytesIO
    from zipfile import ZipFile

    document = {"title": "Math", "sections": [{"heading": "H", "paragraphs": [
        r"$\boxed{a}+\cancel{b}+\bcancel{c}+\xcancel{d}$",
    ]}]}
    response = client.post("/api/doc/render", json={"document": document, "format": "docx"})
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        xml = archive.read("word/document.xml").decode("utf8")
    assert "<m:oMath>" in xml and r"\cancel" not in xml
    assert xml.count("<m:strikeBLTR") == 2
    assert xml.count("<m:strikeTLBR") == 2


def test_word_preserves_cancellation_lines_and_boxes():
    import math_render

    ns = {"m": "http://schemas.openxmlformats.org/officeDocument/2006/math"}
    result = math_render.to_omml(r"\boxed{a}+\cancel{b}+\bcancel{c}+\xcancel{d}+\sout{e}")
    boxes = result.xpath(".//m:borderBox", namespaces=ns)
    assert len(boxes) == 5
    assert not boxes[0].xpath("./m:borderBoxPr", namespaces=ns)
    for box in boxes[1:]:
        assert len(box.xpath("./m:borderBoxPr/m:hideTop", namespaces=ns)) == 1
        assert len(box.xpath("./m:borderBoxPr/m:hideBot", namespaces=ns)) == 1
        assert len(box.xpath("./m:borderBoxPr/m:hideLeft", namespaces=ns)) == 1
        assert len(box.xpath("./m:borderBoxPr/m:hideRight", namespaces=ns)) == 1
    assert len(boxes[1].xpath("./m:borderBoxPr/m:strikeBLTR", namespaces=ns)) == 1
    assert len(boxes[2].xpath("./m:borderBoxPr/m:strikeTLBR", namespaces=ns)) == 1
    assert len(boxes[3].xpath("./m:borderBoxPr/m:strikeBLTR", namespaces=ns)) == 1
    assert len(boxes[3].xpath("./m:borderBoxPr/m:strikeTLBR", namespaces=ns)) == 1
    assert len(boxes[4].xpath("./m:borderBoxPr/m:strikeH", namespaces=ns)) == 1


def test_word_preserves_operators_when_tex_only_controls_layout():
    import math_render
    from lxml import etree
    tex = r"\arg(z)=\theta\nonumber\allowbreak"
    xml = etree.tostring(math_render.to_omml(tex), encoding="unicode")
    assert ">arg<" in xml and ">z<" in xml and "\u03b8" in xml





def test_word_preserves_set_difference_operators_and_matrix_exponents():
    import math_render
    from lxml import etree
    tex = r"\mathop{\text{lcm}}[a,b]+|A\backslash B|+\begin{pmatrix}1&2\\3&4\end{pmatrix}^{2016}"
    xml = etree.tostring(math_render.to_omml(tex), encoding="unicode")
    assert ">lcm<" in xml and "\\</m:t>" in xml
    assert "<m:sSup>" in xml and ">2016<" in xml and "<m:m>" in xml


def test_word_still_rejects_malformed_delimiters_with_backslash_symbol():
    import math_render
    import pytest
    with pytest.raises(ValueError):
        math_render.to_omml(r"\(x+\backslash y")





def test_word_rejects_array_specs_that_would_be_silently_printed():
    import math_render
    import pytest
    with pytest.raises(ValueError, match="array column specification"):
        math_render.to_omml(r"\begin{array}{c@{}c}1&2\end{array}")
    with pytest.raises(ValueError, match="array column specification"):
        math_render.to_omml(r"\begin{array}{r *5{c@{~}}c}1&2\end{array}")



def test_escaped_parentheses_inside_dollar_math_are_literal():
    import math_render
    assert math_render.prepare(r"\(") == "("
    assert math_render.prepare(r"\)") == ")"
    assert math_render.to_omml(r"\(") is not None
    assert math_render.to_omml(r"\)") is not None
    assert math_render.prepare(r"\(x") == r"\(x"


def test_duplicate_geometry_symbol_around_nested_formula_is_removed():
    import math_render
    assert math_render.prepare(r"\triangle\(\triangle ABC\\)") == r"\triangle ABC"
    assert math_render.prepare(r"\angle\(\angle ABC\)") == r"\angle ABC"
    assert math_render.to_omml(r"\triangle\(\triangle ABC\\)") is not None
    assert math_render.prepare(r"\triangle\(\angle ABC\)") == r"\triangle\(\angle ABC\)"


def test_nested_delimiters_inside_formula_are_removed_for_both_renderers():
    import math_render
    assert math_render.prepare(r"\(x^2\)") == "x^2"
    assert math_render.prepare(r"\[x^2\]") == "x^2"
    assert math_render.to_omml(r"\(x^2\)") is not None


def test_stray_dollar_does_not_disable_markdown_cleanup():
    import docgen
    assert docgen._clean_markdown("价格 $5 **重点**") == "价格 $5 重点"
