"""usage.py:JSONL 追加、旧格式迁移、身份字段清洗、按账号导出/删除与压实。"""
from __future__ import annotations

import json

import usage


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    usage.reset_for_tests()


def _record(uid: str, reply_len: int = 1, ts: float = 1.0) -> None:
    usage.record(uid=uid, cmd="", prompt_len=0,
                 reply_len=reply_len, role="main", research=False, ts=ts)


def _lines(tmp_path) -> list[dict]:
    path = tmp_path / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_and_summary(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    usage.record(uid="u-A", cmd="提问", prompt_len=10,
                 reply_len=5, role="main", research=False, ts=1.0)
    usage.record(uid="u-B", cmd="研究", prompt_len=20,
                 reply_len=7, role="deep", research=True, ts=2.0)

    summary = usage.summary()
    assert summary["calls"] == 2
    assert summary["totalChars"] == 12
    assert summary["roles"] == {"main": 1, "deep": 1}
    by_uid = {u["uid"]: u for u in summary["users"]}
    assert by_uid["u-A"]["chars"] == 5
    assert by_uid["u-B"]["chars"] == 7
    # 新记录不再携带手机号/昵称
    for entry in _lines(tmp_path):
        assert "uid" in entry
        assert "phone" not in entry and "user" not in entry


def test_records_are_appended_as_jsonl(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u1")
    _record("u2")
    assert [entry["uid"] for entry in _lines(tmp_path)] == ["u1", "u2"]
    assert not (tmp_path / "usage.jsonl.tmp").exists()


def test_max_calls_trims_oldest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(usage, "_MAX_CALLS", 3)
    monkeypatch.setattr(usage, "_COMPACT_SLACK", 0)
    for i in range(5):
        _record(f"u{i}", ts=float(i))
    summary = usage.summary()
    assert summary["calls"] == 3
    assert [u["uid"] for u in summary["users"]] == ["u2", "u3", "u4"]
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
    assert [u["uid"] for u in usage.summary()["users"]] == ["u3", "u4"]


def test_legacy_json_array_is_migrated_on_write(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = [
        {"user": "old1", "phone": "13800138000", "cmd": "", "prompt_len": 0,
         "reply_len": 2, "role": "main", "research": False, "ts": 1.0},
        {"user": "old2", "phone": "", "cmd": "", "prompt_len": 0,
         "reply_len": 3, "role": "deep", "research": True, "ts": 2.0},
    ]
    (tmp_path / "usage.json").write_text(json.dumps(legacy), encoding="utf-8")

    assert usage.summary()["calls"] == 2
    usage.migrate_identity({"13800138000": "u-old1"})
    _record("new", reply_len=4, ts=3.0)

    lines = _lines(tmp_path)
    assert [entry["uid"] for entry in lines] == ["u-old1", "anonymous", "new"]
    assert all("phone" not in entry and "user" not in entry for entry in lines)
    assert (tmp_path / "usage.json").exists()  # 旧文件保留作备份
    backup = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert all("phone" not in entry and "user" not in entry for entry in backup), "旧备份里还留着 PII"


def test_migrate_identity_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A")
    assert usage.migrate_identity({"13800138000": "u-A"}) == 0
    assert usage.migrate_identity({}) == 0


def test_for_user_scopes_and_redacts_legacy(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A", reply_len=2)
    _record("u-B", reply_len=3)
    path = tmp_path / "usage.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": 9.0, "user": "old", "phone": "13800138000",
            "cmd": "旧", "prompt_len": 1, "reply_len": 4,
            "role": "main", "research": False,
        }, ensure_ascii=False) + "\n")
    usage.reset_for_tests()

    rows = usage.for_user("u-A")
    assert [row["reply_len"] for row in rows] == [2]
    assert all("phone" not in row and "user" not in row and "uid" not in row for row in rows)

    legacy_rows = usage.for_user("u-legacy", "13800138000")
    assert len(legacy_rows) == 1 and legacy_rows[0]["reply_len"] == 4
    assert "phone" not in legacy_rows[0] and "user" not in legacy_rows[0]


def test_delete_user_removes_uid_and_legacy_phone_records(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _record("u-A", reply_len=2)
    _record("u-B", reply_len=3)
    with (tmp_path / "usage.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": 9.0, "user": "old", "phone": "13800138000",
            "cmd": "旧", "prompt_len": 1, "reply_len": 4,
            "role": "main", "research": False,
        }, ensure_ascii=False) + "\n")
    usage.reset_for_tests()

    assert usage.delete_user("missing") == 0
    assert usage.delete_user("u-A") == 1
    assert [entry.get("uid") for entry in _lines(tmp_path)] == ["u-B", None]
    assert usage.delete_user("u-legacy", "13800138000") == 1
    assert [entry["uid"] for entry in _lines(tmp_path)] == ["u-B"]
    assert usage.summary()["calls"] == 1


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
    assert lines[-1]["uid"] == "new"
    assert len(lines) == 2


def test_delete_user_cleans_legacy_backup(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    legacy = [
        {"uid": "u-A", "ts": 1.0, "cmd": "", "prompt_len": 0, "reply_len": 1,
         "role": "main", "research": False},
        {"uid": "u-B", "ts": 2.0, "cmd": "", "prompt_len": 0, "reply_len": 2,
         "role": "main", "research": False},
    ]
    (tmp_path / "usage.json").write_text(json.dumps(legacy), encoding="utf-8")

    # 一条来自 JSONL(迁移后) + 一条来自旧备份
    assert usage.delete_user("u-A") == 2
    backup = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
    assert [entry["uid"] for entry in backup] == ["u-B"]
    assert [entry["uid"] for entry in _lines(tmp_path)] == ["u-B"]
