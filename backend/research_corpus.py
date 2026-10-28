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
import math
import re
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import require_auth
from http_utils import read_json_object
from rag import embed as embed_mod

DATA_DIR = Path(__file__).resolve().parent / "data" / "research"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # 单文件 20MB
MAX_DOCS = 200                         # 每用户论文数上限
MAX_PAGES = 300                        # 单篇页数上限
CHUNK_CHARS = 900                      # 切片目标长度
SUMMARY_CHARS = 220                    # 节点摘要长度
SNIPPET_CHARS = 320

# BM25 参数(业界默认值)
K1 = 1.2
B = 0.75
RRF_K = 60

_UID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RUN_RE = re.compile(r"[一-鿿]+")
_NUMBERED_HEAD_RE = re.compile(r"^\s*(?:#{1,3}\s+|\d+(?:\.\d+)*[\.、)]?\s+)\S")
_KNOWN_HEADINGS = {
    "abstract", "introduction", "related work", "background", "methods",
    "method", "methodology", "results", "discussion", "conclusion",
    "conclusions", "references", "appendix", "acknowledgements",
    "摘要", "引言", "绪论", "相关工作", "背景", "方法", "实验", "结果",
    "讨论", "结论", "参考文献", "附录", "致谢",
}


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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS docs("
        "id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,"
        "sha TEXT NOT NULL, pages INTEGER NOT NULL, created_at REAL NOT NULL,"
        "mime TEXT NOT NULL DEFAULT '')"
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_doc ON nodes(doc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id)")
    return conn


# ---------- 解析与切片 ----------

def _pdf_pages(data: bytes) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ValueError("PDF 已加密,无法读取") from exc
        pages: list[tuple[int, str]] = []
        for index, page in enumerate(reader.pages[:MAX_PAGES], start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 单页解析失败不拖垮整篇
                text = ""
            pages.append((index, text))
        return pages
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"PDF 解析失败: {exc}") from exc


def _text_pages(data: bytes) -> list[tuple[int, str]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("gb18030", errors="replace")
    return [(1, text)]


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


def _heading_level(title: str) -> int:
    """按编号估算层级:"1" → 1,"1.2" → 2;无编号(Abstract 等)按一级。"""
    m = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    return m.group(1).count(".") + 1 if m else 1


def _sections(pages: list[tuple[int, str]]) -> list[Section]:
    sections: list[Section] = []
    cur = Section("正文", pages[0][0] if pages else 1, pages[0][0] if pages else 1)
    parts: list[str] = []

    def flush() -> None:
        text = "\n".join(parts).strip()
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
                parts = []
                cur = Section(line[:80], page_no, page_no)
                continue
            parts.append(line)
            cur.page_end = page_no
    flush()
    return sections or [Section("全文", 1, 1, "\n".join(t for _, t in pages).strip())]


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


def _chunk_section(section: Section) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", section.text) if p.strip()]
    if len(paras) <= 1:
        paras = [_clean_line(p) for p in section.text.splitlines() if _clean_line(p)]
    pieces: list[str] = []
    for para in paras:
        pieces.extend(_split_long(para, CHUNK_CHARS))
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if not buf:
            buf = piece
        elif len(buf) + len(piece) + 2 <= CHUNK_CHARS:
            buf = f"{buf}\n\n{piece}"
        else:
            chunks.append(buf)
            buf = piece
    if buf:
        chunks.append(buf)
    return chunks


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

    def search(self, query: str, top_k: int = 8, doc_id: str | None = None,
               use_tree: bool = True) -> dict:
        self._ensure_vectors()
        allowed_chunks = [i for i, c in enumerate(self.chunks)
                          if doc_id is None or c.doc_id == doc_id]
        allowed_nodes = [i for i, n in enumerate(self.nodes)
                         if doc_id is None or n.doc_id == doc_id]

        # 章节树:先按节点标题+摘要排序,取前 5 个节点作为候选区
        node_rank = self._bm25(query, allowed_nodes, self.node_tf,
                               self.node_avgdl, self.node_idf)
        vec_nodes = self._vector_rank(query, self._node_vectors, allowed_nodes)
        fused_nodes = self._rrf([i for i, _ in node_rank], vec_nodes)
        top_node_ids = {self.nodes[i].id for i, _ in fused_nodes[:5]} if use_tree else set()

        if use_tree and top_node_ids:
            allowed_chunks = [i for i in allowed_chunks
                              if self.chunks[i].node_id in top_node_ids]

        lex = self._bm25(query, allowed_chunks, self.tf, self.avgdl, self.idf)
        vec = self._vector_rank(query, self._chunk_vectors, allowed_chunks)
        fused = self._rrf([i for i, _ in lex], vec)
        if not fused:
            # 树筛完没有命中就退回全库,避免"节点分错 → 永远搜不到"
            if use_tree and top_node_ids:
                return self.search(query, top_k=top_k, doc_id=doc_id, use_tree=False)
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
_index_paths: dict[str, float] = {}
_index_lock = threading.Lock()


def _load_rows(uid: str) -> tuple[list[dict], list[NodeRec], list[ChunkRec]]:
    conn = _connect(uid)
    try:
        docs = [
            {"id": r[0], "name": r[1], "size": r[2], "pages": r[4], "createdAt": r[5]}
            for r in conn.execute(
                "SELECT id, name, size, sha, pages, created_at FROM docs ORDER BY created_at DESC")
        ]
        nodes = [NodeRec(*r) for r in conn.execute(
            "SELECT id, doc_id, parent_id, title, summary, page_start, page_end, text FROM nodes")]
        chunks = [ChunkRec(*r) for r in conn.execute(
            "SELECT id, doc_id, node_id, page_start, page_end, section, text FROM chunks")]
        return docs, nodes, chunks
    finally:
        conn.close()


def _get_index(uid: str) -> UserIndex:
    path = _db_path(uid)
    mtime = path.stat().st_mtime if path.exists() else 0.0
    with _index_lock:
        cached = _indexes.get(uid)
        if cached is not None and _index_paths.get(uid) == mtime:
            return cached
        if not path.exists():
            empty = UserIndex(uid, [], [], [], None)
            _indexes[uid] = empty
            _index_paths[uid] = mtime
            return empty
        docs, nodes, chunks = _load_rows(uid)
        embedder = None
        if embed_mod.is_configured():
            try:
                embedder = embed_mod.Embedder(cache_path=_user_dir(uid) / ".embeddings.json")
            except Exception as exc:  # noqa: BLE001
                print(f"[research] embedding 初始化失败,纯 BM25: {exc}")
        index = UserIndex(uid, docs, nodes, chunks, embedder)
        _indexes[uid] = index
        _index_paths[uid] = mtime
        return index


# ---------- 入库 / 删除 ----------

def _ingest(uid: str, name: str, data: bytes, mime: str) -> dict:
    if not name or len(name) > 200:
        raise ValueError("文件名缺失或过长")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")
    lower = name.lower()
    is_pdf = lower.endswith(".pdf") or mime == "application/pdf"
    if not is_pdf and not (
        lower.endswith((".txt", ".md", ".markdown", ".tex", ".csv", ".json"))
        or mime.startswith("text/")
    ):
        raise ValueError("只支持 PDF 与文本类文件")

    sha = hashlib.sha256(data).hexdigest()
    doc_id = sha[:16]
    pages = _pdf_pages(data) if is_pdf else _text_pages(data)
    total = sum(len(t) for _, t in pages)
    if total < 50:
        raise ValueError("没有提取到正文:可能是扫描版 PDF,请先做 OCR")

    sections = _sections(pages)
    conn = _connect(uid)
    try:
        exists = conn.execute("SELECT id FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if exists:
            return {"docId": doc_id, "duplicate": True}
        count = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        if count >= MAX_DOCS:
            raise ValueError(f"论文数量达到上限 {MAX_DOCS}")
        now = time.time()
        conn.execute(
            "INSERT INTO docs(id, name, size, sha, pages, created_at, mime) VALUES (?,?,?,?,?,?,?)",
            (doc_id, name, len(data), sha, len(pages), now, mime))
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
            summary = _clean_line(section.text)[:SUMMARY_CHARS]
            nodes.append((node_id, doc_id, parent_id, section.title, summary,
                          section.page_start, section.page_end, section.text[:20000]))
            for ci, text in enumerate(_chunk_section(section), start=1):
                chunks.append((f"{doc_id}#s{si}c{ci}", doc_id, node_id,
                               section.page_start, section.page_end, section.title, text))
        conn.executemany(
            "INSERT INTO nodes(id, doc_id, parent_id, title, summary, page_start, page_end, text)"
            " VALUES (?,?,?,?,?,?,?,?)", nodes)
        conn.executemany(
            "INSERT INTO chunks(id, doc_id, node_id, page_start, page_end, section, text)"
            " VALUES (?,?,?,?,?,?,?)", chunks)
        conn.commit()
    finally:
        conn.close()

    # 原文件落盘(只存一份;重名不覆盖,doc_id 已按内容去重)
    suffix = ".pdf" if is_pdf else Path(name).suffix.lower()[:10] or ".txt"
    try:
        (_user_dir(uid) / "files" / f"{doc_id}{suffix}").write_bytes(data)
    except OSError as exc:
        print(f"[research] 原文件保存失败(索引已入库): {exc}")

    with _index_lock:
        _indexes.pop(uid, None)
    return {"docId": doc_id, "duplicate": False, "pages": len(pages),
            "sections": len(sections), "chunks": len(chunks)}


def _delete(uid: str, doc_id: str) -> bool:
    conn = _connect(uid)
    try:
        found = conn.execute("SELECT id FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if not found:
            return False
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM nodes WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM docs WHERE id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    for path in (_user_dir(uid) / "files").glob(f"{doc_id}.*"):
        try:
            path.unlink()
        except OSError:
            pass
    with _index_lock:
        _indexes.pop(uid, None)
    return True


def corpus_stamp(uid: str) -> str:
    """语料版本(DB mtime):上传/删除后让研究答案缓存失效。库不存在返回 0。"""
    path = _db_path(uid)
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return "0"


def chat_hits(uid: str, question: str, top_k: int = 4) -> list[dict]:
    """科研对话用:返回用户自己论文的命中片段;库空时返回空列表。"""
    index = _get_index(uid)
    if not index.chunks:
        return []
    return index.search(question, top_k=top_k)["hits"]


def docs_for_export(uid: str) -> list[dict]:
    """账号导出用:只含论文元数据,不含正文与原文件。"""
    if not _db_path(uid).exists():
        return []
    return _load_rows(uid)[0]


def delete_user(uid: str) -> None:
    """注销/留存清理:删除该用户的整个语料目录(原文件、索引、向量缓存)。"""
    path = DATA_DIR / _safe_uid(uid)
    shutil.rmtree(path, ignore_errors=True)
    with _index_lock:
        _indexes.pop(uid, None)
        _index_paths.pop(uid, None)


# ---------- HTTP 接口 ----------
async def _read_limited(request: Request) -> bytes:
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限")
        chunks.append(chunk)
    return b"".join(chunks)


async def upload_doc(request: Request) -> JSONResponse:
    """上传论文:原始字节放 body,文件名放 ?name=(前端 encodeURIComponent)。

    不用 multipart:只传一个文件,省一层解析依赖;文件名只用于展示,
    落盘路径用内容哈希,杜绝路径穿越。
    """
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    name = request.query_params.get("name", "").strip()
    data = await _read_limited(request)
    if not data:
        raise HTTPException(400, "empty file")
    try:
        result = await asyncio.to_thread(
            _ingest, uid, name, data, request.headers.get("content-type", ""))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse({"ok": True, **result})


async def list_docs(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    docs, _, _ = await asyncio.to_thread(_load_rows, uid)
    return JSONResponse({"docs": docs}, headers={"Cache-Control": "no-store"})


async def delete_doc(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    doc_id = str(request.path_params.get("doc_id") or "")
    ok = await asyncio.to_thread(_delete, uid, doc_id)
    if not ok:
        raise HTTPException(404, "not found")
    return JSONResponse({"ok": True})


async def search_docs(request: Request) -> JSONResponse:
    rec = require_auth(request)
    uid = str(rec.get("uid") or "")
    body = await read_json_object(request)
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(400, "query required")
    top_k = body.get("topK", 8)
    top_k = max(1, min(int(top_k) if isinstance(top_k, int) else 8, 20))
    doc_id = body.get("docId")
    doc_id = str(doc_id) if isinstance(doc_id, str) and doc_id else None
    use_tree = body.get("tree", True) is not False
    started = time.monotonic()
    index = await asyncio.to_thread(_get_index, uid)
    result = await asyncio.to_thread(index.search, query, top_k, doc_id, use_tree)
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
