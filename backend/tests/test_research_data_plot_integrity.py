from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_diagrams as rd


def test_data_plot_downsamples_within_shape_budget():
    points = [{"x": i, "actual": 2 * i} for i in range(150)]
    result = rd.build_data_plot("t", "X", "Y", {
        "points": points, "fitCurve": [{"x": 0, "y": 0}, {"x": 149, "y": 298}],
    })
    assert result is not None
    shown = [s for s in result["shapes"] if s["kind"] == "point"]
    assert 0 < len(shown) <= 97
    assert "97/150" in result["title"]
    assert (shown[0]["x"], shown[-1]["x"]) == (0, 149)
    assert any(s["kind"] == "curve" for s in result["shapes"])


def test_unrenderable_x_is_not_replaced_with_row_number():
    assert rd.build_data_plot("t", "X", "Y", {
        "points": [{"x": 20000, "row": 0, "actual": 2}],
    }) is None


def test_invalid_curve_is_not_bridged():
    result = rd.build_data_plot("t", "X", "Y", {
        "points": [{"x": 0, "actual": 1}, {"x": 2, "actual": 3}],
        "fitCurve": [{"x": 0, "y": 1}, {"x": 1, "y": 20000}, {"x": 2, "y": 3}],
    })
    assert result is not None
    assert not any(s["kind"] == "curve" for s in result["shapes"])


def test_plan_recomputes_from_current_table_and_names_axes(monkeypatch):
    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "integrity-test"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "type": "number"}, {"key": "Y", "type": "number"}],
        "rows": [["5", "10"], ["6", "12"]], "formulas": {},
    })
    calls = []

    async def compute(payload, timeout=30):
        calls.append(payload)
        return {"points": [{"x": 5, "actual": 10}, {"x": 6, "actual": 12}]}

    monkeypatch.setattr(rd, "_run_analysis", compute)
    app = Starlette(routes=[Route("/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    response = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "plot", "tableId": "t", "mode": "research",
        "regression": {"x": ["X"], "y": "Y", "model": "ols", "tableUpdatedAt": 1},
    })
    assert response.status_code == 200
    assert calls[0]["rows"] == [["5", "10"], ["6", "12"]]
    diagram = response.json()["diagram"]
    assert diagram["title"].startswith("Y ~ X")
    assert any(s["kind"] == "point" and s["x"] == 5 and s["y"] == 10 for s in diagram["shapes"])


def test_multiple_x_uses_observation_index_without_mislabeling(monkeypatch):
    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "integrity-test"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "type": "number"}, {"key": "Z", "type": "number"},
                    {"key": "Y", "type": "number"}],
        "rows": [["1", "2", "3"]], "formulas": {},
    })

    async def compute(payload, timeout=30):
        return {"points": [{"row": 4, "actual": 3}, {"row": 7, "actual": 6}]}

    monkeypatch.setattr(rd, "_run_analysis", compute)
    app = Starlette(routes=[Route("/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    response = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "plot", "tableId": "t", "mode": "research",
        "regression": {"x": ["X", "Z"], "y": "Y", "model": "ols"},
    })
    assert response.status_code == 200
    diagram = response.json()["diagram"]
    assert "观测序号" in diagram["title"]
    assert any(s["kind"] == "point" and s["x"] == 4 and s["y"] == 3 for s in diagram["shapes"])


def test_plan_rejects_client_supplied_regression_points(monkeypatch):
    monkeypatch.setattr(rd, "require_auth", lambda request: {"uid": "integrity-test"})
    monkeypatch.setattr(rd, "_get_table", lambda uid, tid: {
        "columns": [{"key": "X", "type": "number"}, {"key": "Y", "type": "number"}],
        "rows": [["1", "2"]], "formulas": {},
    })
    app = Starlette(routes=[Route("/api/research/diagrams/plan", rd.plan_endpoint, methods=["POST"])])
    response = TestClient(app).post("/api/research/diagrams/plan", json={
        "question": "plot", "tableId": "t", "mode": "research",
        "regression": {"points": [{"x": 1, "actual": 999}]},
    })
    assert response.status_code == 400
