import json
from contextlib import closing
from pathlib import Path

import pytest

import db
import diagnosis
import store
import usage


def test_legacy_identity_migration_reads_all_required_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(usage, "_ready_key", None)
    usage.PATH.write_text(
        json.dumps({"phone": "123", "user": "old", "ts": 100}) + "\n",
        encoding="utf-8",
    )

    assert usage.migrate_identity({"123": "u1"}) == 1
    assert len(usage.for_user("u1")) == 1
    with closing(db.connect()) as conn:
        entry = json.loads(conn.execute("SELECT doc FROM usage").fetchone()[0])
    assert "phone" not in entry and "user" not in entry


@pytest.mark.parametrize("module,filename,record", [
    (usage, "usage.jsonl", {"uid": "u1", "ts": 100}),
    (diagnosis, "diagnoses.jsonl", {"uid": "u1", "pointId": "p1", "score": 3}),
])
def test_failed_jsonl_read_is_retried(tmp_path, monkeypatch, module, filename, record):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(module, "PATH", tmp_path / filename)
    monkeypatch.setattr(module, "_ready_key", None)
    module.PATH.write_text(json.dumps(record) + "\n", encoding="utf-8")
    original_open = Path.open

    def fail_open(path, *args, **kwargs):
        if path == module.PATH:
            raise PermissionError("temporarily unavailable")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", fail_open)
        with pytest.raises(PermissionError):
            module.init()
    assert db.get_meta(module.MIGRATION_KEY) is None
    module.init()
    assert len(module.for_user("u1")) == 1


def test_failed_user_file_read_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(store, "TOKENS_PATH", tmp_path / "tokens.json")
    monkeypatch.setattr(store, "_ready_key", None)
    store.USERS_PATH.write_text(json.dumps({"u1": {"uid": "u1", "phone": "123"}}), encoding="utf-8")
    original_read = Path.read_text

    def fail_read(path, *args, **kwargs):
        if path == store.USERS_PATH:
            raise PermissionError("temporarily unavailable")
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", fail_read)
        with pytest.raises(PermissionError):
            store.init()
    assert db.get_meta(store.MIGRATION_KEY) is None
    store.init()
    assert store.find_user_by_phone("123")[0] == "u1"
