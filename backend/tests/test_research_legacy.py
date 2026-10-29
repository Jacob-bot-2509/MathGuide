import pytest

import research_corpus as corpus
import research_legacy as legacy


@pytest.fixture
def archive():
    return {
        "projects": [{"id": 10, "title": "old", "goal": "goal", "approach": "idea", "notes": "notes", "status": "active"}],
        "files": [
            {"id": 20, "projectId": 10, "name": "paper.pdf", "size": 1234, "text": "legacy extracted text"},
            {"id": 21, "projectId": None, "name": "image.png", "size": 55, "kind": "image"},
        ],
        "activeId": 10,
    }


def test_import_is_retry_safe_and_isolated(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(corpus, "DATA_DIR", tmp_path / "research")
    assert legacy._import_archive("user-a", archive)["duplicate"] is False
    assert legacy._import_archive("user-a", archive)["duplicate"] is True
    assert legacy._import_archive("user-b", archive)["duplicate"] is False
    projects = corpus._load_projects("user-a")
    docs, nodes, chunks = corpus._load_rows("user-a")
    assert len(projects) == 1 and projects[0]["notes"] == "notes"
    assert len(docs) == 2 and {d["name"] for d in docs} == {"paper.pdf", "image.png"}
    assert next(d for d in docs if d["name"] == "paper.pdf")["projectId"] == projects[0]["id"]
    assert any("legacy extracted text" in c.text for c in chunks)
    assert len(corpus._load_projects("user-b")) == 1


def test_invalid_archive_is_not_partially_imported(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(corpus, "DATA_DIR", tmp_path / "research")
    archive["files"][1]["size"] = -1
    with pytest.raises(ValueError):
        legacy._import_archive("user-a", archive)
    assert corpus._load_projects("user-a") == []


def test_failure_mid_transaction_rolls_back(tmp_path, monkeypatch, archive):
    monkeypatch.setattr(corpus, "DATA_DIR", tmp_path / "research")
    archive["files"][1]["projectId"] = []
    with pytest.raises(TypeError):
        legacy._import_archive("user-a", archive)
    assert corpus._load_projects("user-a") == []
    assert corpus._load_rows("user-a")[0] == []


def test_import_endpoint_requires_auth_and_returns_counts(tmp_path, monkeypatch, archive):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(corpus, "DATA_DIR", tmp_path / "research")
    client = TestClient(Starlette(routes=[Route("/import", legacy.import_archive, methods=["POST"])]))
    assert client.post("/import", json=archive).status_code == 401
    monkeypatch.setattr(legacy, "require_auth", lambda request: {"uid": "user-a"})
    response = client.post("/import", json=archive)
    assert response.status_code == 200
    assert response.json() == {"duplicate": False, "projects": 1, "files": 2}
    assert client.post("/import", json=archive).json()["duplicate"] is True

