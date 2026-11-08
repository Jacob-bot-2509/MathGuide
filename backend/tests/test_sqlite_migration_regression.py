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


@pytest.fixture
def legacy_data(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(store, "USERS_PATH", tmp_path / "users.json")
    monkeypatch.setattr(store, "TOKENS_PATH", tmp_path / "tokens.json")
    monkeypatch.setattr(usage, "PATH", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "LEGACY_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(diagnosis, "PATH", tmp_path / "diagnoses.jsonl")
    for module in (store, usage, diagnosis):
        monkeypatch.setattr(module, "_ready_key", None)
    users = {"u1": {"uid": "u1", "phone": "123"}, "u2": {"uid": "u2", "phone": "456"}}
    tokens = {"tok1": "u1", "tok2": "u2"}
    entries = [{"uid": "u1", "phone": "123", "ts": 100}, {"uid": "u2", "phone": "456", "ts": 200}]
    diagnoses = [{"uid": "u1", "pointId": "p", "score": 3}, {"uid": "u2", "pointId": "p", "score": 4}]
    store.USERS_PATH.write_text(json.dumps(users), encoding="utf-8")
    store.TOKENS_PATH.write_text(json.dumps(tokens), encoding="utf-8")
    usage.PATH.write_text("".join(json.dumps(row) + "\n" for row in entries), encoding="utf-8")
    usage.LEGACY_PATH.write_text(json.dumps(entries), encoding="utf-8")
    diagnosis.PATH.write_text("".join(json.dumps(row) + "\n" for row in diagnoses), encoding="utf-8")
    store.init()
    usage.init()
    diagnosis.init()


def test_delete_cleans_all_legacy_files_and_keeps_other_user(legacy_data):
    usage.delete_user("u1", "123")
    diagnosis.delete_user("u1")
    store.delete_user("u1")

    assert set(json.loads(store.USERS_PATH.read_text(encoding="utf-8"))) == {"u2"}
    assert json.loads(store.TOKENS_PATH.read_text(encoding="utf-8")) == {"tok2": "u2"}
    assert [row["uid"] for row in db.read_jsonl(usage.PATH)] == ["u2"]
    assert [row["uid"] for row in json.loads(usage.LEGACY_PATH.read_text(encoding="utf-8"))] == ["u2"]
    assert [row["uid"] for row in db.read_jsonl(diagnosis.PATH)] == ["u2"]
    assert store.find_user_by_phone("456")[0] == "u2"
    assert len(usage.for_user("u2")) == len(diagnosis.for_user("u2")) == 1


def test_backup_write_failure_leaves_account_retryable(legacy_data, monkeypatch):
    def fail_write(*args, **kwargs):
        raise OSError("disk full")
    with monkeypatch.context() as patch:
        patch.setattr(db, "write_legacy", fail_write)
        with pytest.raises(OSError):
            store.delete_user("u1")
    assert store.find_user_by_phone("123")[0] == "u1"
    assert "u1" in json.loads(store.USERS_PATH.read_text(encoding="utf-8"))
    store.delete_user("u1")
    assert store.find_user_by_phone("123") is None


@pytest.mark.parametrize("module,filename", [(usage, "usage.jsonl"), (diagnosis, "diagnoses.jsonl")])
def test_corrupt_jsonl_does_not_mark_migration_complete(tmp_path, monkeypatch, module, filename):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(module, "PATH", tmp_path / filename)
    monkeypatch.setattr(module, "_ready_key", None)
    original = '{"uid":"u1"}\n{broken\n'
    module.PATH.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        module.init()
    assert db.get_meta(module.MIGRATION_KEY) is None
    assert module.PATH.read_text(encoding="utf-8") == original
