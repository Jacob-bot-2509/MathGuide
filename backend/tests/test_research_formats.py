"""多格式入库:按文件头识别并抽取正文,不依赖扩展名。"""
from __future__ import annotations

import io
import zipfile

import pytest

import research_corpus as rc
import research_formats as rf

DOCX_TEXT = "Introduction\nWe study quantum error correction in trapped ions."
HTML_TEXT = "Introduction\nA short HTML paper about spectral gaps."
EPUB_TEXT = "Introduction\nAn EPUB chapter about modular forms."
RTF_TEXT = "Introduction\nAn RTF paper about Ricci flow."


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    rc._indexes.clear()
    rc._index_paths.clear()
    yield tmp_path
    rc._indexes.clear()
    rc._index_paths.clear()


def test_detect_format_by_content_not_extension():
    assert rc._detect_format("paper.txt", b"%PDF-1.7\n...", "text/plain") == "pdf"
    assert rc._detect_format("saved.pdf", b"<!doctype html><html><body>x</body></html>",
                             "application/pdf") == "html"
    assert rc._detect_format("note", b"{\\rtf1\\ansi hello}", "") == "rtf"
    assert rc._detect_format("paper.bin", "纯文本论文".encode("utf-8"), "") == "text"


def test_unknown_binary_rejected():
    with pytest.raises(ValueError):
        rc._detect_format("x.bin", b"\x00\x01\x02\x03binary", "application/octet-stream")


def test_docx_html_epub_rtf_ingest(corpus):
    from docx import Document

    doc = Document()
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph(DOCX_TEXT.split("\n")[1])
    buf = io.BytesIO()
    doc.save(buf)
    docx_res = rc._ingest("u-fmt", "paper.docx", buf.getvalue(),
                          "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert docx_res["chunks"] >= 1

    html_res = rc._ingest(
        "u-fmt", "paper.html",
        f"<html><body><h1>Introduction</h1><p>{HTML_TEXT.splitlines()[1]}</p></body></html>".encode(),
        "text/html")
    assert html_res["chunks"] >= 1

    epub = io.BytesIO()
    with zipfile.ZipFile(epub, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("OEBPS/ch1.xhtml",
                    f"<html><body><h1>Introduction</h1><p>{EPUB_TEXT.splitlines()[1]}</p></body></html>")
    epub_res = rc._ingest("u-fmt", "paper.epub", epub.getvalue(), "application/epub+zip")
    assert epub_res["chunks"] >= 1

    rtf_res = rc._ingest(
        "u-fmt", "paper.rtf",
        ("{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Times;}}"
         "\\f0\\fs24 Introduction\\par An RTF paper about Ricci flow.}").encode(),
        "application/rtf")
    assert rtf_res["chunks"] >= 1

    index = rc._get_index("u-fmt")
    text = "\n".join(chunk.text for chunk in index.chunks)
    assert "quantum error correction" in text
    assert "spectral gaps" in text
    assert "modular forms" in text
    assert "Ricci flow" in text


def test_long_document_paginates_and_indexes(corpus):
    pages = rc._pack_pages("\n".join(
        f"Paragraph {i} about long proofs and spectral estimates." for i in range(12000)))
    assert len(pages) > 80
    text = "\n\n".join(t for _, t in pages)
    res = rc._ingest("u-long", "long.txt", text.encode("utf-8"), "text/plain")
    assert res["pages"] == len(pages)
    assert res["chunks"] >= 50


# ---------------------------------------------------------------------------
# 追加:格式识别的全矩阵、各解析器的降级路径、切片边界。
# 为什么重要:用户上传的字节来自各种渠道(另存的网页、改名文件、损坏包),
# 识别错一次不是"格式不对"而是整篇论文 500/0 命中,所以每条都要断言"落到哪种格式"。
# ---------------------------------------------------------------------------

def _pdf_bytes(text: str) -> bytes:
    """手搓一个最小合法 PDF(不引入 reportlab):单页 + Helvetica 一行字。

    真实 PDF 才能验证 pypdf 抽取路径,否则 _pdf_pages 只测到异常兜底。
    """
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(b"trailer\n<</Size " + str(len(objs) + 1).encode()
              + b"/Root 1 0 R>>\nstartxref\n" + str(xref).encode() + b"\n%%EOF\n")
    return out.getvalue()


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def test_detect_format_reads_zip_container_kind():
    """zip 家族(mimetype / word/document.xml / xhtml)必须分得出 epub 与 docx。

    判据是包内结构而不是扩展名:用户把 .docx 改名成 .zip 上传时,
    只有按结构判才能进对解析器。
    """
    epub = _zip_bytes({
        "mimetype": b"application/epub+zip",
        "OEBPS/ch1.xhtml": b"<html><body><p>chapter</p></body></html>",
    })
    assert rf._detect_format("book.zip", epub, "application/zip") == "epub"

    docx = _zip_bytes({"word/document.xml": b"<w:document/>"})
    assert rf._detect_format("paper.zip", docx, "") == "docx"

    # 无 mimetype 也无 document.xml,但含 xhtml 章节:按 epub 处理
    loose = _zip_bytes({"OEBPS/ch1.htm": b"<html><body><p>x</p></body></html>"})
    assert rf._detect_format("book.bin", loose, "") == "epub"

    # 合法的 zip 但不是支持的文档格式:明确拒绝,不要落到"未知二进制"
    only_text = _zip_bytes({"readme.txt": b"hello"})
    with pytest.raises(ValueError):
        rf._detect_format("bundle.zip", only_text, "application/zip")

    # 头部像 zip 但内容损坏:必须报"压缩包损坏",不能抛 BadZipFile 给上层
    corrupt = b"PK\x03\x04" + b"\x00" * 32
    with pytest.raises(ValueError):
        rf._detect_format("bad.zip", corrupt, "")


def test_detect_format_magic_wins_over_extension_and_mime():
    """魔数与扩展名冲突时以内容为准;内容不是 PDF 但声称 PDF 时仍交 PDF 解析器。

    后半句是刻意的:交给 pypdf 报"这份 PDF 坏了",比在这里说"不支持的类型"更好懂。
    """
    assert rf._detect_format("renamed.txt", _pdf_bytes("x"), "text/plain") == "pdf"
    assert rf._detect_format("paper.pdf", b"%PDF-1.7\nbody", "") == "pdf"
    # 二进制内容 + 声明 PDF:判 pdf,由 PDF 解析器给出失败原因(而不是"不支持的类型")
    assert rf._detect_format("paper.pdf", b"\x00\x01\x02 not really pdf", "") == "pdf"
    assert rf._detect_format("x", b"\x00\x01junk", "application/pdf") == "pdf"
    # 可解码的纯文本即使名叫 .pdf 也仍按文本处理(前面已判出 text)
    assert rf._detect_format("paper.pdf", b"just plain words here", "") == "text"
    assert rf._detect_format("no-extension", b"{\\rtf1\\ansi hi}", "") == "rtf"
    # 前后有空白的 rtf 头也算 rtf(lstrip 后判断)
    assert rf._detect_format("x.dat", b"\n  {\\rtf1 and text}", "") == "rtf"


def test_detect_format_html_xml_and_text_paths():
    assert rf._detect_format("p", b"<!DOCTYPE html><html></html>", "") == "html"
    assert rf._detect_format("p", b"<html><body>x</body></html>", "") == "html"
    assert rf._detect_format("p", b"<jats:article/>", "") == "html"
    assert rf._detect_format("p", b'<?xml version="1.0"?><root/>', "") == "xml"
    assert rf._detect_format("p", b"<article><p>x</p></article>", "") == "xml"
    # 无 BOM、无扩展名、无 mime,但确实可解码:当文本
    assert rf._detect_format("", "中文正文 about proofs".encode(), "") == "text"
    # 扩展名白名单兜底
    assert rf._detect_format("notes.md", b"# Title", "") == "text"
    assert rf._detect_format("draft.tex", b"\\section{X}", "") == "text"
    # mime 声明 text/* 且无 NUL:走文本
    assert rf._detect_format("data", b"plain ascii", "text/csv") == "text"


def test_detect_format_rejects_binary_without_known_magic():
    """未知二进制必须 400,不能当文本入库(否则索引里塞满乱码)。"""
    with pytest.raises(ValueError):
        rf._detect_format("x.bin", b"\x00\x01\x02\x03binary", "application/octet-stream")
    with pytest.raises(ValueError):
        rf._detect_format("x", b"\x00\xff\xfe\x01", "")


def test_decode_text_handles_bom_gb18030_and_undecodable_bytes():
    """编码探测顺序:utf-16 BOM → utf-8 → gb18030 → big5 → 替换。

    Windows 上导出的中文论文多是 GBK/GB18030,解错整篇都是乱码,
    所以这里断言的是"具体解码成了哪个字符串",不是"没抛异常"。
    """
    assert rf._decode_text("\ufeff正文".encode()) == "正文"
    assert rf._decode_text("正文".encode("utf-16")) == "正文"
    # BOM 是 utf-16 但字节不合法(奇数长度):退回后续编码链,不抛
    assert "\ufffd" in rf._decode_text(b"\xff\xfe\x00")
    # 合法 utf-16(带 BOM 的小端)
    assert rf._decode_text(b"\xff\xfe" + "光谱".encode("utf-16-le")) == "光谱"
    assert rf._decode_text("中文".encode("gb18030")) == "中文"
    # 三种编码全部失败:替换字符兜底,不抛 UnicodeDecodeError
    assert rf._decode_text(b"\xff\xff\xff") == "\ufffd\ufffd\ufffd"


def test_pack_pages_boundaries_around_size_limit():
    """打包边界:正好等于上限不切页,超一个字符才切。

    切早了会让页码定位偏,切晚了则单页过大、切片页码全落在同一页。
    """
    assert rf._pack_pages("x" * 4000) == [(1, "x" * 4000)]
    two = rf._pack_pages("x" * 4000 + "\ny")
    assert [page for page, _ in two] == [1, 2]
    assert two[0][1] == "x" * 4000
    assert two[1][1] == "y"
    # 空文本也要给出第 1 页,否则下游页码计算会拿到空列表
    assert rf._pack_pages("") == [(1, "")]
    # 自定义上限:逐行累加,超了就换页
    assert rf._pack_pages("aa\nbb\ncc", size=6) == [(1, "aa\nbb"), (2, "cc")]


def test_pdf_pages_extracts_real_text_per_page():
    """真 PDF 走 pypdf 抽文本:页码从 1 开始,文本可检索。

    这条是"PDF 论文能进检索"的地基,只用假字节测不出来。
    """
    pages = rf._pdf_pages(_pdf_bytes("Hello spectral gaps in modular forms"))
    assert [page for page, _ in pages] == [1]
    assert "spectral gaps" in pages[0][1]


def test_pdf_pages_degrades_to_empty_list_on_corrupt_or_encrypted_input():
    """损坏/加密 PDF 必须返回空页表,不能把 pypdf 的内部异常抛给接口层。

    上层据此判"没有正文"给 400;这里抛异常就会变成 500。
    """
    assert rf._pdf_pages(b"not a pdf at all") == []
    assert rf._pdf_pages(b"") == []
    assert rf._pdf_pages_pdfium(b"junk bytes") == []


def test_pdf_pages_falls_back_to_pdfium_when_pypdf_text_is_thin(monkeypatch):
    """pypdf 抽到的字太少(<32)时交给 pdfium,并按页取更长的那份。

    出版商的 CID 子集字体会让 pypdf 整页返回空;不回退就是"上传成功但搜不到"。
    """
    monkeypatch.setattr(rf, "_pdf_pages_pdfium",
                        lambda data: [(1, "y" * 50), (2, "z" * 50)])
    merged = rf._pdf_pages(_pdf_bytes("ab"))  # pypdf 只拿到 2 个字
    assert [page for page, _ in merged] == [1, 2]
    assert merged[0][1] == "y" * 50
    assert merged[1][1] == "z" * 50

    # pypdf 一页都没解析出来:直接用 pdfium 的结果
    monkeypatch.setattr(rf, "_pdf_pages_pdfium", lambda data: [(1, "from pdfium")])
    assert rf._pdf_pages(b"garbage") == [(1, "from pdfium")]

    # pdfium 也抽不出东西:保留 pypdf 的原结果(不能把空结果覆盖成空列表)
    monkeypatch.setattr(rf, "_pdf_pages_pdfium", lambda data: [])
    assert rf._pdf_pages(_pdf_bytes("ab"))[0][1].strip() == "ab"


def test_pdf_pages_pdfium_reads_real_pdf():
    """兜底解析器本身也要能读真文件,否则回退是死路。"""
    pages = rf._pdf_pages_pdfium(_pdf_bytes("pdfium reads this"))
    assert [page for page, _ in pages] == [1]
    assert "pdfium reads this" in pages[0][1]


def test_html_text_skips_script_and_marks_headings():
    """HTML 里的 script/style 文本不能进索引,标题要保持层级(# 号)。

    噪声进正文会污染检索;标题层级丢了,章节定位就全归"正文"。
    """
    text = rf._html_text(
        b"<html><body><h1>Introduction</h1><p>Body text.</p>"
        b"<script>var x = 1;</script><style>p{color:red}</style>"
        b"<h2>2 Methods</h2><p>More.</p></body></html>")
    assert "# Introduction" in text
    assert "## 2 Methods" in text
    assert "var x" not in text
    assert "color:red" not in text
    assert "Body text." in text


def test_html_text_falls_back_to_regex_when_parser_explodes(monkeypatch):
    """解析器异常时退回正则去标签:畸形 HTML 也要能入库,而不是 500。"""

    class Boom:
        def feed(self, data):
            raise RuntimeError("parser broken")

        def text(self):
            return ""

    monkeypatch.setattr(rf, "_HtmlText", Boom)
    text = rf._html_text(b"<p>alpha</p><p>beta</p>")
    assert text.strip() == "alpha beta"





def test_docx_pages_keeps_heading_level_and_tables():
    """DOCX 的标题样式 → markdown 层级,表格 → 竖线分隔的行。

    学位论文的结论常在表格里,表格丢了等于丢结果。
    """
    from docx import Document

    doc = Document()
    doc.add_heading("Introduction", level=2)
    doc.add_paragraph("Body paragraph about proofs.")
    doc.add_paragraph("")  # 空段落不应产生空行
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "n"
    table.cell(0, 1).text = "value"
    table.cell(1, 0).text = "3"
    table.cell(1, 1).text = "1.5"
    buf = io.BytesIO()
    doc.save(buf)

    pages = rf._docx_pages(buf.getvalue())
    text = "\n".join(t for _, t in pages)
    assert "## Introduction" in text
    assert "Body paragraph about proofs." in text
    assert "n | value" in text
    assert "3 | 1.5" in text


def test_epub_pages_reads_chapters_in_name_order():
    """EPUB 按包内文件名排序读章节;非 HTML 条目忽略。"""
    epub = _zip_bytes({
        "mimetype": b"application/epub+zip",
        "OEBPS/ch2.xhtml": b"<html><body><p>second chapter</p></body></html>",
        "OEBPS/ch1.htm": b"<html><body><p>first chapter</p></body></html>",
        "OEBPS/ch3.html": b"<html><body><p>third chapter</p></body></html>",
        "OEBPS/cover.jpg": b"\xff\xd8\xff",
    })
    text = "\n".join(t for _, t in rf._epub_pages(epub))
    assert text.index("first chapter") < text.index("second chapter")
    assert text.index("second chapter") < text.index("third chapter")


def test_rtf_text_strips_control_groups_and_decodes_escapes():
    """RTF 控制组要摘干净:\\* 组、\\uN、\\'hh 转义、\\par 换行。

    少摘一层就会把 \\fonttbl 之类的元数据当正文入库。
    """
    raw = (b"{\\rtf1\\ansi\\deff0 {\\fonttbl {\\f0 Times;}}"
           b"{\\*\\hyphenation keep} \\f0 \\u26009?\\'e9 proof \\par second line}")
    text = rf._rtf_text(raw)
    assert "proof" in text
    assert "second line" in text
    assert "fonttbl" not in text
    assert "hyphenation" not in text
    assert "\\par" not in text
    assert "{" not in text and "}" not in text
    assert "é" in text
    # 超出 Unicode 范围的 \u 值直接丢弃,不抛 chr() 的 ValueError
    assert " ".join(
        rf._rtf_text(b"{\\rtf1 \\u-5 bad \\u1114112 also bad}").split()) == "bad also bad"


def test_extract_pages_dispatches_every_kind():
    """六种 kind 各自落到对应解析器:分派错了就是"上传成功、正文为空"。"""
    from docx import Document

    doc = Document()
    doc.add_paragraph("docx body")
    buf = io.BytesIO()
    doc.save(buf)

    assert rf._extract_pages("pdf", _pdf_bytes("pdf body"), "a.pdf")[0][1].strip() == "pdf body"
    assert "docx body" in rf._extract_pages("docx", buf.getvalue(), "a.docx")[0][1]
    assert "epub body" in rf._extract_pages(
        "epub", _zip_bytes({"ch1.xhtml": b"<html><body><p>epub body</p></body></html>"}),
        "a.epub")[0][1]
    assert "rtf body" in rf._extract_pages("rtf", b"{\\rtf1 rtf body}", "a.rtf")[0][1]
    assert "html body" in rf._extract_pages(
        "html", b"<html><body><p>html body</p></body></html>", "a.html")[0][1]
    assert "xml body" in rf._extract_pages(
        "xml", b"<article><p>xml body</p></article>", "a.xml")[0][1]
    assert "text body" in rf._extract_pages("text", b"text body", "a.txt")[0][1]


def test_extract_doi_only_trusts_first_three_pages():
    """DOI 只在前 3 页找;参考文献里的 DOI 大量误命中,取到就污染去重。"""
    assert rf._extract_doi([(1, "see 10.1234/ABC.def.")]) == "10.1234/abc.def"
    assert rf._extract_doi([(1, "no doi here")]) == ""
    # 太短的匹配(长度 < 8)不算 DOI
    assert rf._extract_doi([(1, "10.1/x")]) == ""
    # 第 4 页的 DOI 不采信
    assert rf._extract_doi([(1, ""), (2, ""), (3, ""), (4, "10.1234/late")]) == ""


def test_is_heading_matches_numbered_known_and_allcaps_only():
    """标题判定:编号 / 已知节名 / 短全大写;超过 80 字与完整句子必须排除。

    判宽了会把正文句子当标题切碎章节;判窄了整篇只剩一个"正文"块。
    """
    assert rf._is_heading("2 Methods")
    assert rf._is_heading("3.1. Data Collection")
    assert rf._is_heading("# Introduction")
    assert rf._is_heading("Abstract:")
    assert rf._is_heading("  结论  ")
    assert rf._is_heading("RESULTS AND DISCUSSION")   # 英文论文的短全大写行
    assert not rf._is_heading("")
    assert not rf._is_heading("x" * 90)
    # 以句号结尾的整句不是标题
    assert not rf._is_heading("THIS IS A WHOLE SENTENCE.")
    # 含小写的一般句子不是标题
    assert not rf._is_heading("We ran three experiments and got results")


def test_heading_level_uses_numbering_depth():
    """章节层级按编号点号数算:无编号的一律一级。

    层级错了,前端大纲会把 1.2 挂到 1 的同级,目录就乱了。
    """
    assert rf._heading_level("1 Introduction") == 1
    assert rf._heading_level("1.2 Data") == 2
    assert rf._heading_level("2.3.4 Results") == 3
    assert rf._heading_level("Abstract") == 1


def test_sections_splits_on_headings_and_tracks_page_range():
    """按标题切章,并记录起止页:页码来自实际行,不能只用章节起页。"""
    pages = [
        (1, "1 Introduction\nwe study gaps\nin spectra"),
        (2, "1.1 Background\nprior work\n2 Methods\n我们做实验"),
        (3, "3 Results\nkey table"),
    ]
    sections = rf._sections(pages)
    assert [s.title for s in sections] == [
        "1 Introduction", "1.1 Background", "2 Methods", "3 Results"]
    assert (sections[0].page_start, sections[0].page_end) == (1, 1)
    assert sections[0].text == "we study gaps\nin spectra"
    assert (sections[1].page_start, sections[1].page_end) == (2, 2)
    assert sections[3].text == "key table"
    assert [rf._heading_level(s.title) for s in sections] == [1, 2, 1, 1]
    # 逐行页码要留住,切片页码靠它
    assert sections[2].lines == [(2, "我们做实验")]


def test_sections_falls_back_to_single_fulltext_block():
    """只剩标题行或整篇空白时退化成单一"全文"块,不能让调用方拿到空列表。

    标题密集的学位论文封面页会走到这条,空列表会让后续切片直接 0 命中。
    """
    headings_only = rf._sections([(1, "ABSTRACT"), (2, "CONTENTS")])
    assert len(headings_only) == 1
    assert headings_only[0].title == "全文"
    assert headings_only[0].page_start == 1 and headings_only[0].page_end == 2
    assert headings_only[0].text == "ABSTRACT\nCONTENTS"

    empty = rf._sections([])
    assert len(empty) == 1
    assert empty[0].title == "全文"
    assert (empty[0].page_start, empty[0].page_end) == (1, 1)
    assert empty[0].text == ""


def test_split_long_boundaries_and_hard_cut():
    """切块边界:等于上限不切,超一个字符才切;无标点的长串硬切。

    界限差 1 就会把正好 900 字的段落切成两半,引用区里段落被拦腰截断。
    """
    assert rf._split_long("", 10) == [""]
    assert rf._split_long("x" * 10, 10) == ["x" * 10]
    pieces = rf._split_long("x" * 11, 10)
    assert pieces == ["x" * 10, "x"]
    assert all(len(p) <= 10 for p in pieces)
    # 有句末标点时按句切并按上限打包
    assert rf._split_long("aa. bb. cc.", 7) == ["aa. bb.", "cc."]
    # 单句超长:先吐出已攒的缓冲,再硬切
    assert rf._split_long("aa. " + "y" * 12, 5) == ["aa.", "yyyyy", "yyyyy", "yy"]
    # 单句正好等于上限时不需要硬切
    assert rf._split_long("aa. bbbbb", 5) == ["aa.", "bbbbb"]


def test_chunk_section_splits_overlong_lines_and_keeps_pages():
    """切片:单行超 CHUNK_CHARS 要切成多块,页码按行来源标注。

    不切会让一个 chunk 变成几万字,检索片段与引用页码双双失效。
    """
    section = rf.Section("1 Introduction", 2, 5, lines=[
        (2, "short line"),
        (3, "z" * (rf.CHUNK_CHARS + 50)),
        (5, "tail"),
    ])
    chunks = rf._chunk_section(section)
    assert all(len(text) <= rf.CHUNK_CHARS for text, _, _ in chunks)
    assert chunks[0] == ("short line", 2, 2)
    # 长行被切开后,余下的片段与新片段都带原行的页码
    assert {page for _, start, end in chunks for page in (start, end)} <= {2, 3, 5}
    assert chunks[-1][2] == 5
    # 空章节不产生空块
    assert rf._chunk_section(rf.Section("empty", 1, 1)) == []


def test_pdf_pages_maps_reader_failures(monkeypatch):
    """pypdf 的三种失败要映射成不同结果:加密 → ValueError(提示换文件),
    单页解析失败 → 该页留空但继续,其他 ValueError → 原样上抛。

    真实 pypdf 现在用返回值(而非异常)表示"密码不对",所以这里用桩把
    契约钉住:哪天升级把它变回异常,映射关系仍然正确。
    """
    import pypdf

    class EncryptedReader:
        is_encrypted = True

        def __init__(self, stream):
            pass

        def decrypt(self, password):
            raise RuntimeError("bad password")

    monkeypatch.setattr(pypdf, "PdfReader", EncryptedReader)
    with pytest.raises(ValueError):
        rf._pdf_pages(b"%PDF-1.4 encrypted")

    class FlakyPage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            if self._text is None:
                raise RuntimeError("broken font")
            return self._text

    class FlakyReader:
        is_encrypted = False

        def __init__(self, stream):
            self.pages = [FlakyPage(None), FlakyPage("second page text long enough")]

    monkeypatch.setattr(pypdf, "PdfReader", FlakyReader)
    # 兜底解析器也请离开(否则它会来抢结果)
    monkeypatch.setattr(rf, "_pdf_pages_pdfium", lambda data: [])
    pages = rf._pdf_pages(b"%PDF-1.4 flaky")
    assert pages[0] == (1, "")            # 坏页留空,不中断
    assert pages[1][1] == "second page text long enough"

    class BoomReader:
        is_encrypted = False

        def __init__(self, stream):
            raise ValueError("坏 PDF")

    monkeypatch.setattr(pypdf, "PdfReader", BoomReader)
    with pytest.raises(ValueError):
        rf._pdf_pages(b"%PDF-1.4 boom")


def test_pdfium_fallback_reports_nothing_when_library_missing_or_page_breaks(monkeypatch):
    """兜底解析器的两条降级:库没装、单页取文本失败。

    两者都必须返回空/空文本,绝不能让上传接口 500。
    """
    import sys

    import pypdfium2

    monkeypatch.setitem(sys.modules, "pypdfium2", None)   # 模拟"未安装"
    assert rf._pdf_pages_pdfium(b"%PDF-1.4") == []
    monkeypatch.setitem(sys.modules, "pypdfium2", pypdfium2)  # 装回来测单页失败

    class BrokenPage:
        def get_textpage(self):
            raise RuntimeError("textpage failed")

        def close(self):
            pass

    class FakeDoc:
        def __init__(self, data):
            pass

        def __len__(self):
            return 1

        def __getitem__(self, index):
            return BrokenPage()

        def close(self):
            pass

    monkeypatch.setattr(pypdfium2, "PdfDocument", FakeDoc)
    assert rf._pdf_pages_pdfium(b"%PDF-1.4") == [(1, "")]


def test_zip_entry_read_failures_do_not_break_bundle_parsing(monkeypatch):
    """包内条目读失败(mimetype 读不到 / 某章缺失)要能继续。

    下载/上传竞态会留下"名字在表里、内容读不出"的包;
    这时仍应按其余结构判 epub/docx,而不是整篇报错。
    """
    import zipfile as zf

    original_read = zf.ZipFile.read

    def fake_read(self, name, *args, **kwargs):
        if name in ("mimetype", "OEBPS/ch1.xhtml"):
            raise KeyError(name)
        return original_read(self, name, *args, **kwargs)

    bundle = _zip_bytes({
        "mimetype": b"application/epub+zip",
        "word/document.xml": b"<w:document/>",
        "OEBPS/ch1.xhtml": b"<html><body><p>lost chapter</p></body></html>",
        "OEBPS/ch2.xhtml": b"<html><body><p>kept chapter</p></body></html>",
    })
    monkeypatch.setattr(zf.ZipFile, "read", fake_read)
    # mimetype 读不到 → 继续按结构判,docx 标记优先于 epub 的 xhtml 兜底
    assert rf._detect_format("bundle.zip", bundle, "") == "docx"
    # 一章读不出 → 其余章节仍在
    text = "\n".join(t for _, t in rf._epub_pages(bundle))
    assert "kept chapter" in text
    assert "lost chapter" not in text


