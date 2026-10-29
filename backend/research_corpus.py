"""
科研语料库:按用户隔离的论文全文索引与检索。

原理:
- 入库:PDF/文本 → 按页抽正文 → 识别章节标题建节点树 → 章节内切片 → 存 SQLite;
- 检索:BM25(字面) + embedding(语义) 各排一份 → RRF 融合 → 章节树节点先筛后取;
- 隔离:每个 uid 一个目录与一个 SQLite,文件、切片、向量缓存互不相通。

外部检索源(arXiv / OpenAlex / ...)不在这里,仍由 rag.research 负责;
本模块只解决「用户自己的论文能不能被搜到、能不能定位到页」。

未配置 MG_EMBED_* 时自动退化为纯 BM25;embedding 服务失败也退化为 BM25,
不阻断检索。章节树目前用启发式标题识别 + 摘要式节点文本,不调用 LLM;
后续可在 nodes 上加 LLM 摘要与走树,不影响现有接口。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from auth import require_auth
from http_utils import read_json_object
from rag import embed as embed_mod
from rag import llm as llm_mod
from rate_limit import SlidingWindowLimiter

DATA_DIR = Path(__file__).resolve().parent / "data" / "research"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 默认单文件 100MB(MG_RESEARCH_MAX_UPLOAD_MB 可调)
MAX_DOCS = 200                         # 默认每用户论文数上限(MG_RESEARCH_MAX_DOCS 可调)
MAX_PAGES = 600                        # 单篇页数上限(支持百页级长文/学位论文)
TEMP_DOC_LIMIT = 200                   # 临时论文(浏览历史)上限,超出淘汰最旧无批注记录
CHUNK_CHARS = 900                      # 切片目标长度
SUMMARY_CHARS = 220                    # 节点摘要长度
SNIPPET_CHARS = 320

# 上传与检索都触发磁盘/embedding 开销,按用户限流(聊天另有自己的限流器)
_upload_limiter = SlidingWindowLimiter(4, 300)    # 5 分钟最多 4 篇
_search_limiter = SlidingWindowLimiter(30, 60)    # 1 分钟最多 30 次检索

# BM25 参数(业界默认值)
K1 = 1.2
B = 0.75
RRF_K = 60

_UID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_NUMBERED_HEAD_RE = re.compile(r"^\s*(?:#{1,3}\s+|\d+(?:\.\d+)*[\.、)]?\s+)\S")
_KNOWN_HEADINGS = {
    "abstract", "introduction", "related work", "background", "methods",
    "method", "methodology", "results", "discussion", "conclusion",
    "conclusions", "references", "appendix", "acknowledgements",
    "摘要", "引言", "绪论", "相关工作", "背景", "方法", "实验", "结果",
    "讨论", "结论", "参考文献", "附录", "致谢",
}


def _max_upload_bytes() -> int:
    raw = os.getenv("MG_RESEARCH_MAX_UPLOAD_MB", "").strip()
    try:
        mb = int(raw)
    except ValueError:
        return MAX_UPLOAD_BYTES
    return mb * 1024 * 1024 if 1 <= mb <= 200 else MAX_UPLOAD_BYTES


def _max_docs() -> int:
    raw = os.getenv("MG_RESEARCH_MAX_DOCS", "").strip()
    try:
        value = int(raw)
    except ValueError:
        return MAX_DOCS
    return value if 1 <= value <= 5000 else MAX_DOCS


def _max_total_bytes() -> int:
    raw = os.getenv("MG_RESEARCH_MAX_TOTAL_MB", "").strip()
    try:
        mb = int(raw)
    except ValueError:
        return 500 * 1024 * 1024
    return mb * 1024 * 1024 if 1 <= mb <= 10240 else 500 * 1024 * 1024


def _safe_uid(uid: str) -> str:
    return _UID_RE.sub("_", uid)[:80] or "anonymous"


def _user_dir(uid: str) -> Path:
    path = DATA_DIR / _safe_uid(uid)
    (path / "files").mkdir(parents=True, exist_ok=True)
    return path


def _db_path(uid: str) -> Path:
    return _user_dir(uid) / "index.sqlite3"


def _connect(uid: str) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(uid), timeout=10)
    # WAL:读写不互相阻塞(检索与后台上传可并发);busy_timeout 避免瞬时锁直接报错
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS docs("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,"
        "sha TEXT NOT NULL, pages INTEGER NOT NULL, created_at REAL NOT NULL,"
        "mime TEXT NOT NULL DEFAULT '', project_id TEXT, doi TEXT,"
        "title TEXT, authors TEXT, year INTEGER, venue TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS nodes("
        "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, parent_id TEXT,"
        "title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',"
        "page_start INTEGER NOT NULL DEFAULT 1, page_end INTEGER NOT NULL DEFAULT 1,"
        "text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS chunks("
        "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, node_id TEXT NOT NULL,"
        "page_start INTEGER NOT NULL, page_end INTEGER NOT NULL,"
        "section TEXT NOT NULL DEFAULT '', text TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS projects("
        "id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        "goal TEXT NOT NULL DEFAULT '', approach TEXT NOT NULL DEFAULT '',"
        "notes TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'exploring',"
        "created_at REAL NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('version', '0')")
    # 兼容已建库:docs 表是在项目表之前上线的,补 project_id 列
    columns = {row[1] for row in conn.execute("PRAGMA table_info(docs)")}
    if "project_id" not in columns:
        conn.execute("ALTER TABLE docs ADD COLUMN project_id TEXT")
    if "doi" not in columns:
        conn.execute("ALTER TABLE docs ADD COLUMN doi TEXT")
    for column, decl in (
        ("title", "TEXT"), ("authors", "TEXT"), ("year", "INTEGER"), ("venue", "TEXT"),
    ):
        if column not in columns:
            conn.execute(f"ALTER TABLE docs ADD COLUMN {column} {decl}")
    for column, decl in (
        ("status", "TEXT NOT NULL DEFAULT 'uploaded'"),
        ("origin_url", "TEXT"),
        ("last_viewed_at", "REAL"),
        ("deleted_at", "REAL"),
        ("purge_after", "REAL"),
    ):
        if column not in columns:
            conn.execute(f"ALTER TABLE docs ADD COLUMN {column} {decl}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS annotations("
        "id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, page INTEGER NOT NULL,"
        " quote TEXT NOT NULL DEFAULT '', rects TEXT NOT NULL DEFAULT '[]',"
        " note TEXT NOT NULL DEFAULT '', color TEXT NOT NULL DEFAULT 'yellow',"
        " created_at REAL NOT NULL, updated_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(doc_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_project ON docs(project_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")
    return conn


def _version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
    try:
        return int(row[0]) if row else 0
    except (TypeError, ValueError):
        return 0


def _bump_version(conn: sqlite3.Connection) -> None:
    """索引内容变更(论文/切片/归属)后 +1,内存索引据此失效。
    WAL 模式下主库 mtime 不一定变化,不能再用文件时间戳判断。"""
    conn.execute("UPDATE meta SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
                 " WHERE key = 'version'")


# ---------- 解析与切片 ----------

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


def _tree_walk_enabled() -> bool:
    """LLM 走树开关(默认关):开启后每次检索多 1~2 次模型调用,
    换来更准的章节定位;没有评测集前不要默认打开。"""
    return os.getenv("MG_TREE_WALK", "0").strip().lower() in ("1", "true", "on", "yes")


def _llm_sync(system: str, user: str, max_tokens: int = 400,
              timeout: float = 20.0) -> str:
    """线程内同步调用 LLM(入库/检索都在线程池里跑,不能直接 await)。"""
    if not llm_mod.is_configured():
        return ""

    async def run() -> str:
        parts: list[str] = []
        async for delta in llm_mod.stream_chat(
            system, user, role="main", fallback=True,
            max_tokens=max_tokens, thinking=False,
        ):
            parts.append(delta)
            if sum(len(p) for p in parts) >= max_tokens * 4:
                break
        return "".join(parts).strip()

    async def with_timeout() -> str:
        return await asyncio.wait_for(run(), timeout)

    try:
        return asyncio.run(with_timeout())
    except Exception as exc:  # noqa: BLE001 摘要失败静默,退回首段摘要
        print(f"[research] LLM 调用失败(走降级): {type(exc).__name__}")
        return ""


def _heuristic_meta(name: str, pages: list[tuple[int, str]]) -> dict:
    """无 LLM 时的元数据兜底:标题取首页首行,年份取首页首个四位年份。"""
    first = pages[0][1] if pages else ""
    title = ""
    for raw in first.splitlines():
        line = _clean_line(raw)
        line = re.sub(r"^#{1,6}\s+", "", line).strip()
        if 5 <= len(line) <= 200 and not re.search(
                r"doi|arxiv|https?://|@|abstract|摘要", line, re.IGNORECASE):
            title = line
            break
    if not title:
        title = Path(name).stem[:200]
    year = 0
    m = re.search(r"\b(19[5-9]\d|20\d{2})\b", first)
    if m:
        value = int(m.group(1))
        now = time.localtime().tm_year
        if 1950 <= value <= now + 1:
            year = value
    return {"title": title, "authors": "", "year": year, "venue": ""}


def _analyze_document(name: str, pages: list[tuple[int, str]],
                      sections: list[Section]) -> tuple[list[str], dict]:
    """一次模型调用同时产出章节摘要与元数据;失败退回启发式结果。"""
    fallback = [_clean_line(s.text)[:SUMMARY_CHARS] for s in sections]
    meta = _heuristic_meta(name, pages)
    if not llm_mod.is_configured() or not sections:
        return fallback, meta
    sample = sections[:16]
    lines = [f"{i}. {s.title}: {_clean_line(s.text)[:200]}"
             for i, s in enumerate(sample, 1)]
    first_page = _clean_line(pages[0][1])[:1200] if pages else ""
    system = (
        "你是学术论文的元数据与索引助手。输出一个 JSON 对象,格式:"
        '{"meta":{"title":"","authors":"","year":0,"venue":""},'
        '"summaries":{"1":"章节摘要","2":"章节摘要"}}。'
        "summaries 为每个章节写不超过 40 字的摘要;meta 只依据给出的首页文本,"
        "未知字段留空字符串或 0。不要解释、不要输出 JSON 以外的内容。"
    )
    user = (f"文件名:{name}\n\n首页:\n{first_page}\n\n章节:\n" + "\n".join(lines))
    raw = _llm_sync(system, user, max_tokens=1000)
    if not raw:
        return fallback, meta
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return fallback, meta
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return fallback, meta
    if not isinstance(data, dict):
        return fallback, meta

    summaries = list(fallback)
    raw_summaries = data.get("summaries")
    items = raw_summaries if isinstance(raw_summaries, dict) else data
    for key, value in items.items():
        try:
            idx = int(str(key).strip()) - 1
        except ValueError:
            continue
        if 0 <= idx < len(summaries) and isinstance(value, str) and value.strip():
            summaries[idx] = value.strip()[:SUMMARY_CHARS]

    raw_meta = data.get("meta")
    if isinstance(raw_meta, dict):
        for key, limit in (("title", 200), ("authors", 300), ("venue", 120)):
            value = raw_meta.get(key)
            if isinstance(value, str) and value.strip():
                meta[key] = value.strip()[:limit]
        year = raw_meta.get("year")
        if isinstance(year, int) and 1950 <= year <= time.localtime().tm_year + 1:
            meta["year"] = year
        elif isinstance(year, str) and year.strip().isdigit():
            value = int(year.strip())
            if 1950 <= value <= time.localtime().tm_year + 1:
                meta["year"] = value
    return summaries, meta


# ---------- 检索打分 ----------

def _tokens(text: str) -> list[str]:
    low = text.lower()
    out = _ASCII_TOKEN_RE.findall(low)
    for run in _CJK_RUN_RE.findall(low):
        out.extend(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            out.append(run)
    return out


@dataclass
class ChunkRec:
    id: str
    doc_id: str
    node_id: str
    page_start: int
    page_end: int
    section: str
    text: str


@dataclass
class NodeRec:
    id: str
    doc_id: str
    parent_id: str | None
    title: str
    summary: str
    page_start: int
    page_end: int
    text: str = ""


class UserIndex:
    """一个用户的全部切片与节点;装在内存里,上传/删除后按 DB mtime 重建。"""

    def __init__(self, uid: str, docs: list[dict], nodes: list[NodeRec],
                 chunks: list[ChunkRec], embedder: embed_mod.Embedder | None):
        self.uid = uid
        self.docs = docs
        self.nodes = nodes
        self.chunks = chunks
        self.embedder = embedder
        self._chunk_tokens = [_tokens(c.section + " " + c.text) for c in chunks]
        self._node_tokens = [_tokens(n.title + " " + n.summary) for n in nodes]
        self._chunk_vectors: list[list[float] | None] = [None] * len(chunks)
        self._node_vectors: list[list[float] | None] = [None] * len(nodes)
        self._vec_lock = threading.Lock()
        self._build_stats()

    def _build_stats(self) -> None:
        self.avgdl = 0.0
        self.df: dict[str, int] = {}
        self.tf: list[dict[str, int]] = []
        for toks in self._chunk_tokens:
            counts: dict[str, int] = {}
            for tok in toks:
                counts[tok] = counts.get(tok, 0) + 1
            self.tf.append(counts)
            for tok in counts:
                self.df[tok] = self.df.get(tok, 0) + 1
            self.avgdl += len(toks)
        if self.chunks:
            self.avgdl /= len(self.chunks)
        n = max(len(self.chunks), 1)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in self.df.items()}

        # 节点标题+摘要单独一套词表:两类文本分布不同,共用 chunk 的 idf
        # 会让只出现在节点标题里的词永远得 0 分
        self.node_tf: list[dict[str, int]] = []
        self.node_df: dict[str, int] = {}
        self.node_avgdl = 0.0
        for toks in self._node_tokens:
            counts: dict[str, int] = {}
            for tok in toks:
                counts[tok] = counts.get(tok, 0) + 1
            self.node_tf.append(counts)
            for tok in counts:
                self.node_df[tok] = self.node_df.get(tok, 0) + 1
            self.node_avgdl += len(toks)
        if self.nodes:
            self.node_avgdl /= len(self.nodes)
        node_n = max(len(self.nodes), 1)
        self.node_idf = {t: math.log(1 + (node_n - d + 0.5) / (d + 0.5))
                         for t, d in self.node_df.items()}

    def _bm25(self, query: str, docs: list[int], tokens: list[dict[str, int]],
              avgdl: float, idf: dict[str, float]) -> list[tuple[int, float]]:
        q = _tokens(query)
        if not q or not docs:
            return []
        scored: list[tuple[int, float]] = []
        for idx in docs:
            counts = tokens[idx]
            dl = sum(counts.values())
            score = 0.0
            for tok in q:
                tf = counts.get(tok)
                if not tf:
                    continue
                denom = tf + K1 * (1 - B + B * dl / (avgdl or 1))
                score += idf.get(tok, 0.0) * tf * (K1 + 1) / (denom or 1)
            if score > 0:
                scored.append((idx, score))
        scored.sort(key=lambda x: -x[1])
        return scored

    def _ensure_vectors(self) -> None:
        if self.embedder is None:
            return
        with self._vec_lock:
            need_chunks = bool(self.chunks) and all(v is None for v in self._chunk_vectors)
            need_nodes = bool(self.nodes) and all(v is None for v in self._node_vectors)
            if not need_chunks and not need_nodes:
                return
            try:
                # 必须一次提交全量切片+节点:Embedder.embed_chunks 会按本次清单
                # 清理缓存里不在清单内的历史键,分两次调用会互相删缓存
                items = [(f"{self.uid}|chunk|{c.id}", f"{c.section}\n{c.text}")
                         for c in self.chunks]
                items += [(f"{self.uid}|node|{n.id}", f"{n.title}\n{n.summary}")
                          for n in self.nodes]
                vectors = self.embedder.embed_chunks(items)
                chunk_n = len(self.chunks)
                self._chunk_vectors = list(vectors[:chunk_n])
                self._node_vectors = list(vectors[chunk_n:])
            except Exception as exc:  # noqa: BLE001 向量服务失败退化为 BM25
                print(f"[research] embedding 失败,降级为 BM25: {exc}")
                self.embedder = None
                self._chunk_vectors = [None] * len(self.chunks)
                self._node_vectors = [None] * len(self.nodes)

    def _vector_rank(self, query: str, vectors: list[list[float] | None],
                     allowed: list[int]) -> list[int]:
        if self.embedder is None or not any(v is not None for v in vectors):
            return []
        try:
            qv = self.embedder.embed_query(query)
        except Exception as exc:  # noqa: BLE001
            print(f"[research] query embedding 失败,本次纯 BM25: {exc}")
            return []
        scored = []
        for idx in allowed:
            vec = vectors[idx]
            if vec is None:
                continue
            score = embed_mod.Embedder.cosine(qv, vec)
            if score > 0:
                scored.append((idx, score))
        scored.sort(key=lambda x: -x[1])
        return [idx for idx, _ in scored]

    @staticmethod
    def _rrf(*rankings: list[int]) -> list[tuple[int, float]]:
        scores: dict[int, float] = {}
        for ranking in rankings:
            for rank, idx in enumerate(ranking):
                scores[idx] = scores.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
        return sorted(scores.items(), key=lambda x: -x[1])

    def _llm_pick_nodes(self, query: str, candidates: list[int]) -> list[int]:
        """让模型从候选节点里选最多 3 个继续深入;解析失败返回空。"""
        if not candidates:
            return []
        by_id = {n.id: i for i, n in enumerate(self.nodes)}
        lines = [
            f"{self.nodes[i].id} | {self.nodes[i].title} | "
            f"p.{self.nodes[i].page_start}-{self.nodes[i].page_end} | {self.nodes[i].summary[:120]}"
            for i in candidates[:16]
        ]
        system = (
            "你是文献检索导航器。根据问题,从候选章节里选出最可能包含答案的最多 3 个章节。"
            "只输出 JSON 数组,元素是章节 id;没有相关章节输出 []。不要解释。"
        )
        user = f"问题:{query}\n\n候选章节:\n" + "\n".join(lines)
        raw = _llm_sync(system, user, max_tokens=120, timeout=10.0)
        if not raw:
            return []
        m = re.search(r"\[[\s\S]*\]", raw)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        picked: list[int] = []
        for item in data:
            idx = by_id.get(str(item).strip())
            if idx is not None and idx in candidates and idx not in picked:
                picked.append(idx)
        return picked[:3]

    def _tree_walk(self, query: str, allowed_nodes: list[int]) -> set[str] | None:
        """PageIndex 式走树:根 → 子节点,最多两轮。失败返回 None 走 BM25 节点排序。"""
        if not _tree_walk_enabled() or not llm_mod.is_configured() or not allowed_nodes:
            return None
        allowed = set(allowed_nodes)
        by_id = {n.id: i for i, n in enumerate(self.nodes)}
        children: dict[str, list[int]] = {}
        roots: list[int] = []
        for i in allowed_nodes:
            node = self.nodes[i]
            parent_id = node.parent_id
            parent_idx = by_id.get(parent_id) if parent_id else None
            if parent_id is None or parent_idx is None or parent_idx not in allowed:
                roots.append(i)
            else:
                children.setdefault(parent_id, []).append(i)
        if not roots:
            return None

        frontier = roots[:20]
        picked: list[int] = []
        for _ in range(2):
            picked = self._llm_pick_nodes(query, frontier)
            if not picked:
                return None
            deeper: list[int] = []
            for idx in picked:
                deeper.extend(children.get(self.nodes[idx].id, []))
            if not deeper:
                break
            frontier = deeper[:20]

        # 选中的可能是父节点:把整棵子树的节点都纳入,避免漏掉子章节
        subtree: set[str] = set()
        stack = [self.nodes[i].id for i in picked]
        while stack:
            node_id = stack.pop()
            if node_id in subtree:
                continue
            subtree.add(node_id)
            stack.extend(child.id for child in self.nodes
                         if child.parent_id == node_id)
        return subtree or None

    def search(self, query: str, top_k: int = 8, doc_id: str | None = None,
               use_tree: bool = False, project_id: str | None = None,
               doc_ids: set[str] | None = None) -> dict:
        """默认不做章节树筛选:评测集上树筛会漏掉正确切片(BM25+向量已足够);
        需要 PageIndex 式走树时由调用方显式打开(MG_TREE_WALK=1 + tree=true)。"""
        self._ensure_vectors()
        project_docs: set[str] | None = None
        if project_id:
            project_docs = {d["id"] for d in self.docs if d.get("projectId") == project_id}
        scope: set[str] | None = doc_ids if doc_ids is not None else (
            {doc_id} if doc_id else {
                d["id"] for d in self.docs if d.get("status") != "temp"})
        allowed_chunks = [
            i for i, c in enumerate(self.chunks)
            if (scope is None or c.doc_id in scope)
            and (project_docs is None or c.doc_id in project_docs)
        ]
        allowed_nodes = [
            i for i, n in enumerate(self.nodes)
            if (scope is None or n.doc_id in scope)
            and (project_docs is None or n.doc_id in project_docs)
        ]

        # 章节树:优先 LLM 走树(MG_TREE_WALK=1);未开启或失败时
        # 退化为节点标题+摘要的 BM25/向量排序,取前 5 个节点作为候选区
        top_node_ids: set[str] = set()
        if use_tree:
            walked = self._tree_walk(query, allowed_nodes)
            if walked:
                top_node_ids = walked
            else:
                node_rank = self._bm25(query, allowed_nodes, self.node_tf,
                                       self.node_avgdl, self.node_idf)
                vec_nodes = self._vector_rank(query, self._node_vectors, allowed_nodes)
                fused_nodes = self._rrf([i for i, _ in node_rank], vec_nodes)
                top_node_ids = {self.nodes[i].id for i, _ in fused_nodes[:5]}

        if use_tree and top_node_ids:
            allowed_chunks = [i for i in allowed_chunks
                              if self.chunks[i].node_id in top_node_ids]

        lex = self._bm25(query, allowed_chunks, self.tf, self.avgdl, self.idf)
        vec = self._vector_rank(query, self._chunk_vectors, allowed_chunks)
        fused = self._rrf([i for i, _ in lex], vec)
        if not fused:
            # 树筛完没有命中就退回全库,避免"节点分错 → 永远搜不到"
            if use_tree and top_node_ids:
                return self.search(query, top_k=top_k, doc_id=doc_id,
                                   use_tree=False, project_id=project_id, doc_ids=doc_ids)
            return {"hits": [], "total": 0, "query": query}

        docs_by_id = {d["id"]: d for d in self.docs}
        hits = []
        for idx, score in fused[:top_k]:
            chunk = self.chunks[idx]
            doc = docs_by_id.get(chunk.doc_id, {})
            hits.append({
                "docId": chunk.doc_id,
                "docName": doc.get("name", ""),
                "nodeId": chunk.node_id,
                "section": chunk.section,
                "pageStart": chunk.page_start,
                "pageEnd": chunk.page_end,
                "snippet": chunk.text[:SNIPPET_CHARS],
                "text": chunk.text,
                "score": round(score, 6),
            })
        return {
            "hits": hits,
            "total": len(fused),
            "query": query,
            "mode": "hybrid" if self.embedder is not None else "bm25",
            "tree": use_tree,
        }


_indexes: dict[str, UserIndex] = {}
_index_paths: dict[str, int] = {}
_index_lock = threading.Lock()
# shortcut: this guards the documented single-worker deployment; use cross-process locks for multiple workers.
_mutation_locks = tuple(threading.RLock() for _ in range(64))


def _mutation_lock(uid: str):
    return _mutation_locks[hash(_safe_uid(uid)) % len(_mutation_locks)]


def _load_rows(uid: str) -> tuple[list[dict], list[NodeRec], list[ChunkRec]]:
    conn = _connect(uid)
    try:
        docs = [
            {"id": r[0], "name": r[1], "size": r[2], "pages": r[4],
             "createdAt": r[5], "projectId": r[6], "doi": r[7] or "",
             "title": r[8] or r[1], "authors": r[9] or "",
             "year": r[10] or 0, "venue": r[11] or "",
             "status": r[12] or "uploaded", "originUrl": r[13] or "",
             "lastViewedAt": r[14] or 0, "deletedAt": r[15] or 0}
            for r in conn.execute(
                "SELECT id, name, size, sha, pages, created_at, project_id, doi,"
                " title, authors, year, venue, status, origin_url, last_viewed_at,"
                " deleted_at FROM docs ORDER BY created_at DESC")
        ]
        nodes = [NodeRec(*r) for r in conn.execute(
            "SELECT id, doc_id, parent_id, title, summary, page_start, page_end, text FROM nodes")]
        chunks = [ChunkRec(*r) for r in conn.execute(
            "SELECT id, doc_id, node_id, page_start, page_end, section, text FROM chunks")]
        return docs, nodes, chunks
    finally:
        conn.close()


def _corpus_version(uid: str) -> int:
    if not _db_path(uid).exists():
        return 0
    conn = _connect(uid)
    try:
        return _version(conn)
    finally:
        conn.close()


def _get_index(uid: str) -> UserIndex:
    path = _db_path(uid)
    version = _corpus_version(uid)
    with _index_lock:
        cached = _indexes.get(uid)
        if cached is not None and _index_paths.get(uid) == version:
            return cached
        if not path.exists():
            empty = UserIndex(uid, [], [], [], None)
            _indexes[uid] = empty
            _index_paths[uid] = version
            return empty
        docs, nodes, chunks = _load_rows(uid)
        live = {d["id"] for d in docs if not d.get("deletedAt")}
        docs = [d for d in docs if d["id"] in live]
        nodes = [n for n in nodes if n.doc_id in live]
        chunks = [c for c in chunks if c.doc_id in live]
        embedder = None
        if embed_mod.is_configured():
            try:
                embedder = embed_mod.Embedder(cache_path=_user_dir(uid) / ".embeddings.json")
            except Exception as exc:  # noqa: BLE001
                print(f"[research] embedding 初始化失败,纯 BM25: {exc}")
        index = UserIndex(uid, docs, nodes, chunks, embedder)
        _indexes[uid] = index
        _index_paths[uid] = version
        return index


# ---------- 入库 / 删除 ----------

def _check_formal_capacity(conn: sqlite3.Connection, additional_size: int) -> None:
    count, used = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM docs"
        " WHERE status != 'temp' AND deleted_at IS NULL").fetchone()
    if count >= _max_docs():
        raise ValueError(f"论文数量达到上限 {_max_docs()}")
    if used + additional_size > _max_total_bytes():
        raise ValueError(f"论文库总容量达到上限 {_max_total_bytes() // (1024 * 1024)}MB")


def _ingest(uid: str, name: str, data: bytes, mime: str,
            project_id: str | None = None, *, status: str = "uploaded",
            origin_url: str = "", analyze: bool = True) -> dict:
    if status not in ("uploaded", "temp", "imported"):
        raise ValueError("未知的文档状态")
    if not name or len(name) > 200:
        raise ValueError("文件名缺失或过长")
    limit = _max_upload_bytes()
    if len(data) > limit:
        raise ValueError(f"文件超过 {limit // (1024 * 1024)}MB 上限")
    kind = _detect_format(name, data, mime)

    sha = hashlib.sha256(data).hexdigest()
    doc_id = sha[:16]
    pages = _extract_pages(kind, data, name)
    total = sum(len(t.strip()) for _, t in pages)
    if total < 50:
        if kind == "pdf":
            raise ValueError(
                "未能从 PDF 提取到文字层:文件可能是扫描件/纯图片,或使用了未嵌入文字的字体;"
                "这类文件需要先做 OCR 再导入")
        raise ValueError(f"没有从{kind.upper()}文件中提取到正文,请检查文件是否损坏")
    doi = _extract_doi(pages)

    sections = _sections(pages)
    # 一次模型调用同时产出章节摘要与元数据;临时论文跳过模型,减少等待与费用
    if analyze:
        summaries, meta = _analyze_document(name, pages, sections)
    else:
        summaries = [_clean_line(s.text)[:SUMMARY_CHARS] for s in sections]
        meta = _heuristic_meta(name, pages)
    with _mutation_lock(uid):
        purge_expired_history(uid)
        conn = _connect(uid)
        try:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            if project_id:
                found_project = conn.execute(
                    "SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
                if not found_project:
                    raise ValueError("研究项目不存在")
            exists = conn.execute(
                "SELECT id, status, deleted_at, purge_after, size FROM docs WHERE id = ?", (doc_id,)).fetchone()
            if not exists and doi:
                # 同一篇论文的另一个 PDF(排版/压缩不同,内容哈希不同)按 DOI 去重
                exists = conn.execute(
                    "SELECT id, status, deleted_at, purge_after, size FROM docs WHERE doi = ? LIMIT 1",
                    (doi,)).fetchone()
            if exists:
                doc_id = str(exists[0])
                current = str(exists[1] or "uploaded")
                now = time.time()
                if exists[2]:
                    if exists[3] is None or exists[3] <= now:
                        raise ValueError("浏览历史已过期，请重试")
                    conn.execute(
                        "UPDATE docs SET deleted_at = NULL, purge_after = NULL WHERE id = ?",
                        (doc_id,))
                    _bump_version(conn)
                if status in ("uploaded", "imported") and current == "temp":
                    _check_formal_capacity(conn, int(exists[4] or 0))
                    conn.execute(
                        "UPDATE docs SET status = ?, project_id = COALESCE(?, project_id),"
                        " origin_url = COALESCE(?, origin_url) WHERE id = ?",
                        (status if status == "imported" else "uploaded", project_id,
                         origin_url or None, doc_id))
                    current = status if status == "imported" else "uploaded"
                    _bump_version(conn)
                elif project_id:
                    conn.execute("UPDATE docs SET project_id = ? WHERE id = ?",
                                 (project_id, doc_id))
                    _bump_version(conn)
                if current == "temp":
                    conn.execute(
                        "UPDATE docs SET last_viewed_at = ?, origin_url = COALESCE(?, origin_url)"
                        " WHERE id = ?", (now, origin_url or None, doc_id))
                conn.commit()
                return {"docId": doc_id, "duplicate": True, "doi": doi,
                        "status": current, "pages": len(pages)}
            evicted: list[str] = []
            if status == "temp":
                used = conn.execute(
                    "SELECT COALESCE(SUM(size), 0) FROM docs"
                    " WHERE status = 'temp' AND deleted_at IS NULL").fetchone()[0]
                temp_count = conn.execute(
                    "SELECT COUNT(*) FROM docs WHERE status = 'temp' AND deleted_at IS NULL"
                ).fetchone()[0]
                over_docs = temp_count >= TEMP_DOC_LIMIT
                over_bytes = used + len(data) > _max_total_bytes()
                if over_docs or over_bytes:
                    # 自动淘汰最旧的无批注临时论文;有批注的永不自动删除
                    rows = conn.execute(
                        "SELECT d.id, d.size FROM docs d"
                        " WHERE d.status = 'temp' AND d.deleted_at IS NULL"
                        " AND NOT EXISTS (SELECT 1 FROM annotations a WHERE a.doc_id = d.id)"
                        " ORDER BY COALESCE(d.last_viewed_at, d.created_at) ASC"
                    ).fetchall()
                    freed = 0
                    for old_id, old_size in rows:
                        if temp_count - len(evicted) < TEMP_DOC_LIMIT and used - freed + len(data) <= _max_total_bytes():
                            break
                        evicted.append(str(old_id))
                        freed += int(old_size or 0)
                    if temp_count - len(evicted) >= TEMP_DOC_LIMIT:
                        raise ValueError(
                            f"临时论文数量达到上限 {TEMP_DOC_LIMIT},且没有可自动清理的无批注记录;"
                            "请导入或手动删除历史")
                    if used - freed + len(data) > _max_total_bytes():
                        raise ValueError(
                            f"临时论文总容量达到上限 {_max_total_bytes() // (1024 * 1024)}MB,"
                            "且没有可自动清理的无批注记录")
                    if evicted:
                        marks = ",".join("?" for _ in evicted)
                        conn.execute(f"DELETE FROM chunks WHERE doc_id IN ({marks})", evicted)
                        conn.execute(f"DELETE FROM nodes WHERE doc_id IN ({marks})", evicted)
                        conn.execute(f"DELETE FROM docs WHERE id IN ({marks})", evicted)
                        used -= freed
            else:
                _check_formal_capacity(conn, len(data))
            now = time.time()
            conn.execute(
                "INSERT INTO docs(id, name, size, sha, pages, created_at, mime, project_id,"
                " doi, title, authors, year, venue, status, origin_url, last_viewed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, name, len(data), sha, len(pages), now, mime, project_id,
                 doi, meta["title"], meta["authors"], meta["year"], meta["venue"],
                 status, origin_url, now if status == "temp" else None))
            nodes: list[tuple] = []
            chunks: list[tuple] = []
            stack: list[tuple[int, str]] = []
            for si, section in enumerate(sections, start=1):
                node_id = f"{doc_id}#s{si}"
                level = _heading_level(section.title)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent_id = stack[-1][1] if stack else None
                stack.append((level, node_id))
                summary = summaries[si - 1] if si - 1 < len(summaries) else _clean_line(section.text)[:SUMMARY_CHARS]
                nodes.append((node_id, doc_id, parent_id, section.title, summary,
                              section.page_start, section.page_end, section.text[:20000]))
                for ci, (text, p_start, p_end) in enumerate(_chunk_section(section), start=1):
                    chunks.append((f"{doc_id}#s{si}c{ci}", doc_id, node_id,
                                   p_start, p_end, section.title, text))
            conn.executemany(
                "INSERT INTO nodes(id, doc_id, parent_id, title, summary, page_start, page_end, text)"
                " VALUES (?,?,?,?,?,?,?,?)", nodes)
            conn.executemany(
                "INSERT INTO chunks(id, doc_id, node_id, page_start, page_end, section, text)"
                " VALUES (?,?,?,?,?,?,?)", chunks)
            _bump_version(conn)
            conn.commit()
        finally:
            conn.close()

        # 原文件落盘(只存一份;重名不覆盖,doc_id 已按内容去重)
        for old_id in evicted:
            for path in (_user_dir(uid) / "files").glob(f"{old_id}.*"):
                try:
                    path.unlink()
                except OSError:
                    continue
        suffix = {
            "pdf": ".pdf", "docx": ".docx", "epub": ".epub",
            "rtf": ".rtf", "html": ".html", "xml": ".xml",
        }.get(kind) or Path(name).suffix.lower()[:10] or ".txt"
        try:
            (_user_dir(uid) / "files" / f"{doc_id}{suffix}").write_bytes(data)
        except OSError as exc:
            print(f"[research] 原文件保存失败(索引已入库): {exc}")

        with _index_lock:
            _indexes.pop(uid, None)
        return {"docId": doc_id, "duplicate": False, "pages": len(pages),
                "sections": len(sections), "chunks": len(chunks),
                "status": status, "title": meta["title"], "doi": doi}


def _delete(uid: str, doc_id: str, *, expired_before: float | None = None) -> bool:
    with _mutation_lock(uid):
        conn = _connect(uid)
        try:
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            if expired_before is None:
                found = conn.execute("SELECT id FROM docs WHERE id = ?", (doc_id,)).fetchone()
            else:
                found = conn.execute(
                    "SELECT id FROM docs WHERE id = ? AND status = 'temp'"
                    " AND deleted_at IS NOT NULL AND purge_after IS NOT NULL AND purge_after <= ?",
                    (doc_id, expired_before)).fetchone()
            if not found:
                return False
            conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM nodes WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM annotations WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
            _bump_version(conn)
            if expired_before is not None:
                # Keep the write lock until old files are gone, so a new upload cannot reuse this id.
                for path in (_user_dir(uid) / "files").glob(f"{doc_id}.*"):
                    path.unlink(missing_ok=True)
            conn.commit()
        finally:
            conn.close()
        if expired_before is None:
            for path in (_user_dir(uid) / "files").glob(f"{doc_id}.*"):
                try:
                    path.unlink()
                except OSError:
                    pass
        with _index_lock:
            _indexes.pop(uid, None)
        return True


def corpus_stamp(uid: str) -> str:
    """语料版本(DB 内的 version):上传/删除后让研究答案缓存失效。库不存在返回 0。"""
    return str(_corpus_version(uid))


def _doc_row(uid: str, doc_id: str) -> dict | None:
    conn = _connect(uid)
    try:
        row = conn.execute(
            "SELECT id, name, pages, mime, status, deleted_at FROM docs WHERE id = ?",
            (doc_id,)).fetchone()
        if not row:
            return None
        return {"id": row[0], "name": row[1], "pages": row[2], "mime": row[3] or "",
                "status": row[4] or "uploaded", "deletedAt": row[5] or 0}
    finally:
        conn.close()


def _annotation_row(row: tuple) -> dict:
    import json as _json

    try:
        rects = _json.loads(row[4] or "[]")
    except (TypeError, ValueError):
        rects = []
    return {
        "id": row[0], "docId": row[1], "page": row[2], "quote": row[3] or "",
        "rects": rects if isinstance(rects, list) else [],
        "note": row[5] or "", "color": row[6] or "yellow",
        "createdAt": row[7], "updatedAt": row[8],
    }


def _list_annotations(uid: str, doc_id: str) -> list[dict]:
    conn = _connect(uid)
    try:
        rows = conn.execute(
            "SELECT id, doc_id, page, quote, rects, note, color, created_at,"
            " updated_at FROM annotations WHERE doc_id = ? ORDER BY page, created_at",
            (doc_id,)).fetchall()
        return [_annotation_row(row) for row in rows]
    finally:
        conn.close()


def _clean_rects(value: object) -> list[list[float]]:
    if not isinstance(value, list):
        return []
    out: list[list[float]] = []
    for item in value[:300]:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            continue
        try:
            nums = [float(x) for x in item]
        except (TypeError, ValueError):
            continue
        if any(x < 0 or x > 1 for x in nums):
            continue
        out.append([round(x, 5) for x in nums])
    return out


def _save_annotation(uid: str, doc_id: str, body: dict) -> dict:
    import json as _json

    page = body.get("page")
    quote = str(body.get("quote") or "")[:2000]
    note = str(body.get("note") or "")[:4000]
    color = str(body.get("color") or "yellow")[:20]
    if not isinstance(page, int) or page < 1:
        raise ValueError("页码无效")
    if not quote and not note:
        raise ValueError("批注内容为空")
    rects = _clean_rects(body.get("rects"))
    now = time.time()
    conn = _connect(uid)
    try:
        doc = conn.execute(
            "SELECT id FROM docs WHERE id = ? AND deleted_at IS NULL", (doc_id,)
        ).fetchone()
        if not doc:
            raise FileNotFoundError("文档不存在")
        aid = str(body.get("id") or "")[:64]
        row = None
        if aid:
            row = conn.execute(
                "SELECT id FROM annotations WHERE id = ? AND doc_id = ?",
                (aid, doc_id)).fetchone()
        if row:
            conn.execute(
                "UPDATE annotations SET page = ?, quote = ?, rects = ?, note = ?,"
                " color = ?, updated_at = ? WHERE id = ? AND doc_id = ?",
                (page, quote, _json.dumps(rects), note, color, now, aid, doc_id))
        else:
            aid = aid or secrets.token_hex(10)
            conn.execute(
                "INSERT INTO annotations(id, doc_id, page, quote, rects, note,"
                " color, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, doc_id, page, quote, _json.dumps(rects), note, color,
                 now, now))
        conn.commit()
        data = conn.execute(
            "SELECT id, doc_id, page, quote, rects, note, color, created_at,"
            " updated_at FROM annotations WHERE id = ?", (aid,)).fetchone()
        return _annotation_row(data)  # type: ignore[arg-type]
    finally:
        conn.close()


def _delete_annotation(uid: str, doc_id: str, annotation_id: str) -> bool:
    conn = _connect(uid)
    try:
        cur = conn.execute(
            "DELETE FROM annotations WHERE id = ? AND doc_id = ?",
            (annotation_id, doc_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _docs_by_doi(uid: str, dois: set[str]) -> dict[str, dict]:
    if not dois:
        return {}
    picked = list(dois)[:100]
    marks = ",".join("?" for _ in picked)
    conn = _connect(uid)
    try:
        rows = conn.execute(
            "SELECT id, doi, status FROM docs WHERE deleted_at IS NULL"
            f" AND lower(doi) IN ({marks})", [d.lower() for d in picked]).fetchall()
        result: dict[str, dict] = {}
        for doc_id, doi, status in rows:
            key = str(doi or "").lower()
            current = result.get(key)
            # 已入库优先于临时文档
            if current is None or (current["status"] == "temp" and status != "temp"):
                result[key] = {"id": doc_id, "status": status or "uploaded"}
        return result
    finally:
        conn.close()


def _import_temp(uid: str, doc_id: str, project_id: str | None,
                 keep_annotations: bool = True) -> dict:
    conn = _connect(uid)
    try:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status, deleted_at, size FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if not row or row[1]:
            raise FileNotFoundError("文档不存在")
        status = str(row[0] or "uploaded")
        if status != "temp":
            return {"docId": doc_id, "duplicate": True, "status": status}
        if project_id:
            project = conn.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
            if not project:
                raise ValueError("研究项目不存在")
        _check_formal_capacity(conn, int(row[2] or 0))
        if not keep_annotations:
            conn.execute("DELETE FROM annotations WHERE doc_id = ?", (doc_id,))
        conn.execute(
            "UPDATE docs SET status = 'imported', project_id = COALESCE(?, project_id),"
            " last_viewed_at = ? WHERE id = ?",
            (project_id, time.time(), doc_id))
        _bump_version(conn)
        conn.commit()
        return {"docId": doc_id, "duplicate": False, "status": "imported",
                "annotationsKept": keep_annotations}
    finally:
        conn.close()


HISTORY_TTL_DAYS = 30


def _history_item(row: tuple) -> dict:
    return {
        "id": row[0], "title": row[1] or row[2], "name": row[2],
        "pages": row[3], "doi": row[4] or "", "year": row[5] or 0,
        "createdAt": row[6], "lastViewedAt": row[7] or 0,
        "annotations": row[8] or 0, "originUrl": row[9] or "",
    }


def _history_items(uid: str) -> list[dict]:
    conn = _connect(uid)
    try:
        rows = conn.execute(
            "SELECT d.id, d.title, d.name, d.pages, d.doi, d.year, d.created_at,"
            " d.last_viewed_at,"
            " (SELECT COUNT(*) FROM annotations a WHERE a.doc_id = d.id),"
            " d.origin_url FROM docs d"
            " WHERE d.status = 'temp' AND d.deleted_at IS NULL"
            " ORDER BY COALESCE(d.last_viewed_at, d.created_at) DESC").fetchall()
        return [_history_item(row) for row in rows]
    finally:
        conn.close()


def _history_trash(uid: str) -> list[dict]:
    now = time.time()
    conn = _connect(uid)
    try:
        rows = conn.execute(
            "SELECT d.id, d.title, d.name, d.pages, d.doi, d.year, d.created_at,"
            " d.last_viewed_at,"
            " (SELECT COUNT(*) FROM annotations a WHERE a.doc_id = d.id),"
            " d.origin_url, d.deleted_at, d.purge_after FROM docs d"
            " WHERE d.status = 'temp' AND d.deleted_at IS NOT NULL"
            " ORDER BY d.deleted_at DESC").fetchall()
        items = []
        for row in rows:
            item = _history_item(row[:10])
            purge = float(row[11] or 0)
            item["deletedAt"] = row[10] or 0
            item["purgeAfter"] = purge
            item["daysLeft"] = max(0, int((purge - now + 86399) // 86400))
            items.append(item)
        return items
    finally:
        conn.close()


def _history_delete(uid: str, doc_id: str) -> bool:
    now = time.time()
    conn = _connect(uid)
    try:
        cur = conn.execute(
            "UPDATE docs SET deleted_at = ?, purge_after = ?"
            " WHERE id = ? AND status = 'temp' AND deleted_at IS NULL",
            (now, now + HISTORY_TTL_DAYS * 86400, doc_id))
        if cur.rowcount:
            _bump_version(conn)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _history_restore(uid: str, doc_id: str) -> bool:
    conn = _connect(uid)
    try:
        cur = conn.execute(
            "UPDATE docs SET deleted_at = NULL, purge_after = NULL"
            " WHERE id = ? AND status = 'temp' AND deleted_at IS NOT NULL"
            " AND purge_after IS NOT NULL AND purge_after > ?",
            (doc_id, time.time()))
        if cur.rowcount:
            _bump_version(conn)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def purge_expired_history(uid: str) -> int:
    """删除回收站中超过 30 天的临时论文;返回清理数量。"""
    now = time.time()
    conn = _connect(uid)
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM docs WHERE status = 'temp' AND deleted_at IS NOT NULL"
            " AND purge_after IS NOT NULL AND purge_after <= ?", (now,))]
    finally:
        conn.close()
    return sum(_delete(uid, doc_id, expired_before=now) for doc_id in ids)


def purge_expired_history_all() -> int:
    if not DATA_DIR.exists():
        return 0
    total = 0
    for folder in DATA_DIR.iterdir():
        if not folder.is_dir() or not (folder / "index.sqlite3").exists():
            continue
        try:
            total += purge_expired_history(folder.name)
        except Exception:  # noqa: BLE001 单个用户库损坏不阻断启动
            continue
    return total


def _doc_file_path(uid: str, doc_id: str) -> Path | None:
    for path in sorted((_user_dir(uid) / "files").glob(f"{doc_id}.*")):
        if path.name.endswith(".pages.json"):
            continue
        return path
    return None


_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
    ".epub": "application/epub+zip",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".rtf": "application/rtf",
}


def _doc_text_cache(uid: str, doc_id: str) -> list[list]:
    folder = _user_dir(uid) / "files"
    cache = folder / f"{doc_id}.pages.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    source = _doc_file_path(uid, doc_id)
    if source is None:
        raise FileNotFoundError("原始文件不存在")
    data = source.read_bytes()
    kind = _detect_format(source.name, data, "")
    if kind == "pdf":
        raise ValueError("PDF 使用文件接口,不走文本接口")
    pages = _extract_pages(kind, data, source.name)
    payload = [[number, text] for number, text in pages]
    try:
        cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return payload


PROJECT_STATUSES = {"exploring", "active", "paused", "done"}
PROJECT_TEXT_MAX = 4000


def _project_row(row: tuple) -> dict:
    return {
        "id": row[0], "title": row[1], "goal": row[2], "approach": row[3],
        "notes": row[4], "status": row[5], "createdAt": row[6], "updatedAt": row[7],
    }


def _load_projects(uid: str) -> list[dict]:
    conn = _connect(uid)
    try:
        return [
            _project_row(r)
            for r in conn.execute(
                "SELECT id, title, goal, approach, notes, status, created_at, updated_at"
                " FROM projects ORDER BY updated_at DESC")
        ]
    finally:
        conn.close()


def _create_project(uid: str, title: str) -> dict:
    title = title.strip()[:120] or "未命名研究"
    now = time.time()
    project_id = f"p-{secrets.token_hex(8)}"
    conn = _connect(uid)
    try:
        conn.execute(
            "INSERT INTO projects(id, title, goal, approach, notes, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (project_id, title, "", "", "", "exploring", now, now))
        conn.commit()
    finally:
        conn.close()
    return _project_row((project_id, title, "", "", "", "exploring", now, now))


def _update_project(uid: str, project_id: str, patch: dict) -> dict | None:
    allowed = {"title", "goal", "approach", "notes", "status"}
    sets: list[str] = []
    values: list[object] = []
    for key in allowed:
        if key not in patch:
            continue
        value = patch[key]
        if not isinstance(value, str):
            continue
        if key == "status":
            if value not in PROJECT_STATUSES:
                continue
        elif key == "title":
            value = value.strip()[:120] or "未命名研究"
        else:
            value = value[:PROJECT_TEXT_MAX]
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return None
    sets.append("updated_at = ?")
    values.append(time.time())
    conn = _connect(uid)
    try:
        cur = conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", (*values, project_id))
        if cur.rowcount == 0:
            return None
        conn.commit()
        row = conn.execute(
            "SELECT id, title, goal, approach, notes, status, created_at, updated_at"
            " FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _project_row(row) if row else None
    finally:
        conn.close()


def _delete_project(uid: str, project_id: str) -> bool:
    conn = _connect(uid)
    try:
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        if cur.rowcount == 0:
            return False
        # 项目删除不删论文,只解除归属,避免误删用户资料
        conn.execute("UPDATE docs SET project_id = NULL WHERE project_id = ?", (project_id,))
        _bump_version(conn)
        conn.commit()
        return True
    finally:
        conn.close()


def _clear_all(uid: str) -> int:
    """清空用户论文库(保留临时论文与空 DB 目录);返回删除的论文数。"""
    with _mutation_lock(uid):
        conn = _connect(uid)
        try:
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM docs WHERE status != 'temp'")]
            if ids:
                marks = ",".join("?" for _ in ids)
                conn.execute(f"DELETE FROM chunks WHERE doc_id IN ({marks})", ids)
                conn.execute(f"DELETE FROM nodes WHERE doc_id IN ({marks})", ids)
                conn.execute(f"DELETE FROM annotations WHERE doc_id IN ({marks})", ids)
                conn.execute(f"DELETE FROM docs WHERE id IN ({marks})", ids)
            count = len(ids)
            _bump_version(conn)
            conn.commit()
        finally:
            conn.close()
        for path in (_user_dir(uid) / "files").glob("*"):
            if path.stem.split(".")[0] in ids:
                try:
                    path.unlink()
                except OSError:
                    pass
        with _index_lock:
            _indexes.pop(uid, None)
            _index_paths.pop(uid, None)
        return count


def chat_hits(uid: str, question: str, top_k: int = 4,
              doc_id: str | None = None) -> list[dict]:
    """科研对话用:返回用户自己论文的命中片段;库空时返回空列表。
    传 doc_id 时只在该篇论文内检索(阅读器里针对当前论文提问)。"""
    index = _get_index(uid)
    if not index.chunks:
        return []
    return index.search(question, top_k=top_k, doc_id=doc_id)["hits"]

def docs_for_export(uid: str) -> list[dict]:
    """账号导出用:只含论文元数据,不含正文与原文件。"""
    if not _db_path(uid).exists():
        return []
    return _load_rows(uid)[0]


def projects_for_export(uid: str) -> list[dict]:
    """账号导出用:研究项目(目标/思路/笔记)。"""
    if not _db_path(uid).exists():
        return []
    return _load_projects(uid)


def delete_user(uid: str) -> None:
    """注销/留存清理:删除该用户的整个语料目录(原文件、索引、向量缓存)。"""
    path = DATA_DIR / _safe_uid(uid)
    shutil.rmtree(path, ignore_errors=True)
    with _index_lock:
        _indexes.pop(uid, None)
        _index_paths.pop(uid, None)


def _rate(limiter: SlidingWindowLimiter, uid: str) -> None:
    if not limiter.allow(uid):
        raise HTTPException(429, "too many requests")


# ---------- HTTP 接口 ----------
async def _read_limited(request: Request) -> bytes:
    limit = _max_upload_bytes()
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        raise HTTPException(413, f"文件超过 {limit // (1024 * 1024)}MB 上限")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"文件超过 {limit // (1024 * 1024)}MB 上限")
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_doc(request: Request) -> JSONResponse:
    """上传论文:原始字节放 body,文件名放 ?name=(前端 encodeURIComponent)。

    不用 multipart:只传一个文件,省一层解析依赖;文件名只用于展示,
    落盘路径用内容哈希,杜绝路径穿越。
    """
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    _rate(_upload_limiter, uid)
    name = request.query_params.get("name", "").strip()
    project_id = request.query_params.get("projectId", "").strip() or None
    data = await _read_limited(request)
    if not data:
        raise HTTPException(400, "empty file")
    try:
        result = await asyncio.to_thread(
            _ingest, uid, name, data, request.headers.get("content-type", ""), project_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse({"ok": True, **result})


async def list_docs(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    docs, _, _ = await asyncio.to_thread(_load_rows, uid)
    docs = [
        d for d in docs
        if d.get("status") != "temp" and not d.get("deletedAt")
    ]
    return JSONResponse({"docs": docs}, headers={"Cache-Control": "no-store"})


async def delete_doc(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    ok = await asyncio.to_thread(_delete, uid, doc_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True})


async def doc_file(request: Request) -> FileResponse:
    """返回本人论文的原始文件,供阅读器同源加载(支持 PDF Range)。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    doc = await asyncio.to_thread(_doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    path = await asyncio.to_thread(_doc_file_path, uid, doc_id)
    if path is None:
        raise HTTPException(404, "原始文件不存在")
    active_content = path.suffix.lower() in {".html", ".htm", ".xml"}
    media = "application/octet-stream" if active_content else _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    disposition = "attachment" if active_content else "inline"
    return FileResponse(
        path, media_type=media,
        headers={
            "Content-Disposition": f'{disposition}; filename="{quote(path.name)}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def doc_text(request: Request) -> JSONResponse:
    """非 PDF 文档的分页正文:文本阅读器用,带页码与总页数。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    doc = await asyncio.to_thread(_doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    try:
        page = int(request.query_params.get("page") or 1)
    except ValueError:
        page = 1
    try:
        payload = await asyncio.to_thread(_doc_text_cache, uid, doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "原始文件不存在") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    total = len(payload)
    page = max(1, min(page, total or 1))
    item = payload[page - 1] if payload else [1, ""]
    return JSONResponse({
        "docId": doc_id, "name": doc["name"], "page": page, "total": total,
        "text": item[1],
    }, headers={"Cache-Control": "no-store"})


async def clear_docs(request: Request) -> JSONResponse:
    """清空我的论文库:删除全部论文、切片、章节树与原文件。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    removed = await asyncio.to_thread(_clear_all, uid)
    return JSONResponse({"ok": True, "removed": removed})


async def list_annotations(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    doc = await asyncio.to_thread(_doc_row, uid, doc_id)
    if doc is None or doc["deletedAt"]:
        raise HTTPException(404, "not found")
    items = await asyncio.to_thread(_list_annotations, uid, doc_id)
    return JSONResponse({"annotations": items}, headers={"Cache-Control": "no-store"})


async def save_annotation(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    body = await read_json_object(request)
    try:
        item = await asyncio.to_thread(_save_annotation, uid, doc_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(404, "not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse({"annotation": item})


async def delete_annotation(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    annotation_id = str(request.path_params.get("annotation_id") or "")
    ok = await asyncio.to_thread(_delete_annotation, uid, doc_id, annotation_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True})


async def list_projects(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    projects = await asyncio.to_thread(_load_projects, uid)
    return JSONResponse({"projects": projects}, headers={"Cache-Control": "no-store"})


async def create_project(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    body = await read_json_object(request)
    title = str(body.get("title", ""))[:120]
    project = await asyncio.to_thread(_create_project, uid, title)
    return JSONResponse({"project": project}, headers={"Cache-Control": "no-store"})


async def update_project(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    project_id = str(request.path_params.get("project_id") or "")
    body = await read_json_object(request)
    project = await asyncio.to_thread(_update_project, uid, project_id, body)
    if project is None:
        raise HTTPException(404, "not found")
    return JSONResponse({"project": project}, headers={"Cache-Control": "no-store"})


async def delete_project(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    project_id = str(request.path_params.get("project_id") or "")
    ok = await asyncio.to_thread(_delete_project, uid, project_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True})


async def search_docs(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    _rate(_search_limiter, uid)
    body = await read_json_object(request)
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(400, "query required")
    top_k = body.get("topK", 8)
    top_k = max(1, min(int(top_k) if isinstance(top_k, int) else 8, 20))
    doc_id = body.get("docId")
    doc_id = str(doc_id) if isinstance(doc_id, str) and doc_id else None
    raw_ids = body.get("docIds")
    if raw_ids is not None and not isinstance(raw_ids, list):
        raise HTTPException(400, "docIds must be a list")
    doc_ids: set[str] | None = None
    if isinstance(raw_ids, list):
        picked = {str(x) for x in raw_ids if isinstance(x, str) and x}
        doc_ids = set(list(picked)[:MAX_DOCS])
    project_id = body.get("projectId")
    project_id = str(project_id) if isinstance(project_id, str) and project_id else None
    use_tree = body.get("tree", False) is True
    started = time.monotonic()
    index = await asyncio.to_thread(_get_index, uid)
    result = await asyncio.to_thread(index.search, query, top_k, doc_id,
                                     use_tree, project_id, doc_ids)
    result["elapsed"] = round(time.monotonic() - started, 3)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


async def tree(request: Request) -> JSONResponse:
    """返回某篇论文的章节树(节点扁平列表,parentId 组树);用于检索结果定位。"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = request.query_params.get("docId", "")
    if not doc_id:
        raise HTTPException(400, "docId required")
    _, nodes, _ = await asyncio.to_thread(_load_rows, uid)
    selected = [
        {
            "id": n.id, "parentId": n.parent_id, "title": n.title,
            "summary": n.summary, "pageStart": n.page_start, "pageEnd": n.page_end,
        }
        for n in nodes if n.doc_id == doc_id
    ]
    return JSONResponse({"docId": doc_id, "nodes": selected},
                        headers={"Cache-Control": "no-store"})
