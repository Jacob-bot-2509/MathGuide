"""Regression tests for research history, quota, and original-file safety."""
import time

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_corpus as rc


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    rc._indexes.clear()
    rc._index_paths.clear()
    yield
    rc._indexes.clear()
    rc._index_paths.clear()


def ingest(uid="u", suffix="", status="temp"):
    return rc._ingest(uid, "a.txt", ("attention content for research " * 8 + suffix).encode(),
                      "text/plain", status=status, analyze=False)


def test_delete_and_reingest_invalidate_search_cache(corpus):
    doc = ingest()
    did = doc["docId"]
    assert rc._get_index("u").search("attention", doc_id=did)["hits"]
    assert rc._history_delete("u", did)
    assert rc._get_index("u").search("attention", doc_id=did)["hits"] == []
    result = ingest()
    assert result["status"] == "temp"
    assert rc._doc_row("u", did)["status"] == "temp"
    assert rc._get_index("u").search("attention", doc_id=did)["hits"]


def test_expired_cannot_restore(corpus):
    did = ingest()["docId"]
    assert rc._history_delete("u", did)
    conn = rc._connect("u")
    conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?", (time.time() - 1, did))
    conn.commit()
    conn.close()
    assert rc._history_restore("u", did) is False


def test_purge_does_not_delete_a_concurrently_restored_record(corpus, monkeypatch):
    did = ingest()["docId"]
    assert rc._history_delete("u", did)
    conn = rc._connect("u")
    conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?", (time.time() - 1, did))
    conn.commit()
    conn.close()
    original = rc._delete

    def restore_before_delete(uid, doc_id, **kwargs):
        conn = rc._connect(uid)
        conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?", (time.time() + 100, doc_id))
        conn.commit()
        conn.close()
        assert rc._history_restore(uid, doc_id)
        return original(uid, doc_id, **kwargs)

    monkeypatch.setattr(rc, "_delete", restore_before_delete)
    assert rc.purge_expired_history("u") == 0
    assert rc._doc_row("u", did) is not None
    assert rc._doc_file_path("u", did).exists()


def test_clear_library_removes_only_its_annotations(corpus):
    regular = ingest(status="uploaded")
    temporary = ingest(suffix=" temporary", status="temp")
    for doc in (regular, temporary):
        rc._save_annotation("u", doc["docId"], {"page": 1, "quote": "attention", "rects": []})
    assert rc._clear_all("u") == 1
    conn = rc._connect("u")
    rows = conn.execute("SELECT doc_id FROM annotations").fetchall()
    conn.close()
    assert rows == [(temporary["docId"],)]


def test_html_file_is_not_served_as_executable_inline(corpus, monkeypatch):
    data = b"<html><script>window.example=1</script>" + b"research text " * 8 + b"</html>"
    doc = rc._ingest("u", "test.html", data, "text/html", analyze=False)
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u"})
    app = Starlette(routes=[Route("/docs/{doc_id}/file", rc.doc_file)])
    with TestClient(app) as client:
        response = client.get("/docs/" + doc["docId"] + "/file")
    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-type"].startswith("application/octet-stream")


def test_temporary_storage_is_separate_from_formal_storage(corpus, monkeypatch):
    data = ("attention content for research " * 8).encode()
    monkeypatch.setattr(rc, "_max_total_bytes", lambda: len(data) + 10)
    regular = ingest(status="uploaded")
    temporary = ingest(suffix=" temp", status="temp")
    assert rc._doc_row("u", regular["docId"]) is not None
    assert rc._doc_row("u", temporary["docId"]) is not None
    with pytest.raises(ValueError):
        rc._import_temp("u", temporary["docId"], None)
    with pytest.raises(ValueError):
        ingest(suffix=" temp", status="uploaded")
    assert rc._doc_row("u", temporary["docId"])["status"] == "temp"
    assert rc._history_delete("u", temporary["docId"])
    with pytest.raises(ValueError):
        ingest(suffix=" temp", status="uploaded")
    assert rc._doc_row("u", temporary["docId"])["deletedAt"]


def test_pdf_file_remains_inline_and_supports_ranges(corpus, tmp_path, monkeypatch):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-1.7 test document")
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "u"})
    monkeypatch.setattr(rc, "_doc_row", lambda uid, doc_id: {"deletedAt": 0})
    monkeypatch.setattr(rc, "_doc_file_path", lambda uid, doc_id: path)
    app = Starlette(routes=[Route("/docs/{doc_id}/file", rc.doc_file)])
    with TestClient(app) as client:
        response = client.get("/docs/a/file", headers={"Range": "bytes=0-3"})
    assert response.status_code == 206
    assert response.content == b"%PDF"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["cache-control"] == "private, no-store"


def test_expired_file_delete_failure_keeps_record_for_retry(corpus, monkeypatch):
    from pathlib import Path

    did = ingest()["docId"]
    assert rc._history_delete("u", did)
    conn = rc._connect("u")
    conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?", (time.time() - 1, did))
    conn.commit()
    conn.close()
    original_unlink = Path.unlink

    def failing_unlink(path, *args, **kwargs):
        if path.name.startswith(did):
            raise OSError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    with pytest.raises(OSError):
        rc.purge_expired_history("u")
    assert rc._doc_row("u", did)["deletedAt"]


def test_reopening_expired_paper_does_not_recover_old_annotations(corpus):
    did = ingest()["docId"]
    rc._save_annotation("u", did, {"page": 1, "quote": "attention", "rects": []})
    assert rc._history_delete("u", did)
    conn = rc._connect("u")
    conn.execute("UPDATE docs SET purge_after = ? WHERE id = ?", (time.time() - 1, did))
    conn.commit()
    conn.close()
    assert ingest()["docId"] == did
    assert rc._list_annotations("u", did) == []


def test_reopening_during_eviction_keeps_new_file(corpus, monkeypatch):
    import threading
    from pathlib import Path

    monkeypatch.setattr(rc, "TEMP_DOC_LIMIT", 1)
    first = ingest()
    did = first["docId"]
    entered = threading.Event()
    release = threading.Event()
    original_unlink = Path.unlink
    errors = []

    def delayed_unlink(path, *args, **kwargs):
        if path.name.startswith(did) and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original_unlink(path, *args, **kwargs)

    def run(suffix):
        try:
            ingest(suffix=suffix)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(Path, "unlink", delayed_unlink)
    eviction = threading.Thread(target=run, args=(" second paper",))
    reopening = threading.Thread(target=run, args=("",))
    eviction.start()
    try:
        assert entered.wait(5)
        reopening.start()
        reopening.join(0.5)
    finally:
        release.set()
        eviction.join(5)
        if reopening.ident is not None:
            reopening.join(5)
    assert not errors
    assert not eviction.is_alive() and not reopening.is_alive()
    assert rc._doc_row("u", did) is not None
    assert rc._doc_file_path("u", did) is not None


def test_daily_retention_continues_after_error(monkeypatch):
    import asyncio
    import research_papers as papers

    waits = []
    runs = []

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            raise asyncio.CancelledError

    def cleanup():
        runs.append(True)
        if len(runs) == 1:
            raise OSError("temporary error")

    monkeypatch.setattr(papers.asyncio, "sleep", sleep)
    monkeypatch.setattr(papers.rc, "purge_expired_history_all", cleanup)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(papers.history_retention_loop())
    assert waits == [86400, 86400, 86400]
    assert len(runs) == 2
