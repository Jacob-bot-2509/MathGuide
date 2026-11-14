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


# ---------- 以下为 v1.26.0 覆盖率补充:校验拒绝分支与数值清洗 ----------
# 背景:上面的用例只走了正常路径,校验拒绝分支(用户误配列/模型时真正会走到的代码)
# 此前全部未覆盖。这些分支一旦写错,用户看到的是 500 而不是可读的 ValueError 文案。

def test_finite_and_round_handle_unusable_input():
    from analysis_regression import _finite, _number, _round

    assert _finite("1.5") == 1.5
    assert _finite(None) is None
    assert _finite("abc") is None
    assert _finite(float("inf")) is None
    assert _finite(float("nan")) is None

    assert _round("1.23456789") == 1.234568
    assert _round(None) is None

    assert _number(" 1e3 ") == 1000.0
    assert _number("") is None
    assert _number(None) is None
    assert _number("abc") is None
    # Decimal 能表示 Infinity,业务上必须当非法值
    assert _number("Infinity") is None


def test_column_values_falls_back_to_positional_key_and_pads_short_row():
    from analysis_regression import _column_values

    values = _column_values([{"key": "X"}, {}], [["1"], ["2", "3"]])
    assert values["X"] == [1.0, 2.0]
    # 第二列没有 key → COL1;短行缺失位置按 None 处理
    assert values["COL1"] == [None, 3.0]


@pytest.mark.parametrize("spec", [
    "not-a-dict",                                                # 50: 规格不是 dict
    {"x": ["X"], "y": "Y"},                                      # 53: 模型非法(缺省)
    {"x": ["X"], "y": "Y", "model": "logit"},                     # 53: 模型非法(未知)
    {"x": [], "y": "Y", "model": "ols"},                           # 61: 没有自变量
    {"x": ["X"], "y": "", "model": "ols"},                         # 61: 没有因变量
    {"x": ["X", "X"], "y": "Y", "model": "ols"},                   # 63: 自变量重复
    {"x": ["NOPE"], "y": "Y", "model": "ols"},                     # 63: 列不存在
    {"x": ["X"], "y": "NOPE", "model": "ols"},                     # 63: 因变量不存在
    {"x": ["X", "Y"], "y": "Y", "model": "poly"},                  # 67: 多项式只能单 X
    {"x": ["X"], "y": "Y", "model": "poly", "degree": "abc"},       # 70-71: degree 转换失败
    {"x": ["X"], "y": "Y", "model": "poly", "degree": [2]},         # 70-71: degree 类型错
    {"x": ["X"], "y": "Y", "model": "poly", "degree": 1},           # 73: degree 越界
    {"x": ["X"], "y": "Y", "model": "poly", "degree": 5},           # 73: degree 越界
])
def test_validate_spec_rejections(spec):
    from analysis_regression import _validate_spec

    with pytest.raises(ValueError):
        _validate_spec(COLS, spec)


def test_all_rows_unusable_is_reported_as_empty():
    with pytest.raises(ValueError, match="empty"):
        fit_regression(COLS, [["", ""], ["x", "y"]], {}, {"x": ["X"], "y": "Y", "model": "ols"})


def test_degree_four_needs_at_least_seven_rows():
    # poly degree=4 → 设计矩阵 5 列,要求 n >= p + 2 = 7
    rows = [[str(i), str(i)] for i in range(1, 5)]
    with pytest.raises(ValueError, match="insufficient_n"):
        fit_regression(COLS, rows, {}, {
            "x": ["X"], "y": "Y", "model": "poly", "degree": 4})


def test_multiple_x_omits_curve_and_point_x():
    # Z 用平方项,避免与 X 完全共线(3*X 会触发 singular)
    rows = [[str(i), str(2 * i + 1), str(i * i)] for i in range(1, 9)]
    result = fit_regression(
        [{"key": "X"}, {"key": "Y"}, {"key": "Z"}], rows, {},
        {"x": ["X", "Z"], "y": "Y", "model": "ols"})

    assert [item["term"] for item in result["coefficients"]] == ["const", "X", "Z"]
    assert result["fitCurve"] == []
    assert all("x" not in point for point in result["points"])
