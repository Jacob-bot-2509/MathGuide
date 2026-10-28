"""diagnosis:LLM 评分解析、按用户持久化、弱项报告与接口鉴权。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import diagnosis
import store
from knowledge_graph import load_graph

PHONE = "13800138000"
PASSWORD = "secret123"


@pytest.fixture()
def data_path(tmp_path, monkeypatch):
    monkeypatch.setattr(diagnosis, "DATA_DIR", tmp_path)
    monkeypatch.setattr(diagnosis, "PATH", tmp_path / "diagnoses.jsonl")
    return tmp_path / "diagnoses.jsonl"


@pytest.fixture()
def client(temp_store, temp_usage, data_path, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/account/export", auth.export_account, methods=["POST"]),
        Route("/api/account/delete", auth.delete_account, methods=["POST"]),
        Route("/api/diagnosis", diagnosis.diagnose, methods=["POST"]),
        Route("/api/diagnosis/report", diagnosis.weak_points),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient) -> str:
    res = c.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------- 模型输出解析 ----------

def test_parse_result_accepts_plain_json():
    score, comment = diagnosis.parse_result('{"score": 4, "comment": "掌握较好"}')
    assert score == 4
    assert comment == "掌握较好"


def test_parse_result_accepts_fenced_json():
    text = '结论如下:\n```json\n{"score": 2, "comment": "定义混淆"}\n```\n'
    assert diagnosis.parse_result(text) == (2, "定义混淆")


def test_parse_result_clamps_score_to_1_5():
    assert diagnosis.parse_result('{"score": 9, "comment": "x"}')[0] == 5
    assert diagnosis.parse_result('{"score": 0, "comment": "x"}')[0] == 1


def test_parse_result_rejects_non_json():
    with pytest.raises(diagnosis.DiagnosisError):
        diagnosis.parse_result("我觉得还行")


def test_parse_result_rejects_non_finite_score():
    with pytest.raises(diagnosis.DiagnosisError):
        diagnosis.parse_result('{"score": Infinity, "comment": "x"}')


# ---------- 持久化 ----------

def test_record_and_latest_by_point(data_path):
    diagnosis.record("u1", "set-map", 2, "第一次", source="llm")
    diagnosis.record("u1", "set-map", 4, "第二次", source="self")
    diagnosis.record("u1", "derivative-def", 1, "薄弱", source="llm")

    latest = diagnosis.latest("u1")
    assert latest["set-map"]["score"] == 4
    assert latest["derivative-def"]["score"] == 1
    assert len(diagnosis.for_user("u1")) == 3
    assert data_path.exists()


def test_weak_report_filters_and_sorts(data_path):
    graph = load_graph()
    diagnosis.record("u1", "set-map", 2, "基础不牢", source="self")
    diagnosis.record("u1", "derivative-def", 1, "概念不清", source="llm")
    diagnosis.record("u1", "chain-rule", 4, "已掌握", source="self")

    report = diagnosis.weak_report("u1", graph)

    assert [item["pointId"] for item in report["weak"]] == [
        "derivative-def", "set-map",
    ]
    assert report["weak"][0]["name"] == graph.points["derivative-def"].name
    assert report["weak"][0]["descendantCount"] == graph.descendant_count("derivative-def")
    assert report["diagnosed"] == 3


def test_delete_user_removes_only_target(data_path):
    diagnosis.record("u1", "set-map", 2, "x", source="self")
    diagnosis.record("u2", "set-map", 3, "y", source="self")

    assert diagnosis.delete_user("u1") == 1
    assert diagnosis.for_user("u1") == []
    assert len(diagnosis.for_user("u2")) == 1


# ---------- 接口 ----------

def test_diagnosis_requires_auth(client):
    res = client.post("/api/diagnosis",
                      json={"pointId": "derivative-def", "selfRating": 2})
    assert res.status_code == 401


def test_self_rating_persists_and_appears_in_report(client):
    token = _register(client)
    res = client.post("/api/diagnosis",
                      json={"pointId": "derivative-def", "selfRating": 2},
                      headers=_headers(token))
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["score"] == 2
    assert body["source"] == "self"

    report = client.get("/api/diagnosis/report", headers=_headers(token)).json()
    assert report["diagnosed"] == 1
    assert report["weak"][0]["pointId"] == "derivative-def"


def test_answer_path_uses_llm_score(client, monkeypatch):
    token = _register(client)

    async def fake_score(point, answer):
        assert answer == "洛必达法则要求分子分母同时趋于零"
        return 4, "步骤正确,但未验证条件"

    monkeypatch.setattr(diagnosis, "_llm_score", fake_score)
    res = client.post(
        "/api/diagnosis",
        json={"pointId": "lhopital",
              "answer": "洛必达法则要求分子分母同时趋于零"},
        headers=_headers(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["score"] == 4
    assert res.json()["source"] == "llm"


def test_unknown_point_returns_404(client):
    token = _register(client)
    res = client.post("/api/diagnosis",
                      json={"pointId": "ghost", "selfRating": 2},
                      headers=_headers(token))
    assert res.status_code == 404


def test_missing_rating_and_answer_returns_400(client):
    token = _register(client)
    res = client.post("/api/diagnosis",
                      json={"pointId": "derivative-def"},
                      headers=_headers(token))
    assert res.status_code == 400


def test_llm_failure_returns_503(client, monkeypatch):
    token = _register(client)

    async def boom(point, answer):
        raise diagnosis.DiagnosisUnavailable("模型不可用")

    monkeypatch.setattr(diagnosis, "_llm_score", boom)
    res = client.post("/api/diagnosis",
                      json={"pointId": "derivative-def", "answer": "..."},
                      headers=_headers(token))
    assert res.status_code == 503


def test_account_export_and_delete_include_diagnoses(client):
    token = _register(client)
    client.post("/api/diagnosis",
                json={"pointId": "derivative-def", "selfRating": 2},
                headers=_headers(token))
    uid, _ = store.find_user_by_phone(PHONE)

    exported = client.post("/api/account/export", headers=_headers(token)).json()
    assert len(exported["diagnoses"]) == 1
    assert exported["diagnoses"][0]["pointId"] == "derivative-def"

    res = client.post("/api/account/delete", json={"password": PASSWORD},
                      headers=_headers(token))
    assert res.status_code == 200, res.text
    assert diagnosis.for_user(uid) == []
