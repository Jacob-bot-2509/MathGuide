"""
知识文档加载与切片。

文档格式(backend/knowledge/*.md):
    ---
    title: 函数极限
    title_en: Limits
    keywords: ["极限", "lim"]   # JSON 数组,中英触发词(小写)
    category: analysis          # 与前端 classifier 板块 key 一致
    level: advance              # basic / advance / competition
    ---
    ## 章节标题
    正文(行内公式 $...$,块级公式 $$...$$,与前端 MathText 渲染约定一致)

切片规则:按 ## 标题切段;单节超过 MAX_SECTION_CHARS 时按段落拆分,保持公式块不被切断。
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MAX_SECTION_CHARS = 900

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
    level: str = "advance"


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


def load_knowledge(base: Path) -> list[Chunk]:
    """装载知识目录下全部 md 文档并切片"""
    chunks: list[Chunk] = []
    for path in sorted(base.glob("*.md")):
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        title = str(meta.get("title", path.stem))
        title_en = str(meta.get("title_en", title))
        keywords = [str(k).lower() for k in meta.get("keywords", [])]
        category = str(meta.get("category", "other"))
        level = str(meta.get("level", "advance"))
        sections = _SECTION_RE.split(body)
        # 首个元素为引言(无 ## 标题),后续按 [标题, 正文] 成对出现
        if sections[0].strip():
            for text in _split_section(sections[0].strip(), MAX_SECTION_CHARS):
                chunks.append(Chunk(f"{path.stem}:intro", title, title_en, "概述", text, keywords, category, level))
        for i in range(1, len(sections), 2):
            head = sections[i].strip()
            text = sections[i + 1].strip() if i + 1 < len(sections) else ""
            if not text:
                continue
            for piece in _split_section(text, MAX_SECTION_CHARS):
                chunks.append(Chunk(f"{path.stem}:{i}", title, title_en, head, piece, keywords, category, level))
    return chunks
