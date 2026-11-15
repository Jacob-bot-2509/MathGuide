"""论文格式解析与切块(纯函数,无模块状态)。

从 research_corpus.py 拆出的原因:这一块只跟“字节 → 页 → 章节 → 切片”有关,
与用户目录、SQLite、索引缓存无关,却占了原文件近五分之一。
拆开后新增格式支持(如 epub/rtf)可以单独改、单独测。
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

from log import get_logger

log = get_logger(__name__)

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)

MAX_PAGES = 600                        # 单篇页数上限(支持百页级长文/学位论文)

CHUNK_CHARS = 900                      # 切片目标长度

_NUMBERED_HEAD_RE = re.compile(r"^\s*(?:#{1,3}\s+|\d+(?:\.\d+)*[\.、)]?\s+)\S")

_KNOWN_HEADINGS = {
    "abstract", "introduction", "related work", "background", "methods",
    "method", "methodology", "results", "discussion", "conclusion",
    "conclusions", "references", "appendix", "acknowledgements",
    "摘要", "引言", "绪论", "相关工作", "背景", "方法", "实验", "结果",
    "讨论", "结论", "参考文献", "附录", "致谢",
}

def _pdf_pages(data: bytes) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    pages: list[tuple[int, str]] = []
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ValueError("PDF 已加密,无法读取") from exc
        for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 单页解析失败不拖垮整篇
                text = ""
            pages.append((index, text))
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 pypdf 失败时仍尝试 pdfium
        pages = []

    if sum(len(text.strip()) for _, text in pages) < 32:
        alt = _pdf_pages_pdfium(data)
        if alt:
            if not pages:
                pages = alt
            else:
                # 逐页取更长的结果,pypdf 对某些 CID 字体会整页返回空
                merged = []
                for i in range(max(len(pages), len(alt))):
                    a = pages[i][1] if i < len(pages) else ""
                    b = alt[i][1] if i < len(alt) else ""
                    merged.append((i + 1, b if len(b) > len(a) else a))
                pages = merged
    return pages

def _pdf_pages_pdfium(data: bytes) -> list[tuple[int, str]]:
    """pypdf 抽不出文字时的兜底:PDFium 对出版商的 CID/子集字体更稳。"""
    try:
        import pypdfium2 as pdfium
    except Exception:  # noqa: BLE001 未安装则跳过
        return []
    doc = None
    try:
        doc = pdfium.PdfDocument(data)
        pages: list[tuple[int, str]] = []
        for index in range(min(len(doc), MAX_PAGES)):
            text = ""
            page = doc[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded() or ""
                finally:
                    text_page.close()
            except Exception:  # noqa: BLE001
                text = ""
            finally:
                page.close()
            pages.append((index + 1, text))
        return pages
    except Exception:  # noqa: BLE001
        return []
    finally:
        if doc is not None:
            doc.close()

def _text_pages(data: bytes) -> list[tuple[int, str]]:
    text = _decode_text(data)
    return _pack_pages(text)

def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "gb18030", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")

def _detect_format(name: str, data: bytes, mime: str) -> str:
    """按文件头判类型,扩展名只兜底:另存的 HTML、改名文件也能正确入库。"""
    head = data[:8192]
    lower_name = (name or "").lower()
    mime = (mime or "").lower()
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "mimetype" in names:
                    try:
                        if zf.read("mimetype").strip() == b"application/epub+zip":
                            return "epub"
                    except (KeyError, OSError):
                        pass
                if "word/document.xml" in names:
                    return "docx"
                if any(n.lower().endswith((".xhtml", ".html", ".htm")) for n in names):
                    return "epub"
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("压缩包已损坏或不是 EPUB/DOCX") from exc
        raise ValueError("暂不支持这种压缩包格式,请上传 PDF/DOCX/EPUB/HTML/RTF/TXT")
    if head.lstrip().startswith(b"{\\rtf"):
        return "rtf"
    probe = head.lstrip().lower()
    if (probe.startswith(b"<!doctype html") or b"<html" in probe[:1500]
            or b"<body" in probe[:2000] or b"<jats" in probe[:3000]):
        return "html"
    if probe.startswith(b"<?xml") or b"<article" in probe[:3000]:
        return "xml"
    if b"\x00" not in head or head.startswith((b"\xff\xfe", b"\xfe\xff")):
        if (mime.startswith("text/")
                or lower_name.endswith((".txt", ".md", ".markdown", ".tex", ".csv",
                                        ".json", ".rtf", ".html", ".htm", ".xml"))):
            return "text"
        # 无扩展名/未知扩展名但确实是可解码文本
        sample = _decode_text(head)
        if not sample.count("\ufffd"):
            return "text"
    if mime == "application/pdf" or lower_name.endswith(".pdf"):
        # 内容不是 PDF 但按 PDF 命名/声明:交给 PDF 解析器给出明确的失败原因
        return "pdf"
    raise ValueError("不支持的文件类型:请上传 PDF、DOCX、EPUB、HTML、RTF 或文本文件")

def _pack_pages(text: str, size: int = 4000) -> list[tuple[int, str]]:
    """无固定页面的文档按段落打包成近似页,保证切片仍能标出位置。"""
    lines = text.splitlines()
    pages: list[tuple[int, str]] = []
    buf: list[str] = []
    used = 0
    for line in lines:
        if buf and used + len(line) + 1 > size:
            pages.append((len(pages) + 1, "\n".join(buf)))
            buf, used = [], 0
        buf.append(line)
        used += len(line) + 1
    if buf or not pages:
        pages.append((len(pages) + 1, "\n".join(buf)))
    return pages

class _HtmlText(HTMLParser):
    _BLOCK = {
        "p", "div", "br", "li", "tr", "table", "section", "article",
        "blockquote", "pre", "title", "figcaption", "caption",
    }
    _HEADING = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in ("script", "style", "noscript"):
            self.skip += 1
            return
        if tag in self._HEADING:
            self.parts.append("\n" + "#" * self._HEADING[tag] + " ")
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in self._HEADING or tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)

def _html_text(data: bytes) -> str:
    parser = _HtmlText()
    try:
        parser.feed(_decode_text(data))
    except Exception:  # noqa: BLE001 解析失败时退回正则去标签
        raw = re.sub(r"<[^>]+>", " ", _decode_text(data))
        return re.sub(r"\s+", " ", raw)
    text = parser.text()
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

def _docx_pages(data: bytes) -> list[tuple[int, str]]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(data))
    body = doc.element.body
    parts: list[str] = []
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, doc)
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower()
            level = 0
            if style.startswith("heading"):
                digits = re.findall(r"\d+", style)
                level = min(4, int(digits[0])) if digits else 1
            parts.append(("#" * level + " " if level else "") + text)
        elif tag == "tbl":
            table = Table(child, doc)
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
    return _pack_pages("\n\n".join(parts))

def _epub_pages(data: bytes) -> list[tuple[int, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith((".xhtml", ".html", ".htm"))]
        names.sort()
        chunks = []
        for name in names[:400]:
            try:
                chunks.append(_html_text(zf.read(name)))
            except (KeyError, OSError):
                continue
    return _pack_pages("\n\n".join(c for c in chunks if c.strip()))

def _rtf_text(data: bytes) -> str:
    raw = data.decode("latin-1", errors="replace")
    # 丢弃 {\*...} 与超链接等控制组
    while True:
        new = re.sub(r"\{\\\*[^{}]*\}", "", raw)
        if new == raw:
            break
        raw = new

    def unicode_escape(match: re.Match[str]) -> str:
        code = int(match.group(1))
        return chr(code) if 0 <= code <= 0x10FFFF else ""

    raw = re.sub(r"\\u(-?\d+)\??", lambda m: unicode_escape(m), raw)
    raw = re.sub(r"\\'([0-9a-fA-F]{2})",
                 lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", errors="replace"),
                 raw)
    raw = raw.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    return re.sub(r"\n{3,}", "\n\n", raw).strip()

def _extract_pages(kind: str, data: bytes, name: str) -> list[tuple[int, str]]:
    if kind == "pdf":
        return _pdf_pages(data)
    if kind == "docx":
        return _docx_pages(data)
    if kind == "epub":
        return _epub_pages(data)
    if kind == "rtf":
        return _pack_pages(_rtf_text(data))
    if kind in ("html", "xml"):
        return _pack_pages(_html_text(data))
    return _text_pages(data)

def _extract_doi(pages: list[tuple[int, str]]) -> str:
    """从正文前 3 页找 DOI;找不到返回空串。"""
    for _, text in pages[:3]:
        for match in _DOI_RE.finditer(text):
            doi = match.group(0).rstrip(".,;)]}").lower()
            if len(doi) >= 8:
                return doi[:200]
    return ""

def _clean_line(line: str) -> str:
    return re.sub(r"[ \t]+", " ", line).strip()

def _is_heading(line: str) -> bool:
    s = _clean_line(line)
    if not s or len(s) > 80:
        return False
    if _NUMBERED_HEAD_RE.match(s):
        return True
    low = s.lower().strip(":：")
    if low in _KNOWN_HEADINGS:
        return True
    # 全大写短行(英文论文常见),排除公式与句子
    if 3 <= len(s) <= 60 and re.fullmatch(r"[A-Z][A-Z0-9 \-&/:]+", s) and not s.endswith("."):
        return True
    return False


@dataclass

class Section:
    title: str
    page_start: int
    page_end: int
    text: str = ""
    # 逐行保留页码:切片页码要精确到行所在页,不能只用章节起止页
    lines: list[tuple[int, str]] = field(default_factory=list)

def _heading_level(title: str) -> int:
    """按编号估算层级:"1" → 1,"1.2" → 2;无编号(Abstract 等)按一级。"""
    m = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    return m.group(1).count(".") + 1 if m else 1

def _sections(pages: list[tuple[int, str]]) -> list[Section]:
    sections: list[Section] = []
    first = pages[0][0] if pages else 1
    cur = Section("正文", first, first)

    def flush() -> None:
        text = "\n".join(line for _, line in cur.lines).strip()
        if text:
            cur.text = text
            sections.append(cur)

    for page_no, text in pages:
        for raw in text.splitlines():
            line = _clean_line(raw)
            if not line:
                continue
            if _is_heading(line):
                flush()
                cur = Section(line[:80], page_no, page_no)
                continue
            cur.lines.append((page_no, line))
            cur.page_end = page_no
    flush()
    if sections:
        return sections
    flat: list[tuple[int, str]] = [
        (page_no, _clean_line(line))
        for page_no, text in pages
        for line in text.splitlines() if _clean_line(line)
    ]
    return [Section("全文", flat[0][0] if flat else 1, flat[-1][0] if flat else 1,
                    "\n".join(line for _, line in flat), flat)]

def _split_long(text: str, limit: int) -> list[str]:
    """超长段落按句末标点切;仍超长则硬切,保证不产生巨块"""
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[。！？.!?])\s+", text)
    out: list[str] = []
    buf = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(sentence[i:i + limit] for i in range(0, len(sentence), limit))
        elif len(buf) + len(sentence) + 1 <= limit:
            buf = f"{buf} {sentence}".strip()
        else:
            if buf:
                out.append(buf)
            buf = sentence
    if buf:
        out.append(buf)
    return out

def _chunk_section(section: Section) -> list[tuple[str, int, int]]:
    """章节 → [(正文, 起始页, 结束页)];页码按实际行来源记录。"""
    chunks: list[tuple[str, int, int]] = []
    buf: list[tuple[int, str]] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        text = "\n".join(line for _, line in buf).strip()
        if text:
            chunks.append((text, buf[0][0], buf[-1][0]))
        buf = []
        size = 0

    for page_no, line in section.lines:
        pieces = _split_long(line, CHUNK_CHARS) if len(line) > CHUNK_CHARS else [line]
        for piece in pieces:
            if buf and size + len(piece) + 1 > CHUNK_CHARS:
                flush()
            buf.append((page_no, piece))
            size += len(piece) + 1
    flush()
    return chunks
