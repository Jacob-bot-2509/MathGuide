import pytest

pytest.importorskip("statsmodels")

from analysis_regression import fit_regression

COLS = [
    {"key": "X", "type": "number"},
    {"key": "Y", "type": "number"},
]

COLS_COLLINEAR = [
    {"key": "X1", "type": "number"},
    {"key": "X2", "type": "number"},
    {"key": "Y", "type": "number"},
]


def test_ols_matches_known_values():
    rows = [["1", "2"], ["2", "4"], ["3", "5"], ["4", "4"], ["5", "5"]]
    result = fit_regression(COLS, rows, {}, {"x": ["X"], "y": "Y", "model": "ols"})
    coef = {item["term"]: item for item in result["coefficients"]}
    assert coef["const"]["estimate"] == pytest.approx(2.2, abs=1e-6)
    assert coef["X"]["estimate"] == pytest.approx(0.6, abs=1e-6)
    assert coef["X"]["se"] == pytest.approx(0.2828427, abs=1e-6)
    assert result["r2"] == pytest.approx(0.6, abs=1e-6)
    assert result["n"] == 5
    assert len(result["points"]) == 5
    assert result["points"][0]["x"] == pytest.approx(1.0)


def test_listwise_deletion_reports_missing_rows():
    rows = [["1", "2"], ["", "4"], ["3", "5"], ["4", "4"], ["5", "5"]]
    result = fit_regression(COLS, rows, {}, {"x": ["X"], "y": "Y", "model": "ols"})
    assert result["n"] == 4
    assert result["missing"] == 1
    assert result["points"][0]["row"] == 0
    assert result["points"][1]["row"] == 2


def test_polynomial_degree_two_is_exact():
    rows = [["-2", "4"], ["-1", "1"], ["0", "0"], ["1", "1"], ["2", "4"]]
    result = fit_regression(COLS, rows, {}, {
        "x": ["X"], "y": "Y", "model": "poly", "degree": 2})
    terms = {item["term"]: item["estimate"] for item in result["coefficients"]}
    assert terms["const"] == pytest.approx(0, abs=1e-8)
    assert terms["X"] == pytest.approx(0, abs=1e-8)
    assert terms["X^2"] == pytest.approx(1, abs=1e-8)
    assert result["r2"] == pytest.approx(1, abs=1e-8)


def test_collinear_columns_return_singular():
    rows = [["1", "2", "3"], ["2", "4", "5"], ["3", "6", "6"],
            ["4", "8", "7"], ["5", "10", "8"]]
    with pytest.raises(ValueError, match="singular"):
        fit_regression(COLS_COLLINEAR, rows, {}, {
            "x": ["X1", "X2"], "y": "Y", "model": "ols"})


def test_missing_intercept_is_unsupported():
    with pytest.raises(ValueError, match="unsupported"):
        fit_regression(COLS, [["1", "2"], ["2", "3"], ["3", "4"]], {}, {
            "x": ["X"], "y": "Y", "model": "ols", "options": {"intercept": False}})


def test_worker_regression_op_returns_result():
    from analysis_worker import handle_request

    response = handle_request({
        "id": "r1", "op": "regression",
        "payload": {
            "columns": COLS,
            "rows": [["1", "2"], ["2", "4"], ["3", "5"], ["4", "4"], ["5", "5"]],
            "formulas": {},
            "spec": {"x": ["X"], "y": "Y", "model": "ols"},
        },
    })
    assert response["ok"] is True
    assert response["result"]["n"] == 5
    assert response["result"]["coefficients"][1]["term"] == "X"
