"""确定性回归计算:只接受结构化表格与模型规格,不执行用户代码。"""
from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

import numpy as np
import statsmodels.api as sm


def _finite(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round(value) -> float | None:
    number = _finite(value)
    return None if number is None else round(number, 6)


def _number(text) -> float | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _column_values(columns: list[dict], rows: list[list[str]]) -> dict[str, list[float | None]]:
    keys = [str(col.get("key") or f"COL{i}").upper()
            for i, col in enumerate(columns)]
    values: dict[str, list[float | None]] = {key: [] for key in keys}
    for row in rows:
        for index, key in enumerate(keys):
            values[key].append(_number(row[index] if index < len(row) else ""))
    return values


def _validate_spec(columns: list[dict], spec: dict) -> tuple[str, list[str], int]:
    if not isinstance(spec, dict):
        raise ValueError("unsupported")
    model = str(spec.get("model") or "").strip().lower()
    if model not in {"ols", "poly"}:
        raise ValueError("unsupported")
    options = spec.get("options") or {}
    if isinstance(options, dict) and options.get("intercept") is False:
        raise ValueError("unsupported")
    keys = {str(col.get("key") or "").upper() for col in columns}
    x = [str(item).strip().upper() for item in (spec.get("x") or []) if str(item).strip()]
    y = str(spec.get("y") or "").strip().upper()
    if not x or not y:
        raise ValueError("bad_column")
    if len(set(x)) != len(x) or any(key not in keys for key in x + [y]):
        raise ValueError("bad_column")
    degree = 0
    if model == "poly":
        if len(x) != 1:
            raise ValueError("unsupported")
        try:
            degree = int(spec.get("degree") or 2)
        except (TypeError, ValueError) as exc:
            raise ValueError("unsupported") from exc
        if degree not in (2, 3, 4):
            raise ValueError("unsupported")
    return model, x, degree


def fit_regression(columns: list[dict], rows: list[list[str]],
                   formulas: dict[str, str], spec: dict) -> dict:
    """OLS / multiple linear / single-X polynomial;listwise deletion."""
    model, x_keys, degree = _validate_spec(columns, spec)
    y_key = str(spec.get("y") or "").strip().upper()
    values = _column_values(columns, rows)
    keys = [y_key] + x_keys
    if any(key not in values for key in keys):
        raise ValueError("bad_column")

    data: list[dict] = []
    for index in range(len(rows)):
        row_values = {key: values[key][index] for key in keys}
        if any(value is None for value in row_values.values()):
            continue
        data.append({"row": index, **row_values})
    missing = len(rows) - len(data)
    if not data:
        raise ValueError("empty")
    n = len(data)
    y = np.asarray([item[y_key] for item in data], dtype=float)
    x = np.asarray([[item[key] for key in x_keys] for item in data], dtype=float)

    if model == "poly":
        powers = [x[:, 0] ** power for power in range(1, degree + 1)]
        design = np.column_stack(powers)
        terms = [x_keys[0]] + [f"{x_keys[0]}^{power}"
                               for power in range(2, degree + 1)]
    else:
        design = x
        terms = list(x_keys)
    design = sm.add_constant(design, has_constant="add")
    p = design.shape[1]
    if n < p + 2:
        raise ValueError("insufficient_n")
    if np.linalg.matrix_rank(design) < p:
        raise ValueError("singular")

    fitted_model = sm.OLS(y, design).fit()
    params = np.asarray(fitted_model.params, dtype=float)
    bse = np.asarray(fitted_model.bse, dtype=float)
    tvalues = np.asarray(fitted_model.tvalues, dtype=float)
    pvalues = np.asarray(fitted_model.pvalues, dtype=float)
    conf = np.asarray(fitted_model.conf_int(), dtype=float)

    coefficients = []
    for index, term in enumerate(["const"] + terms):
        coefficients.append({
            "term": term,
            "estimate": _round(params[index]),
            "se": _round(bse[index]),
            "t": _round(tvalues[index]),
            "p": _round(pvalues[index]),
            "ciLow": _round(conf[index][0]),
            "ciHigh": _round(conf[index][1]),
        })

    fitted = np.asarray(fitted_model.fittedvalues, dtype=float)
    residuals = y - fitted
    points = []
    for index, item in enumerate(data):
        point = {
            "row": item["row"],
            "actual": _round(y[index]),
            "fitted": _round(fitted[index]),
            "residual": _round(residuals[index]),
        }
        if len(x_keys) == 1:
            point["x"] = _round(x[index][0])
        points.append(point)

    fit_curve = []
    if len(x_keys) == 1:
        low, high = float(np.min(x[:, 0])), float(np.max(x[:, 0]))
        if low == high:
            high = low + 1.0
        for step in range(200):
            value = low + (high - low) * step / 199
            prediction = params[0]
            for power in range(1, len(params)):
                prediction += params[power] * (value ** power)
            fit_curve.append({"x": _round(value), "y": _round(prediction)})

    equation_parts = [f"{_finite(params[0]) or 0:.4f}"]
    for index, term in enumerate(terms, start=1):
        value = _finite(params[index]) or 0.0
        sign = "+" if value >= 0 else "-"
        equation_parts.append(f"{sign} {abs(value):.4f} {term}")

    return {
        "model": model,
        "degree": degree,
        "n": n,
        "missing": missing,
        "equation": f"{y_key} = " + " ".join(equation_parts),
        "coefficients": coefficients,
        "r2": _round(getattr(fitted_model, "rsquared", None)),
        "adjR2": _round(getattr(fitted_model, "rsquared_adj", None)),
        "f": _round(getattr(fitted_model, "fvalue", None)),
        "pF": _round(getattr(fitted_model, "f_pvalue", None)),
        "points": points,
        "fitCurve": fit_curve,
        "warnings": [],
    }
