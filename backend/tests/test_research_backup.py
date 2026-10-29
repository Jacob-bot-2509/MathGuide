"""科研语料备份/恢复脚本:归档往返。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import research_corpus as rc

SAMPLE = """1 Introduction
Attention lets a model weight relevant context for long documents.
This paragraph is long enough to be indexed as a chunk.
"""


def _load_tool():
    path = Path(__file__).resolve().parent.parent / "tools" / "research_backup.py"
    spec = importlib.util.spec_from_file_location("research_backup", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_backup_and_restore_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    rc._indexes.clear()
    rc._index_paths.clear()
    rc._ingest("u-b", "a.txt", SAMPLE.encode("utf-8"), "text/plain")

    tool = _load_tool()
    archive = tmp_path / "backup.tar.gz"
    tool.backup("u-b", archive)
    assert archive.is_file()

    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "restored")
    tool.restore("u-b", archive, force=True)
    db = tmp_path / "restored" / "u-b" / "index.sqlite3"
    assert db.is_file()
    assert rc.chat_hits("u-b", "attention")
