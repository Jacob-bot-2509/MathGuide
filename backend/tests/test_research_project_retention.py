"""Research projects must not disappear when more than 30 are created."""

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_corpus as rc


def test_project_creation_preserves_existing_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc, "require_auth", lambda request: {"uid": "retention-user"})
    app = Starlette(routes=[
        Route("/api/research/projects", rc.list_projects),
        Route("/api/research/projects", rc.create_project, methods=["POST"]),
    ])
    with TestClient(app) as client:
        created_ids = set()
        for i in range(31):
            response = client.post("/api/research/projects", json={"title": f"Project {i}"})
            assert response.status_code == 200
            created_ids.add(response.json()["project"]["id"])
        response = client.get("/api/research/projects")
        assert response.status_code == 200
        assert {project["id"] for project in response.json()["projects"]} == created_ids
