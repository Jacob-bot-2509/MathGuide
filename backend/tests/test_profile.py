"""profile:学习画像聚合(诊断次数、掌握/薄弱统计、章节分布与最近记录)。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import diagnosis
import profile
import store

PHONE = "13800138000"
PASSWORD = "secret123"


@pytest.fixture()
def client(temp_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setattr(diagnosis, "DATA_DIR", tmp_path)
    monkeypatch.setattr(diagnosis, "PATH", tmp_path / "diagnoses.jsonl")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/profile", profile.learning_profile),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient) -> tuple[str, str]:
    res = c.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"], store.find_user_by_phone(PHONE)[0]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_profile_requires_auth(client):
    assert client.get("/api/profile").status_code == 401


def test_empty_profile(client):
    token, _ = _register(client)
    body = client.get("/api/profile", headers=_headers(token)).json()

    assert body["diagnosed"] == 0
    assert body["mastered"] == 0
    assert body["weak"] == 0
    assert body["averageScore"] is None
    assert body["chapters"] == []
    assert body["recent"] == []


def test_profile_counts_and_chapter_average(client):
    token, uid = _register(client)
    diagnosis.record(uid, "set-map", 4, "已掌握", source="self")
    diagnosis.record(uid, "derivative-def", 2, "概念不清", source="llm")
    diagnosis.record(uid, "chain-rule", 5, "很熟练", source="self")

    body = client.get("/api/profile", headers=_headers(token)).json()

    assert body["diagnosed"] == 3
    assert body["mastered"] == 2
    assert body["weak"] == 1
    assert body["averageScore"] == 3.7
    chapters = {item["chapter"]: item for item in body["chapters"]}
    assert chapters["函数与极限"]["averageScore"] == 4.0
    assert chapters["导数与微分"]["averageScore"] == 3.5
    assert chapters["导数与微分"]["diagnosed"] == 2


def test_latest_score_wins(client):
    token, uid = _register(client)
    diagnosis.record(uid, "set-map", 1, "第一次", source="llm")
    diagnosis.record(uid, "set-map", 5, "第二次", source="self")

    body = client.get("/api/profile", headers=_headers(token)).json()

    assert body["diagnosed"] == 1
    assert body["mastered"] == 1
    assert body["weak"] == 0
    assert body["averageScore"] == 5.0
    assert len(body["recent"]) == 2
    assert body["recent"][0]["score"] == 5  # 最近一次在前


def test_recent_is_limited(client):
    token, uid = _register(client)
    for index in range(12):
        diagnosis.record(uid, "set-map", (index % 5) + 1, f"第{index}次", source="self")

    body = client.get("/api/profile", headers=_headers(token)).json()

    assert len(body["recent"]) == 10
    assert "uid" not in body["recent"][0]
