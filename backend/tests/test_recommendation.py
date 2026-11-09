"""recommendation:前置门控、复习/新学候选、双策略排序与接口。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import diagnosis
import recommendation
import store
from knowledge_graph import KnowledgeGraph, KnowledgePoint

PHONE = "13800138000"
PASSWORD = "secret123"


def _graph() -> KnowledgeGraph:
    """a → b → d/e,a → c → d;b 难但核心,c 易但边缘。"""
    points = {}
    for pid, difficulty, prereqs in [
        ("a", 1, ()),
        ("b", 5, ("a",)),
        ("c", 2, ("a",)),
        ("d", 4, ("b", "c")),
        ("e", 5, ("b",)),
    ]:
        points[pid] = KnowledgePoint(pid, f"点{pid}", "章", difficulty, prereqs)
    return KnowledgeGraph(points)


def test_only_roots_when_nothing_mastered():
    result = recommendation.recommend(_graph(), {}, strategy="difficulty", limit=5)
    assert [item["pointId"] for item in result["items"]] == ["a"]
    assert result["items"][0]["reason"] == "new"


def test_prerequisites_gate_candidates():
    result = recommendation.recommend(
        _graph(), {"a": 4}, strategy="difficulty", limit=5)
    ids = [item["pointId"] for item in result["items"]]
    assert ids == ["c", "b"]  # c 难度 2 在前,b 难度 5 在后
    assert "d" not in ids and "e" not in ids  # 前置 b 未达标


def test_review_candidate_is_marked_and_kept():
    result = recommendation.recommend(
        _graph(), {"a": 4, "b": 2}, strategy="difficulty", limit=5)
    by_id = {item["pointId"]: item for item in result["items"]}
    assert by_id["b"]["reason"] == "review"
    assert by_id["c"]["reason"] == "new"
    assert "d" not in by_id  # b 未达标,不能解锁 d


def test_mastered_points_are_excluded():
    result = recommendation.recommend(
        _graph(), {"a": 4, "b": 4}, strategy="difficulty", limit=5)
    ids = [item["pointId"] for item in result["items"]]
    assert ids == ["c", "e"]  # b 已掌握 → 解锁 e;d 仍被未掌握的 c 挡住


def test_coreness_strategy_prefers_unlocking_more():
    result = recommendation.recommend(
        _graph(), {"a": 4}, strategy="coreness", limit=5)
    assert [item["pointId"] for item in result["items"]] == ["b", "c"]
    assert result["items"][0]["descendantCount"] == 2


def test_limit_is_respected():
    result = recommendation.recommend(
        _graph(), {"a": 4}, strategy="difficulty", limit=1)
    assert len(result["items"]) == 1


def test_invalid_strategy_rejected():
    with pytest.raises(ValueError):
        recommendation.recommend(_graph(), {}, strategy="random", limit=5)


# ---------- 接口 ----------

@pytest.fixture()
def client(temp_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setattr(diagnosis, "DATA_DIR", tmp_path)
    monkeypatch.setattr(diagnosis, "PATH", tmp_path / "diagnoses.jsonl")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/recommendation", recommendation.recommend_points),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient) -> tuple[str, str]:
    res = c.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"], store.find_user_by_phone(PHONE)[0]


def test_recommendation_requires_auth(client):
    assert client.get("/api/recommendation").status_code == 401


def test_recommendation_uses_stored_mastery(client):
    token, uid = _register(client)
    diagnosis.record(uid, "set-map", 4, "已掌握", source="self")

    res = client.get("/api/recommendation",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [item["pointId"] for item in body["items"]]
    assert "set-map" not in ids
    assert "elementary-functions" in ids
    assert body["mastered"] == 1


def test_recommendation_rejects_bad_strategy(client):
    token, _ = _register(client)
    res = client.get("/api/recommendation?strategy=random",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 400


# ---------- 艾宾浩斯复习评判 ----------

from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _latest(score: int, days: int) -> dict:
    return {
        "score": score,
        "at": (NOW - timedelta(days=days)).isoformat(timespec="seconds"),
    }


def test_mastered_review_due_point_is_recommended():
    result = recommendation.recommend(
        _graph(), {"a": 5}, strategy="difficulty", limit=5,
        latest={"a": _latest(5, 90)}, now=NOW)

    by_id = {item["pointId"]: item for item in result["items"]}
    assert by_id["a"]["reason"] == "review"
    assert by_id["a"]["reviewDue"] is True
    assert by_id["a"]["retention"] < 0.6
    assert result["mastered"] == 1


def test_review_due_sorts_before_new():
    result = recommendation.recommend(
        _graph(), {"a": 5}, strategy="difficulty", limit=5,
        latest={"a": _latest(5, 90)}, now=NOW)

    assert result["items"][0]["pointId"] == "a"


def test_fresh_mastered_point_is_not_reviewed():
    result = recommendation.recommend(
        _graph(), {"a": 5}, strategy="difficulty", limit=5,
        latest={"a": _latest(5, 0)}, now=NOW)

    assert "a" not in [item["pointId"] for item in result["items"]]


def test_endpoint_returns_review_due(client, monkeypatch):
    token, uid = _register(client)
    old = {"set-map": {
        "score": 5,
        "at": (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds"),
    }}
    monkeypatch.setattr(diagnosis, "latest", lambda uid: old)

    res = client.get("/api/recommendation",
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    by_id = {item["pointId"]: item for item in res.json()["items"]}
    assert by_id["set-map"]["reviewDue"] is True
    assert by_id["set-map"]["reason"] == "review"
