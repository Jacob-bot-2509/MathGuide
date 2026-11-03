"""高等代数可几何表示层:Phase 1 实子空间、线性变换、行列式、方程组、实特征方向。

模型只输出代数语义;本模块负责校验并确定性生成 DiagramSpec 的 shapes。
"""

from __future__ import annotations

import json
import math
import re
from typing import Iterable

from rag import llm

LINEAR_VISUALS = {"subspace", "linear_map", "determinant", "system", "eigen"}
TOL = 1e-9
DISPLAY = 1.6

_LINEAR_RE = re.compile(
    r"子空间|张成|span|线性空间|线性变换|线性映射|核空间|像空间|零空间|"
    r"特征值|特征向量|对角化|行列式|线性方程组|解空间|正交补|投影矩阵|"
    r"基向量|维数|R\s*\^\s*[23]|\\\\mathbb\{R\}\s*\^\s*[23]|"
    r"\bR[23]\b",
    re.IGNORECASE,
)


def looks_linear(question: str) -> bool:
    return bool(_LINEAR_RE.search(question or ""))


def _num(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or abs(parsed) > 1e4:
        return None
    return parsed


def _text(value: object, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _vec(value: object, size: int) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != size:
        return None
    parsed = [_num(item) for item in value]
    if any(item is None for item in parsed):
        return None
    return [float(item) for item in parsed]


def _integer(value: object, low: int, high: int) -> int | None:
    parsed = _num(value)
    if parsed is None or not parsed.is_integer() or not low <= parsed <= high:
        return None
    return int(parsed)


def _vectors(value: object, size: int, count: int | None = None) -> list[list[float]] | None:
    if not isinstance(value, list):
        return None
    out: list[list[float]] = []
    for item in value:
        vec = _vec(item, size)
        if vec is None:
            return None
        out.append(vec)
    if count is not None and len(out) != count:
        return None
    return out


def _matrix(value: object, size: int) -> list[list[float]] | None:
    if not isinstance(value, list) or len(value) != size:
        return None
    rows: list[list[float]] = []
    for item in value:
        row = _vec(item, size)
        if row is None:
            return None
        rows.append(row)
    return rows


def _norm(vec: Iterable[float]) -> float:
    return math.sqrt(sum(item * item for item in vec))


def _unit(vec: list[float]) -> list[float] | None:
    length = _norm(vec)
    if length < TOL:
        return None
    return [item / length for item in vec]


def _add(a: list[float], b: list[float], scale: float = 1.0) -> list[float]:
    return [x + y * scale for x, y in zip(a, b)]


def _scale(vec: list[float], scale: float) -> list[float]:
    return [item * scale for item in vec]


def _cross(a: list[float], b: list[float]) -> list[float]:
    if len(a) != 3 or len(b) != 3:
        return [0.0, 0.0, 0.0]
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _rref(matrix: list[list[float]]) -> tuple[list[list[float]], list[tuple[int, int]]]:
    rows = [row[:] for row in matrix]
    if not rows:
        return rows, []
    cols = len(rows[0])
    pivot_row = 0
    pivots: list[tuple[int, int]] = []
    for col in range(cols):
        best = max(range(pivot_row, len(rows)), key=lambda r: abs(rows[r][col]))
        if abs(rows[best][col]) < TOL:
            continue
        rows[pivot_row], rows[best] = rows[best], rows[pivot_row]
        pivot = rows[pivot_row][col]
        rows[pivot_row] = [value / pivot for value in rows[pivot_row]]
        for row_index, row in enumerate(rows):
            if row_index == pivot_row:
                continue
            factor = row[col]
            if abs(factor) < TOL:
                continue
            rows[row_index] = [
                value - factor * base
                for value, base in zip(row, rows[pivot_row])
            ]
        pivots.append((pivot_row, col))
        pivot_row += 1
        if pivot_row >= len(rows):
            break
    return rows, pivots


def _rank(matrix: list[list[float]]) -> int:
    if not matrix or not matrix[0]:
        return 0
    return len(_rref(matrix)[1])


def _nullspace(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix or not matrix[0]:
        return []
    reduced, pivots = _rref(matrix)
    pivot_cols = {col for _row, col in pivots}
    free_cols = [col for col in range(len(matrix[0])) if col not in pivot_cols]
    basis: list[list[float]] = []
    for free in free_cols:
        vector = [0.0] * len(matrix[0])
        vector[free] = 1.0
        for row, pivot_col in pivots:
            vector[pivot_col] = -reduced[row][free]
        basis.append(vector)
    return basis


def _independent(vectors: list[list[float]]) -> list[list[float]]:
    basis: list[list[float]] = []
    rank = 0
    for vector in vectors:
        candidate = basis + [vector]
        next_rank = _rank(candidate)
        if next_rank > rank:
            basis.append(vector)
            rank = next_rank
    return basis


def _det(matrix: list[list[float]]) -> float:
    size = len(matrix)
    if size == 1:
        return matrix[0][0]
    if size == 2:
        return matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
    if size == 3:
        a, b, c = matrix[0]
        d, e, f = matrix[1]
        g, h, i = matrix[2]
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return 0.0


def _matvec(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _eigen_symmetric(matrix: list[list[float]]) -> list[tuple[float, list[float]]]:
    """Jacobi 特征分解,只用于小尺寸实对称矩阵。"""
    size = len(matrix)
    a = [row[:] for row in matrix]
    vectors = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _ in range(64):
        p, q = 0, 1 if size > 1 else 0
        largest = 0.0
        for i in range(size):
            for j in range(i + 1, size):
                if abs(a[i][j]) > largest:
                    largest = abs(a[i][j])
                    p, q = i, j
        if largest < 1e-10:
            break
        theta = (a[q][q] - a[p][p]) / (2 * a[p][q])
        sign = 1.0 if theta >= 0 else -1.0
        t = sign / (abs(theta) + math.sqrt(theta * theta + 1))
        c = 1 / math.sqrt(t * t + 1)
        s = t * c
        for k in range(size):
            akp = a[k][p]
            akq = a[k][q]
            a[k][p] = c * akp - s * akq
            a[k][q] = s * akp + c * akq
        for k in range(size):
            apk = a[p][k]
            aqk = a[q][k]
            a[p][k] = c * apk - s * aqk
            a[q][k] = s * apk + c * aqk
        for k in range(size):
            vkp = vectors[k][p]
            vkq = vectors[k][q]
            vectors[k][p] = c * vkp - s * vkq
            vectors[k][q] = s * vkp + c * vkq
    pairs = [
        (a[index][index], [vectors[row][index] for row in range(size)])
        for index in range(size)
    ]
    pairs.sort(key=lambda item: item[0], reverse=True)
    return pairs


def _point(vec: list[float], label: str = "") -> dict:
    shape: dict = {"kind": "point", "x": vec[0], "y": vec[1]}
    if len(vec) > 2:
        shape["z"] = vec[2]
    if label:
        shape["label"] = label
    return shape


def _vector(start: list[float], end: list[float], label: str = "") -> dict:
    shape: dict = {"kind": "vector", "from": start[:], "to": end[:]}
    if label:
        shape["label"] = label
    return shape


def _segment(start: list[float], end: list[float], label: str = "") -> dict:
    shape: dict = {"kind": "segment", "from": start[:], "to": end[:]}
    if label:
        shape["label"] = label
    return shape


def _plane(center: list[float], normal: list[float], size: float,
           label: str = "") -> dict:
    shape: dict = {
        "kind": "plane",
        "x": center[0], "y": center[1], "z": center[2],
        "width": size, "height": size, "normal": normal[:],
    }
    if label:
        shape["label"] = label
    return shape


def _polygon(points: list[list[float]], label: str = "") -> dict:
    shape: dict = {"kind": "polygon", "points": [point[:] for point in points]}
    if label:
        shape["label"] = label
    return shape


def _annotation(point: list[float], text: str) -> dict:
    note: dict = {"x": point[0], "y": point[1], "text": text}
    if len(point) > 2:
        note["z"] = point[2]
    return note


def _subspace_basis(subspace: dict, ambient: int) -> tuple[int, str, list[float], list[list[float]]] | None:
    dimension = _integer(subspace.get("dimension"), 0, ambient)
    if dimension is None:
        return None
    kind = _text(subspace.get("kind"), 20).lower()
    if kind not in ("linear", "affine"):
        return None
    offset = _vec(subspace.get("offset", [0.0] * ambient), ambient)
    if offset is None:
        return None
    if kind == "linear" and any(abs(value) > TOL for value in offset):
        return None
    basis = _vectors(subspace.get("basis"), ambient)
    if basis is None or len(basis) != dimension:
        return None
    if any(_norm(vector) < TOL for vector in basis):
        return None
    if _rank(basis) != dimension:
        return None
    return dimension, kind, offset, basis


def sanitize_linear(raw: object) -> dict | None:
    """校验模型给出的线性代数语义计划;只接受 Phase 1 实数 2D/3D。"""
    if not isinstance(raw, dict):
        return None
    visual = _text(raw.get("visual"), 30).lower()
    if visual not in LINEAR_VISUALS:
        return None
    domain = _text(raw.get("domain", "real"), 20).lower()
    if domain != "real":
        return None
    ambient = _integer(raw.get("ambient"), 2, 3)
    if ambient is None:
        return None
    result: dict = {
        "visual": visual,
        "domain": "real",
        "ambient": ambient,
    }
    title = _text(raw.get("title"), 200)
    if title:
        result["title"] = title
    if visual == "subspace":
        subspace = raw.get("subspace")
        if not isinstance(subspace, dict):
            return None
        basis = _subspace_basis(subspace, ambient)
        if basis is None:
            return None
        dimension, kind, offset, vectors = basis
        result["subspace"] = {
            "dimension": dimension,
            "kind": kind,
            "offset": offset,
            "basis": vectors,
        }
        label = _text(subspace.get("label"), 80)
        if label:
            result["subspace"]["label"] = label
    elif visual in ("linear_map", "eigen"):
        matrix = _matrix(raw.get("matrix"), ambient)
        if matrix is None:
            return None
        result["matrix"] = matrix
    elif visual == "determinant":
        vectors = _vectors(raw.get("vectors"), ambient, ambient)
        if vectors is None or any(_norm(vector) < TOL for vector in vectors):
            return None
        result["vectors"] = vectors
    elif visual == "system":
        raw_equations = raw.get("equations")
        if not isinstance(raw_equations, list) or not raw_equations:
            return None
        equations: list[list[float]] = []
        for item in raw_equations[:ambient]:
            equation = _vec(item, ambient + 1)
            if equation is None:
                return None
            if any(abs(value) > TOL for value in equation[:ambient]):
                equations.append(equation)
        if not equations:
            return None
        result["equations"] = equations
    return result


def _build_subspace(linear: dict) -> tuple[str, list[dict], list[dict]]:
    ambient = linear["ambient"]
    subspace = linear["subspace"]
    dimension = subspace["dimension"]
    kind = subspace["kind"]
    offset = subspace["offset"]
    basis = subspace["basis"]
    shapes: list[dict] = []
    notes: list[dict] = []
    shapes.append(_point(offset, "p" if kind == "affine" else "O"))
    units = [_unit(vector) for vector in basis]
    units = [vector for vector in units if vector is not None]
    label_prefix = "p + span" if kind == "affine" else "span"
    if dimension == 0:
        notes.append(_annotation(_add(offset, [0.45] * ambient), "dim = 0"))
    elif dimension == 1:
        unit = units[0]
        shapes.append(_segment(_add(offset, unit, -DISPLAY),
                               _add(offset, unit, DISPLAY)))
        shapes.append(_vector(offset, _add(offset, unit, DISPLAY), "v1"))
        notes.append(_annotation(_add(offset, unit, DISPLAY * 0.75),
                                 f"{label_prefix}(v1), dim = 1"))
    elif dimension == 2:
        if ambient == 3:
            u, v = units[0], units[1]
            normal = _unit(_cross(u, v))
            if normal is None:
                return "geometry3d", shapes, notes
            center = _add(offset, _add(u, v), DISPLAY * 0.75)
            shapes.append(_plane(center, normal, DISPLAY * 2.0, "S"))
            shapes.append(_vector(offset, _add(offset, u, DISPLAY), "v1"))
            shapes.append(_vector(offset, _add(offset, v, DISPLAY), "v2"))
            notes.append(_annotation(center, f"dim = 2"))
        else:
            shapes.append(_vector(offset, _add(offset, units[0], DISPLAY), "v1"))
            shapes.append(_vector(offset, _add(offset, units[1], DISPLAY), "v2"))
            notes.append(_annotation(_add(offset, [0.8, 0.8]), "R²"))
    else:
        for index, unit in enumerate(units[:3]):
            shapes.append(_vector(offset, _add(offset, unit, DISPLAY), f"v{index + 1}"))
        notes.append(_annotation(_add(offset, [1.0, 1.0, 1.0]), "R³"))
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _subspace_through(origin: list[float], basis: list[list[float]],
                      label: str, ambient: int) -> list[dict]:
    units = [unit for unit in (_unit(vector) for vector in basis) if unit is not None]
    shapes: list[dict] = []
    if not units:
        return [_point(origin, label)]
    if len(units) == 1:
        shapes.append(_segment(_add(origin, units[0], -DISPLAY * 1.2),
                               _add(origin, units[0], DISPLAY * 1.2),
                               label))
        return shapes
    if len(units) >= 2 and ambient == 3:
        normal = _unit(_cross(units[0], units[1]))
        if normal:
            center = _add(origin, _add(units[0], units[1]), DISPLAY * 0.8)
            shapes.append(_plane(center, normal, DISPLAY * 2.0, label))
            return shapes
    if len(units) >= 3:
        return [_point(origin, label)]
    shapes.append(_point(origin, label))
    return shapes


def _build_linear_map(linear: dict) -> tuple[str, list[dict], list[dict]]:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    for index in range(ambient):
        basis = [0.0] * ambient
        basis[index] = 1.0
        image = _matvec(matrix, basis)
        if _norm(image) > TOL:
            unit = _unit(image)
            shapes.append(_vector(origin, _add(origin, unit, DISPLAY),
                                  f"T(e{index + 1})"))
    kernel = _nullspace(matrix)
    image_basis = _independent([
        [matrix[row][col] for row in range(ambient)]
        for col in range(ambient)
    ])
    shapes.extend(_subspace_through(origin, kernel, "ker T", ambient))
    shapes.extend(_subspace_through(origin, image_basis, "Im T", ambient))
    notes.append(_annotation(_add(origin, [0.8] * ambient),
                             f"rank = {len(image_basis)}, nullity = {len(kernel)}"))
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _build_determinant(linear: dict) -> tuple[str, list[dict], list[dict]]:
    ambient = linear["ambient"]
    vectors = linear["vectors"]
    max_length = max(_norm(vector) for vector in vectors)
    factor = min(1.0, 3.0 / max_length) if max_length > TOL else 1.0
    display = [_scale(vector, factor) for vector in vectors]
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    for index, vector in enumerate(display):
        shapes.append(_vector(origin, vector, f"v{index + 1}"))
    if ambient == 2:
        u, v = display
        shapes.append(_polygon([origin, u, _add(u, v), v], "det"))
        value = _det([vectors[0], vectors[1]])
        notes.append(_annotation(_add(_add(u, v), [0.3, 0.3]),
                                 f"det = {value:.3g}"))
    else:
        u, v, w = display
        corners = [
            [0.0, 0.0, 0.0], u, v, w,
            _add(u, v), _add(u, w), _add(v, w), _add(_add(u, v), w),
        ]
        edges = [
            (0, 1), (0, 2), (0, 4), (1, 3), (1, 5),
            (2, 3), (2, 6), (4, 5), (4, 6), (3, 7), (5, 7), (6, 7),
        ]
        for start, end in edges:
            shapes.append(_segment(corners[start], corners[end]))
        value = _det([vectors[0], vectors[1], vectors[2]])
        notes.append(_annotation(_add(_add(u, v), w, 0.6),
                                 f"det = {value:.3g}"))
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _build_eigen(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    if any(abs(matrix[i][j] - matrix[j][i]) > 1e-7
           for i in range(ambient) for j in range(ambient)):
        return None
    pairs = _eigen_symmetric(matrix)
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    for index, (value, vector) in enumerate(pairs):
        unit = _unit(vector)
        if unit is None:
            continue
        shapes.append(_vector(origin, _add(origin, unit, DISPLAY), f"λ{index + 1}"))
        notes.append(_annotation(_add(origin, unit, DISPLAY * 0.75),
                                 f"λ = {value:.3g}"))
    if len(notes) == 0:
        return None
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _line_points(equation: list[float], radius: float) -> tuple[list[float], list[float]] | None:
    a, b, c = equation
    if abs(b) > TOL:
        first = [-radius, (c - a * -radius) / b]
        second = [radius, (c - a * radius) / b]
        return first, second
    if abs(a) > TOL:
        x = c / a
        return [x, -radius], [x, radius]
    return None


def _build_system(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    equations = linear["equations"]
    shapes: list[dict] = []
    notes: list[dict] = []
    if ambient == 2:
        radius = max(3.0, max(
            abs(eq[2]) / max(math.hypot(eq[0], eq[1]), TOL)
            for eq in equations
        ) + 2.0)
        for equation in equations:
            points = _line_points(equation, radius)
            if points:
                shapes.append(_segment(points[0], points[1]))
        if len(equations) >= 2:
            a1, b1, c1 = equations[0]
            a2, b2, c2 = equations[1]
            det = a1 * b2 - a2 * b1
            if abs(det) > TOL:
                x = (c1 * b2 - c2 * b1) / det
                y = (a1 * c2 - a2 * c1) / det
                shapes.append(_point([x, y], "解"))
                notes.append(_annotation([x + 0.4, y + 0.4], f"({x:.3g}, {y:.3g})"))
            else:
                notes.append(_annotation([0.6, 0.6], "无唯一解或两线重合"))
        type_name = "plot2d"
    else:
        planes = []
        for equation in equations:
            a, b, c, d = equation
            normal = [a, b, c]
            unit = _unit(normal)
            if unit is None:
                continue
            distance = d / _norm(normal)
            center = _scale(unit, distance)
            shapes.append(_plane(center, unit, 4.0))
            planes.append((normal, d))
        if len(planes) >= 2:
            direction = _cross(planes[0][0], planes[1][0])
            if _norm(direction) > TOL:
                unit = _unit(direction)
                free = max(range(3), key=lambda index: abs(unit[index]))
                axes = [index for index in range(3) if index != free]
                rows = [
                    [planes[0][0][index] for index in axes],
                    [planes[1][0][index] for index in axes],
                ]
                rhs = [planes[0][1], planes[1][1]]
                det = _det(rows)
                if abs(det) > TOL:
                    values = [
                        (rhs[0] * rows[1][1] - rhs[1] * rows[0][1]) / det,
                        (rows[0][0] * rhs[1] - rows[1][0] * rhs[0]) / det,
                    ]
                    point = [0.0, 0.0, 0.0]
                    point[free] = 0.0
                    point[axes[0]] = values[0]
                    point[axes[1]] = values[1]
                    shapes.append(_segment(
                        _add(point, unit, -3.0), _add(point, unit, 3.0),
                        "交线"))
                    notes.append(_annotation(_add(point, [0.4, 0.4, 0.4]),
                                             "解集为直线"))
            else:
                notes.append(_annotation([0.5, 0.5, 0.5], "两平面平行或重合"))
        type_name = "geometry3d"
    return type_name, shapes, notes


def build_linear_diagram(raw: object) -> dict | None:
    """把含 linear 语义块的原始图解转成确定性 DiagramSpec。"""
    if not isinstance(raw, dict):
        return None
    linear = sanitize_linear(raw.get("linear"))
    if linear is None:
        return None
    visual = linear["visual"]
    if visual == "subspace":
        built = _build_subspace(linear)
    elif visual == "linear_map":
        built = _build_linear_map(linear)
    elif visual == "determinant":
        built = _build_determinant(linear)
    elif visual == "eigen":
        built = _build_eigen(linear)
    else:
        built = _build_system(linear)
    if built is None:
        return None
    type_name, shapes, notes = built
    if not shapes:
        return None
    title = _text(raw.get("title") or linear.get("title"), 200)
    if not title:
        title = {
            "subspace": "子空间",
            "linear_map": "线性变换的核与像",
            "determinant": "行列式的几何意义",
            "system": "线性方程组的解集",
            "eigen": "实特征方向",
        }.get(visual, "高等代数图解")
    if visual == "subspace":
        subspace = linear["subspace"]
        title = f"R^{linear['ambient']} 中 {subspace['dimension']} 维子空间"
    return {
        "schemaVersion": 1,
        "type": type_name,
        "title": title,
        "nodes": [],
        "edges": [],
        "shapes": shapes,
        "annotations": notes,
        "linear": linear,
    }


def _load_json(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


_LINEAR_SYSTEM = """你是高等代数图解规划器。只输出一个 JSON 对象,不要 Markdown、不要解释。
模型只给代数语义,不要给 shapes/points/坐标网格。
schema:
{
  "visual": "subspace|linear_map|determinant|system|eigen",
  "domain": "real",
  "ambient": 2 或 3,
  "title": "中文标题",
  "subspace": {"dimension": 0-3, "kind": "linear|affine",
               "offset": [x,y] 或 [x,y,z], "basis": [[...]], "label": "短标签"},
  "matrix": [[...]],
  "vectors": [[...]],
  "equations": [[a,b,c] 或 [a,b,c,d]]
}
规则:
1. R^2/R² 用 ambient 2;R^3/R³/空间子空间用 ambient 3。
2. 线性子空间 offset 必须为零;仿射子空间 offset 非零。
3. basis 数量必须等于 dimension,且线性无关。
4. determinant 的 vectors 数量等于 ambient。
5. eigen 只给实对称矩阵。
6. system 每条方程:2D 为 [a,b,c] 表示 ax+by=c;3D 为 [a,b,c,d] 表示 ax+by+cz=d。
7. 不要输出 abstract 的商空间/张量/PID 模;这些不在本期内。
8. 不要解释选型或权重。
示例: R^3 中由 e1,e2 张成的平面
{"visual":"subspace","domain":"real","ambient":3,"title":"R^3 中的坐标平面",
 "subspace":{"dimension":2,"kind":"linear","offset":[0,0,0],
 "basis":[[1,0,0],[0,1,0]],"label":"span(e1,e2)"}}
"""


async def plan_linear(question: str, before: str, role: str = "main") -> dict | None:
    """让模型输出高等代数语义计划;失败返回 None。"""
    if not llm.is_configured(role):
        return None
    latest = re.sub(r"\s+", " ", before or "").strip()[-1600:]
    context = (
        f"用户问题:{_text(question, 900)}\n"
        f"当前讲解:{_text(latest, 1200)}"
    )
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(
                _LINEAR_SYSTEM, context, role=role, fallback=True,
                max_tokens=900, thinking=False):
            parts.append(delta)
            if sum(len(part) for part in parts) >= 5000:
                break
    except Exception:  # noqa: BLE001
        return None
    raw = _load_json("".join(parts))
    if raw is None:
        return None
    if not raw.get("type"):
        raw["type"] = "geometry3d" if raw.get("ambient") == 3 else "geometry2d"
    return build_linear_diagram({"type": raw.get("type"),
                                  "title": raw.get("title"),
                                  "linear": raw})
