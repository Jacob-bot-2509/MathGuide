"""
知识文档加载与切片。

支持的文档格式(backend/knowledge/):
- *.md:带 frontmatter 的结构化文档(推荐),见下;
- *.txt:纯文本讲义/笔记,无 frontmatter 也能直接入库
  (title 取文件名,按空行分段,默认 category=other)。

md 格式:
    ---
    title: 函数极限
    title_en: Limits
    keywords: ["极限", "lim"]   # JSON 数组,中英触发词(小写)
    category: analysis          # 与前端 classifier 板块 key 一致
    ---
    ## 章节标题
    正文(行内公式 $...$,块级公式 $$...$$,与前端 MathText 渲染约定一致)

切片规则:md 按 ## 标题切段;单节超过 MAX_SECTION_CHARS 时按段落拆分,
保持公式块不被切断。PDF 等二进制格式解析见 backend/README.md(预留扩展)。
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_SECTION_CHARS = 900

class _IdGen:
    """按「文件名 + 文件内序号」生成 chunk id(embedding 缓存以此为键)。

    不能用全局自增计数:每次重建索引都从上次的计数继续,同一篇文档的 id 会整体漂移
    (`c1` → `c51`),向量缓存全部失配 —— 新增一篇论文就要把整个知识库重算一遍向量。
    按文件计数后,增删文件不影响其他文件的 id,只有改动过的文档才重算。"""

    __slots__ = ("_name", "_n")

    def __init__(self, name: str):
        self._name, self._n = name, 0

    def next(self) -> str:
        self._n += 1
        return f"{self._name}#{self._n}"

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class Chunk:
    id: str
    title: str
    title_en: str
    section: str
    text: str
    keywords: list[str] = field(default_factory=list)
    category: str = "other"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    m = _FRONT_RE.match(content)
    if not m:
        return {}, content
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            try:
                val = json.loads(val)  # keywords 用 JSON 数组,避免引入 YAML 依赖
            except json.JSONDecodeError:
                pass
        else:
            val = val.strip("\"'")
        meta[key.strip()] = val
    return meta, m.group(2).strip()


def _split_section(text: str, limit: int) -> list[str]:
    """长节按段落拆分;含 $$ 的公式块视为整体不切断"""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if buf and len(buf) + len(para) > limit:
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return parts


def _load_md(path: Path, chunks: list[Chunk]) -> None:
    ids = _IdGen(path.stem)
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    title = str(meta.get("title", path.stem))
    title_en = str(meta.get("title_en", title))
    keywords = [str(k).lower() for k in meta.get("keywords", [])]
    category = str(meta.get("category", "other"))
    sections = _SECTION_RE.split(body)
    # 首个元素为引言(无 ## 标题),后续按 [标题, 正文] 成对出现
    if sections[0].strip():
        for text in _split_section(sections[0].strip(), MAX_SECTION_CHARS):
            chunks.append(Chunk(ids.next(), title, title_en, "概述", text, keywords, category))
    for i in range(1, len(sections), 2):
        head = sections[i].strip()
        text = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if not text:
            continue
        for piece in _split_section(text, MAX_SECTION_CHARS):
            chunks.append(Chunk(ids.next(), title, title_en, head, piece, keywords, category))


def _load_txt(path: Path, chunks: list[Chunk]) -> None:
    """纯文本讲义:文件名作标题,按空行分段直接入库(无需 frontmatter)"""
    ids = _IdGen(path.stem)
    title = path.stem
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        return
    keywords = [title.lower()]
    for i, piece in enumerate(_split_section(body, MAX_SECTION_CHARS), 1):
        chunks.append(Chunk(ids.next(), title, title, f"段落{i}", piece, keywords, "other"))


def load_knowledge(base: Path) -> list[Chunk]:
    """装载知识目录下全部 md/txt 文档并切片(新增文档无需改代码)"""
    chunks: list[Chunk] = []
    for path in sorted(base.glob("*.md")):
        _load_md(path, chunks)
    for path in sorted(base.glob("*.txt")):
        _load_txt(path, chunks)
    return chunks
