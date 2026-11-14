"""exercises/build:构建流程的 CLI 入口与来源校验。

`build_source` 的核心路径已有测试覆盖,但 `main()`(argparse + 逐来源抓取 + 日志)
和"未知来源"这两个分支一直是空白 —— 它们是运维真正会踩的地方:
`--source` 写错、`--limit` 给 0、抓取函数返回空。
"""
from __future__ import annotations

import json

import pytest

from exercises import build, fetch


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="未知来源"):
        build.build_source("nope", {}, tmp_path)


def test_main_builds_each_requested_source(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(name, limit, seed, cache):
        calls.append((name, limit, seed, cache))
        return {}          # 空样本:只验流程与日志

    monkeypatch.setattr(fetch, "fetch_source", fake_fetch)

    exit_code = build.main([
        "--source", "math", "--limit", "5", "--output", str(tmp_path),
    ])

    assert exit_code == 0
    assert calls and calls[0][0] == "math" and calls[0][1] == 5
    assert (tmp_path / "math.manifest.json").is_file()
    manifest = json.loads((tmp_path / "math.manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "math"
    assert manifest["schema_version"] == 1


def test_main_rejects_non_positive_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "fetch_source", lambda *args: {})
    with pytest.raises(SystemExit):
        build.main(["--limit", "0", "--output", str(tmp_path)])


def test_main_defaults_to_all_sources(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(fetch, "fetch_source",
                        lambda name, *args: seen.append(name) or {})
    assert build.main(["--limit", "1", "--output", str(tmp_path)]) == 0
    assert seen == list(build.SOURCES)
