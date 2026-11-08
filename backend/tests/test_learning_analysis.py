"""learning_analysis:掌握度快照、数据质量、瓶颈、下一步与分析文案。"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import learning_analysis
import store
from knowledge_graph import KnowledgeGraph, KnowledgePoint

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
PHONE = "13800138000"
PASSWORD = "secret123"


def _graph() -> KnowledgeGraph:
    """a → b → d/e,a → c → d;两个章节,便于检查章节均衡。"""
    points = {}
    for pid, difficulty, chapter, prereqs in [
        ("a", 1, "第一章", ()),
        ("b", 5, "第一章", ("a",)),
        ("c", 2, "第二章", ("a",)),
        ("d", 4, "第二章", ("b", "c")),
        ("e", 5, "第二章", ("b",)),
    ]:
        points[pid] = KnowledgePoint(pid, f"点{pid}", chapter, difficulty, prereqs)
    return KnowledgeGraph(points)


def _entry(score: int, *, days_ago: int = 0) -> dict:
    at = (NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {"pointId": "x", "score": score, "at": at, "comment": "", "source": "self"}


def _wide_graph(total: int = 10) -> KnowledgeGraph:
    points = {
        f"p{index}": KnowledgePoint(f"p{index}", f"点{index}", "章", 1, ())
        for index in range(total)
    }
    return KnowledgeGraph(points)


def test_empty_snapshot_reports_no_data():
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={}, now=NOW)

    assert snapshot["dataQuality"] == "none"
    assert snapshot["limits"]["reviewRetention"] == 0.6
    assert snapshot["coverage"] == {
        "total": 5,
        "diagnosed": 0,
        "ratio": 0.0,
        "frontierTotal": 1,
        "frontierDiagnosed": 0,
        "frontierRatio": 0.0,
    }
    assert snapshot["structure"] == {
        "mastered": 0, "weak": 0, "stale": 0, "undiagnosed": 5,
    }
    assert [item["pointId"] for item in snapshot["suggestedDiagnosis"]] == ["a"]
    assert len(snapshot["chapters"]) == 2


def test_snapshot_counts_frontier_bottlenecks_and_next_steps():
    latest = {"a": _entry(4), "b": _entry(2)}
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map=latest, now=NOW)

    assert snapshot["dataQuality"] == "sparse"
    assert snapshot["coverage"]["diagnosed"] == 2
    assert snapshot["coverage"]["ratio"] == 0.4
    assert snapshot["coverage"]["frontierTotal"] == 2
    assert snapshot["coverage"]["frontierDiagnosed"] == 1
    assert snapshot["coverage"]["frontierRatio"] == 0.5

    structure = snapshot["structure"]
    assert structure["mastered"] == 1
    assert structure["weak"] == 1
    assert structure["undiagnosed"] == 3

    assert [item["pointId"] for item in snapshot["bottlenecks"]] == ["b"]
    assert snapshot["bottlenecks"][0]["descendantCount"] == 2

    next_ids = [item["pointId"] for item in snapshot["nextSteps"]]
    assert next_ids[:2] == ["b", "c"]
    assert snapshot["nextSteps"][0]["reason"] == "review"
    assert snapshot["nextSteps"][1]["reason"] == "new"
    assert snapshot["nextSteps"][0]["why"]

    # b 需要复习,c 尚未诊断;其余点被前置挡住,不应进入摸底建议
    assert [item["pointId"] for item in snapshot["suggestedDiagnosis"]] == ["c"]

    chapters = {item["chapter"]: item for item in snapshot["chapters"]}
    assert chapters["第一章"]["diagnosed"] == 2
    assert chapters["第一章"]["mastered"] == 1
    assert chapters["第一章"]["weak"] == 1
    assert chapters["第一章"]["averageScore"] == 3.0
    assert chapters["第二章"]["diagnosed"] == 0
    assert chapters["第二章"]["coverageRatio"] == 0.0


def test_review_due_uses_ebbinghaus_retention():
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={"a": _entry(3, days_ago=40)}, now=NOW)

    # 原始诊断分仍决定已掌握/薄弱;待复核只是叠加标记
    assert snapshot["structure"]["stale"] == 1
    assert snapshot["structure"]["mastered"] == 1
    assert snapshot["structure"]["weak"] == 0

    stale = snapshot["stale"][0]
    assert stale["pointId"] == "a"
    assert stale["score"] == 3
    assert stale["effectiveScore"] == pytest.approx(1 + 2 * math.exp(-40 / 60), abs=0.01)
    assert stale["days"] >= 40
    assert stale["retention"] == pytest.approx(math.exp(-40 / 60), abs=0.001)
    assert stale["tauDays"] == 60
    assert stale["retention"] < snapshot["limits"]["reviewRetention"]

    assert [item["pointId"] for item in snapshot["bottlenecks"]] == ["a"]
    assert snapshot["bottlenecks"][0]["reason"] == "stale"
    assert snapshot["nextSteps"][0]["pointId"] == "a"
    assert snapshot["nextSteps"][0]["reason"] == "review"


def test_forgetting_does_not_block_prerequisites():
    """遗忘只影响复习优先级,不能让已掌握的前置在门槛上失效。"""
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={"a": _entry(5, days_ago=90)}, now=NOW)

    assert snapshot["structure"]["mastered"] == 1
    assert snapshot["structure"]["stale"] == 1
    # a 早已待复核,但 b/c 仍应被视为可学前沿
    assert snapshot["coverage"]["frontierTotal"] == 2
    assert [item["pointId"] for item in snapshot["suggestedDiagnosis"]] == ["b", "c"]


def test_retention_curve_is_monotonic_and_score_aware():
    graph = _wide_graph(1)

    def stale_retention(score: int, days: int) -> float:
        snapshot = learning_analysis.build_snapshot(
            "u", graph=graph,
            latest_map={"p0": _entry(score, days_ago=days)}, now=NOW)
        assert snapshot["stale"], "该年龄应已进入待复核"
        return snapshot["stale"][0]["retention"]

    r3_60 = stale_retention(3, 60)
    r5_60 = stale_retention(5, 60)
    assert r3_60 == pytest.approx(math.exp(-60 / 60), abs=0.001)
    assert r5_60 == pytest.approx(math.exp(-60 / 90), abs=0.001)
    assert r5_60 > r3_60  # 掌握度越高,遗忘越慢
    assert stale_retention(5, 90) < r5_60  # 同分随时间单调下降

    fresh = learning_analysis.build_snapshot(
        "u", graph=graph, latest_map={"p0": _entry(5)}, now=NOW)
    assert fresh["stale"] == []


def test_data_quality_thresholds():
    graph = _wide_graph(10)
    eight = {f"p{index}": _entry(4) for index in range(8)}

    none = learning_analysis.build_snapshot("u", graph=graph, latest_map={}, now=NOW)
    sparse = learning_analysis.build_snapshot(
        "u", graph=graph, latest_map={"p0": _entry(4)}, now=NOW)
    ok = learning_analysis.build_snapshot("u", graph=graph, latest_map=eight, now=NOW)

    assert none["dataQuality"] == "none"
    assert sparse["dataQuality"] == "sparse"
    assert ok["dataQuality"] == "ok"


def test_system_prompt_carries_computed_facts_and_no_fabrication_rule():
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={"a": _entry(4), "b": _entry(2)}, now=NOW)

    zh = learning_analysis.system_prompt(snapshot, zh=True)
    assert "覆盖度" in zh
    assert "章节均衡" in zh
    assert "前置瓶颈" in zh
    assert "待复核" in zh
    assert "下一步" in zh
    assert "艾宾浩斯" in zh
    assert "不得编造" in zh
    assert snapshot["coverage"]["diagnosed"] == 2
    assert '"diagnosed": 2' in zh

    en = learning_analysis.system_prompt(snapshot, zh=False)
    assert "Coverage" in en
    assert "Ebbinghaus" in en
    assert "Do not invent" in en


def test_fallback_report_is_deterministic_and_mentions_next_steps():
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={"a": _entry(4), "b": _entry(2)}, now=NOW)

    text = learning_analysis.fallback_report(snapshot, zh=True)

    assert "覆盖度" in text
    assert "前置瓶颈" in text
    assert "下一步" in text
    assert "点b" in text
    assert "2/5" in text


def test_footer_links_point_to_graph_nodes():
    snapshot = learning_analysis.build_snapshot(
        "u1", graph=_graph(), latest_map={"a": _entry(4), "b": _entry(2)}, now=NOW)

    footer = learning_analysis.footer_links(snapshot, zh=True)
    assert "[点b](cmd://point/b)" in footer
    assert "[点c](cmd://point/c)" in footer

    en = learning_analysis.footer_links(snapshot, zh=False)
    assert "Open in graph" in en


# ---------- 接口 ----------

@pytest.fixture()
def client(temp_store, tmp_path, monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    app = Starlette(routes=[
        Route("/api/auth/register", auth.register, methods=["POST"]),
        Route("/api/profile/analysis", learning_analysis.analysis_endpoint),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _register(c: TestClient) -> tuple[str, str]:
    res = c.post("/api/auth/register", json={"phone": PHONE, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()["token"], store.find_user_by_phone(PHONE)[0]


def test_analysis_requires_auth(client):
    assert client.get("/api/profile/analysis").status_code == 401


def test_analysis_endpoint_returns_empty_snapshot_for_new_account(client):
    token, _ = _register(client)
    res = client.get(
        "/api/profile/analysis", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dataQuality"] == "none"
    assert body["coverage"]["total"] == 80
    assert body["coverage"]["diagnosed"] == 0
    assert body["suggestedDiagnosis"]
    assert "generatedAt" in body
