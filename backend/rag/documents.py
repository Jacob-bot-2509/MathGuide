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


def _normalize_keywords(value: object) -> list[str]:
    """frontmatter keywords → 小写词表。

    必须是 JSON 数组;写成裸字符串(如 `keywords: 极限`)时按整词处理。
    旧实现直接迭代字符串,会把「极限」拆成 ['极','限'] 两个单字触发词。
    """
    if isinstance(value, str):
        value = [value]
    elif not isinstance(value, list):
        return []
    return [str(k).strip().lower() for k in value if str(k).strip()]


def _split_section(text: str, limit: int) -> list[str]:
    """长节按段落拆分;$$...$$ 公式块内部的空行不作为切分点。

    单段本身超过 limit 时不强行再切:把公式/表格从中间切断比超限更糟。
    """
    if len(text) <= limit:
        return [text]

    # 先按空行聚成「不会被公式块内部空行拆散」的段落
    paragraphs: list[str] = []
    buf: list[str] = []
    in_math = False
    for para in text.split("\n\n"):
        buf.append(para)
        if para.count("$$") % 2:
            in_math = not in_math
        if not in_math:
            paragraphs.append("\n\n".join(buf))
            buf = []
    if buf:
        paragraphs.append("\n\n".join(buf))

    # 再按 limit 装箱,段落是原子单位
    parts: list[str] = []
    cur = ""
    for para in paragraphs:
        if cur and len(cur) + 2 + len(para) > limit:
            parts.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        parts.append(cur)
    return parts


def _load_md(path: Path, chunks: list[Chunk]) -> None:
    ids = _IdGen(path.stem)
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    title = str(meta.get("title", path.stem))
    title_en = str(meta.get("title_en", title))
    keywords = _normalize_keywords(meta.get("keywords"))
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
    """装载知识目录下全部 md/txt 文档并切片(新增文档无需改代码)。

    单个文件坏掉(编码不是 UTF-8、被占用、frontmatter 畸形)只跳过该文件并
    告警:知识库属于外部数据,一个坏文件不应该让整个后端起不来。
    """
    chunks: list[Chunk] = []
    for pattern, loader in (("*.md", _load_md), ("*.txt", _load_txt)):
        for path in sorted(base.glob(pattern)):
            try:
                loader(path, chunks)
            except Exception as exc:  # noqa: BLE001 坏文件跳过,但必须留痕
                print(f"[rag] 跳过无法解析的知识文件 {path.name}: {exc}")
    return chunks
