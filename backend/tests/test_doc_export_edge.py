"""doc.py 的浏览器查找与 HTML→PDF 打印链路（A 方案：服务器装 chromium）。

为什么单独测:`_find_edge` 决定"这台机器能不能出 PDF",而 `_html_to_pdf` 的五条失败路径
(未装浏览器 / 打印超时 / 没产出文件 / 产物不是 PDF / 正常)全都只在真实部署环境才会遇到。
这里用假的浏览器可执行文件 + 假 subprocess 把调用链跑通,不需要真的装浏览器。

`MG_EDGE_PATH` 的语义也在这里钉死:**配了但文件不存在 → 返回 None**,不做兜底,
否则配错了会悄悄换浏览器,PDF 与预期不一致却查不出原因。
"""
from __future__ import annotations

import subprocess

import pytest

import doc

# ---------- 浏览器查找 ----------

def test_edge_path_env_wins(tmp_path, monkeypatch):
    fake = tmp_path / "chromium"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("MG_EDGE_PATH", str(fake))
    assert doc._find_edge() == str(fake)


def test_edge_path_env_invalid_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv("MG_EDGE_PATH", str(tmp_path / "missing-browser"))
    # 即使 PATH 里有 msedge,也不能兜底
    monkeypatch.setattr(doc.shutil, "which", lambda _name: "/usr/bin/msedge")
    assert doc._find_edge() is None


def test_edge_found_in_known_candidates(tmp_path, monkeypatch):
    fake = tmp_path / "msedge.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.delenv("MG_EDGE_PATH", raising=False)
    monkeypatch.setattr(doc, "_EDGE_CANDIDATES", (fake,))
    assert doc._find_edge() == str(fake)


def test_edge_found_via_path_commands(monkeypatch):
    monkeypatch.delenv("MG_EDGE_PATH", raising=False)
    monkeypatch.setattr(doc, "_EDGE_CANDIDATES", ())
    monkeypatch.setattr(doc.shutil, "which", lambda name: "/usr/bin/chromium" if name == "chromium" else None)
    assert doc._find_edge() == "/usr/bin/chromium"


def test_edge_missing_everywhere(monkeypatch):
    monkeypatch.delenv("MG_EDGE_PATH", raising=False)
    monkeypatch.setattr(doc, "_EDGE_CANDIDATES", ())
    monkeypatch.setattr(doc.shutil, "which", lambda _name: None)
    assert doc._find_edge() is None


def test_katex_dir_falls_back_to_last_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_KATEX_CANDIDATES", (tmp_path / "a", tmp_path / "b"))
    assert doc._katex_dir() == tmp_path / "b"


# ---------- HTML → PDF ----------

def _html(tmp_path):
    path = tmp_path / "doc.html"
    path.write_text("<html>公式 \\(x^2\\)</html>", encoding="utf-8")
    return path


def test_no_browser_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_edge", lambda: None)
    assert doc._html_to_pdf(_html(tmp_path), tmp_path / "out.pdf") is None


def test_print_timeout_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_edge", lambda: "/usr/bin/chromium")

    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="chromium", timeout=60)

    monkeypatch.setattr(doc.subprocess, "run", boom)
    assert doc._html_to_pdf(_html(tmp_path), tmp_path / "out.pdf") is None


def test_missing_output_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_edge", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(doc.subprocess, "run", lambda *a, **k: None)
    assert doc._html_to_pdf(_html(tmp_path), tmp_path / "out.pdf") is None


def test_non_pdf_output_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_edge", lambda: "/usr/bin/chromium")
    out = tmp_path / "out.pdf"
    out.write_bytes(b"<html>not a pdf</html>")
    monkeypatch.setattr(doc.subprocess, "run", lambda *a, **k: None)
    assert doc._html_to_pdf(_html(tmp_path), out) is None


def test_successful_print_uses_headless_flags_and_returns_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(doc, "_find_edge", lambda: "/usr/bin/chromium")
    out = tmp_path / "out.pdf"
    seen: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        seen.append(cmd)
        out.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(doc.subprocess, "run", fake_run)

    data = doc._html_to_pdf(_html(tmp_path), out)

    assert data == b"%PDF-1.4 fake"
    command = " ".join(seen[0])
    assert "--headless=new" in command
    assert "--print-to-pdf=" in command
    assert "--virtual-time-budget" in command


# ---------- 对外入口 ----------

def test_render_pdf_bytes_normalizes_language_and_delegates(tmp_path, monkeypatch):
    captured = {}

    def fake_html_to_pdf(html_path, pdf_path):
        captured["html"] = html_path.read_text(encoding="utf-8")
        return b"%PDF-1.4 ok"

    monkeypatch.setattr(doc, "_html_to_pdf", fake_html_to_pdf)
    monkeypatch.setattr(doc, "_katex_dir", lambda: tmp_path)

    data = doc.render_pdf_bytes({"title": "标题", "sections": []}, lang="fr")

    assert data == b"%PDF-1.4 ok"
    # lang 非法时按 zh 渲染:至少要产出非空 HTML 且走 KaTeX 链接
    assert captured["html"].strip()
    assert "katex" in captured["html"]
