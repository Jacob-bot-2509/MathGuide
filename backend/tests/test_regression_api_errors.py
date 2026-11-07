import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import research_tables as rt


@pytest.mark.parametrize(("code", "status"), [
    ("insufficient_n", 400),
    ("singular", 400),
    ("unavailable", 503),
    ("internal_error", 503),
])
def test_regression_reports_input_and_worker_errors_separately(monkeypatch, code, status):
    monkeypatch.setattr(rt, "require_auth", lambda request: {"uid": "test"})
    monkeypatch.setattr(rt, "_get_table", lambda uid, tid: {"id": tid})

    async def fail(*args, **kwargs):
        raise rt.analysis_client.AnalysisError(code)

    monkeypatch.setattr(rt, "_run_analysis", fail)
    app = Starlette(routes=[Route(
        "/api/research/tables/{table_id}/regression", rt.regression_table, methods=["POST"])])
    body = {
        "columns": [{"key": "X", "type": "number"}, {"key": "Y", "type": "number"}],
        "rows": [["1", "2"], ["2", "3"], ["3", "4"]],
        "formulas": {},
        "regression": {"x": ["X"], "y": "Y", "model": "ols"},
    }
    response = TestClient(app).post("/api/research/tables/t1/regression", json=body)
    assert response.status_code == status
    assert response.text == code
