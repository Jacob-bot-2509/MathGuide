"""graph_api:知识图谱数据接口(节点、边、章节与个人掌握度)。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import diagnosis
import graph_api
import store
from knowledge_graph import load_graph

PHONE = "13800138000"
PASSWORD = "secret123"


@pytest.fixture()
def client(temp_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setattr(diagnosis, "DATA_DIR", tmp_path)
    monkeypatch.setattr(diagnosis, "PATH", tmp_path / "diagnoses.jsonl")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/graph", graph_api.graph_data),
        Route("/api/graph/export", graph_api.graph_export),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient) -> tuple[str, str]:
    res = c.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"], store.find_user_by_phone(PHONE)[0]


def _get(c: TestClient, token: str, path: str = "/api/graph") -> dict:
    res = c.get(path, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    return res.json()


def test_graph_requires_auth(client):
    assert client.get("/api/graph").status_code == 401


def test_graph_returns_all_nodes_and_edges(client):
    token, _ = _register(client)
    body = _get(client, token)
    graph = load_graph()

    assert len(body["nodes"]) == len(graph.points)
    assert {node["id"] for node in body["nodes"]} == set(graph.points)
    assert len(body["edges"]) == sum(
        len(point.prerequisites) for point in graph.points.values())

    node = next(item for item in body["nodes"] if item["id"] == "chain-rule")
    assert node["name"] == graph.points["chain-rule"].name
    assert node["prerequisites"] == list(graph.points["chain-rule"].prerequisites)
    assert node["descendantCount"] == graph.descendant_count("chain-rule")
    assert node["status"] == "new"
    assert node["summary"] == graph.points["chain-rule"].summary
    assert node["summary"]
    assert node["keyPoints"] == list(graph.points["chain-rule"].key_points)
    assert body["chapters"][0] == "函数与极限"

    edge = next(item for item in body["edges"]
                if item["target"] == "chain-rule")
    assert edge["source"] in node["prerequisites"]


def test_graph_marks_personal_mastery(client):
    token, uid = _register(client)
    diagnosis.record(uid, "set-map", 4, "已掌握", source="self")
    diagnosis.record(uid, "derivative-def", 2, "概念混淆", source="llm")
    body = _get(client, token)
    by_id = {node["id"]: node for node in body["nodes"]}

    assert by_id["set-map"]["status"] == "mastered"
    assert by_id["derivative-def"]["status"] == "weak"
    assert by_id["chain-rule"]["status"] == "new"


def test_graph_export_is_standalone_html(client):
    token, _ = _register(client)
    res = client.get("/api/graph/export",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("text/html")
    html = res.text
    assert "vis-network" in html or "vis.Network" in html
    assert "set-map" in html and "chain-rule" in html
    assert len(html) > 100_000, "内联 vis 资源缺失,导出的 HTML 不是独立文件"


def test_graph_export_requires_auth(client):
    assert client.get("/api/graph/export").status_code == 401


def test_graph_contains_networkx_layout(client):
    token, _ = _register(client)
    body = _get(client, token)
    nodes = {node["id"]: node for node in body["nodes"]}
    for node in nodes.values():
        assert isinstance(node["x"], int)
        assert isinstance(node["y"], int)
        assert node["level"] >= 0
    for node in nodes.values():
        for prereq in node["prerequisites"]:
            assert nodes[prereq]["x"] < node["x"]


def test_graph_marks_review_due_with_ebbinghaus(client, monkeypatch):
    token, _ = _register(client)
    old = {"set-map": {
        "score": 5,
        "at": (datetime.now(timezone.utc) - timedelta(days=90))
        .isoformat(timespec="seconds"),
    }}
    monkeypatch.setattr(diagnosis, "latest", lambda uid: old)

    body = _get(client, token)
    node = next(item for item in body["nodes"] if item["id"] == "set-map")

    assert node["mastery"] == 5
    assert node["reviewDue"] is True
    assert node["retention"] < 0.6
