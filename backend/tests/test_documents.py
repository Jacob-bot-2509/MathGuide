"""rag/documents.py:frontmatter、关键词归一与切片不丢内容。"""
from __future__ import annotations

from rag import documents


def test_normalize_keywords_accepts_list_and_bare_string():
    assert documents._normalize_keywords(["极限", "Limit"]) == ["极限", "limit"]
    assert documents._normalize_keywords("极限") == ["极限"]
    assert documents._normalize_keywords(None) == []
    assert documents._normalize_keywords({"x": 1}) == []
    assert documents._normalize_keywords(["  ", "limit"]) == ["limit"]


def test_split_section_keeps_display_math_intact_and_preserves_text():
    text = "intro\n\n$$\na\n\nb\n$$\n\noutro"
    parts = documents._split_section(text, 20)
    assert any("$$\na\n\nb\n$$" in part for part in parts)
    assert "\n\n".join(parts) == text


def test_split_section_does_not_split_a_single_long_paragraph():
    text = "x" * 100
    assert documents._split_section(text, 20) == [text]


def test_split_section_preserves_plain_text():
    text = "\n\n".join(["段落" * 10, "第二段" * 10, "第三段" * 10])
    parts = documents._split_section(text, 50)
    assert "\n\n".join(parts) == text
    assert all(part for part in parts)


def test_load_md_handles_bare_string_keywords(tmp_path):
    path = tmp_path / "limits.md"
    path.write_text(
        "---\n"
        "title: 函数极限\n"
        "title_en: Limits\n"
        "keywords: 极限\n"
        "category: analysis\n"
        "---\n\n"
        "## 定义\n"
        "极限的定义是 $\\lim_{x\\to 0} x = 0$。\n",
        encoding="utf-8",
    )
    chunks: list[documents.Chunk] = []
    documents._load_md(path, chunks)
    assert chunks
    assert chunks[0].title == "函数极限"
    assert chunks[0].keywords == ["极限"]
    assert chunks[0].section == "定义"


def test_load_knowledge_reads_md_and_txt(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\ntitle: A\nkeywords: [\"a\", \"alpha\"]\n---\n\n## H\nbody a\n",
        encoding="utf-8",
    )
    (tmp_path / "b.txt").write_text("line one\n\nline two", encoding="utf-8")
    chunks = documents.load_knowledge(tmp_path)
    titles = {c.title for c in chunks}
    assert titles == {"A", "b"}
    assert all(c.id for c in chunks)


def test_load_knowledge_skips_undecodable_file(tmp_path):
    (tmp_path / "good.md").write_text(
        "---\ntitle: Good\n---\n\n## H\ntext\n", encoding="utf-8")
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00\x00")
    chunks = documents.load_knowledge(tmp_path)
    assert {c.title for c in chunks} == {"Good"}
