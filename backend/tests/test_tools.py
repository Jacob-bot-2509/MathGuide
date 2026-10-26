"""tools/fetch_knowledge.py:arXiv 走 HTTPS、响应上限与落盘路径安全。"""
from __future__ import annotations

from tools import fetch_knowledge as fk


def test_fetch_arxiv_uses_https(tmp_path, monkeypatch):
    urls: list[str] = []

    def fake_get(url, timeout=30):
        urls.append(url)
        return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    monkeypatch.setattr(fk, "http_get", fake_get)
    monkeypatch.setattr(fk.time, "sleep", lambda *_: None)

    assert fk.fetch_arxiv(tmp_path, 1, do_filter=False) == 0
    assert urls
    assert all(url.startswith("https://export.arxiv.org/") for url in urls)


def test_write_md_does_not_escape_output_dir(tmp_path):
    assert fk.write_md(tmp_path, "../../evil", "evil", ["keyword"], "analysis", "body")
    assert (tmp_path / "evil.md").is_file()
    assert not (tmp_path.parent / "evil.md").exists()
