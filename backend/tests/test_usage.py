"""usage.py:JSONL 追加、旧格式迁移、上限裁剪、压实与坏行恢复。"""
from __future__ import annotations

import json

import usage


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    usage.reset_for_tests()


def _record(user: str, reply_len: int = 1, ts: float = 1.0) -> None:
    usage.record(user=user, phone="", cmd="", prompt_len=0,
                 reply_len=reply_len, role="main", research=False, ts=ts)


def _lines(tmp_path) -> list[dict]:
    path = tmp_path / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_and_summary(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    usage.record(user="A", phone="13800138000", cmd="提问", prompt_len=10,
                 reply_len=5, role="main", research=False, ts=1.0)
    usage.record(user="B", phone="", cmd="研究", prompt_len=20,
                 reply_len=7, role="deep", research=True, ts=2.0)

    summary = usage.summary()
    assert summary["calls"] == 2
    assert summary["totalChars"] == 12
    assert summary["roles"] == {"main": 1, "deep": 1}
    by_phone = {u["phone"]: u for u in summary["users"]}
    assert by_phone["13800138000"]["user"] == "A"
    assert by_phone["13800138000"]["chars"] == 5
    assert "" in by_phone


def test_records_are_appended_as_jsonl(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u1")
    _record("u2")
    assert [entry["user"] for entry in _lines(tmp_path)] == ["u1", "u2"]
    assert not (tmp_path / "usage.jsonl.tmp").exists()


def test_max_calls_trims_oldest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(usage, "_MAX_CALLS", 3)
    monkeypatch.setattr(usage, "_COMPACT_SLACK", 0)
    for i in range(5):
        _record(f"u{i}", ts=float(i))
    summary = usage.summary()
    assert summary["calls"] == 3
    assert [u["user"] for u in summary["users"]] == ["u2", "u3", "u4"]
    assert len(_lines(tmp_path)) == 3


def test_slack_allows_append_then_compacts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(usage, "_MAX_CALLS", 2)
    monkeypatch.setattr(usage, "_COMPACT_SLACK", 2)
    for i in range(4):
        _record(f"u{i}", ts=float(i))
    # 内存严格 2 条,文件允许 2+2 行
    assert usage.summary()["calls"] == 2
    assert len(_lines(tmp_path)) == 4
    _record("u4", ts=5.0)  # 超过 MAX+SLACK,触发压实
    assert len(_lines(tmp_path)) == 2
    assert [u["user"] for u in usage.summary()["users"]] == ["u3", "u4"]


def test_legacy_json_array_is_migrated_on_write(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = [
        {"user": "old1", "phone": "", "cmd": "", "prompt_len": 0,
         "reply_len": 2, "role": "main", "research": False, "ts": 1.0},
        {"user": "old2", "phone": "", "cmd": "", "prompt_len": 0,
         "reply_len": 3, "role": "deep", "research": True, "ts": 2.0},
    ]
    (tmp_path / "usage.json").write_text(json.dumps(legacy), encoding="utf-8")

    assert usage.summary()["calls"] == 2
    _record("new", reply_len=4, ts=3.0)

    assert [entry["user"] for entry in _lines(tmp_path)] == ["old1", "old2", "new"]
    assert (tmp_path / "usage.json").exists()  # 旧文件保留作备份


def test_corrupt_jsonl_is_cleaned_on_next_write(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    path = tmp_path / "usage.jsonl"
    path.write_text(
        '\n'.join([
            json.dumps({"user": "ok", "reply_len": 1, "role": "main"}),
            "{not json",
            json.dumps([1, 2, 3]),
            "",
        ]) + "\n",
        encoding="utf-8",
    )

    assert usage.summary()["calls"] == 1
    _record("new", reply_len=1)
    lines = _lines(tmp_path)
    assert [entry["user"] for entry in lines] == ["ok", "new"]
