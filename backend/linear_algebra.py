"""高等代数可几何表示层:Phase 1 实子空间、线性变换、行列式、方程组、实特征方向。

模型只输出代数语义;本模块负责校验并确定性生成 DiagramSpec 的 shapes。
"""

from __future__ import annotations

import cmath
import json
import math
import re
from typing import Iterable

from rag import llm

LINEAR_VISUALS = {
    "subspace", "linear_map", "determinant", "system", "eigen",
    "inner_product", "quadratic_form", "bilinear_form",
    "unitary", "symplectic", "affine", "projective", "svd",
}
TOL = 1e-9
DISPLAY = 1.6

_LINEAR_RE = re.compile(
    r"子空间|张成|span|线性空间|线性变换|线性映射|核空间|像空间|零空间|"
    r"特征值|特征向量|对角化|行列式|线性方程组|解空间|正交补|投影矩阵|"
    r"基向量|维数|内积|正交投影|Gram|施密特|二次型|双线性|正定|惯性|"
    r"对称矩阵|酉空间|酉变换|酉矩阵|复内积|Hermitian|辛空间|辛变换|"
    r"辛矩阵|辛形式|各向同性|Lagrangian|相空间|仿射|射影|无穷远|交比|"
    r"SVD|奇异值|unitary|symplectic|"
    r"极分解|条件数|低秩|R\s*\^\s*[234]|\\\\mathbb\{R\}\s*\^\s*[234]|"
    r"\bR[234]\b",
    re.IGNORECASE,
)
# 只表示“这是高等代数语义题”的词;R^n 单独出现可能只是多元微积分的定义域。
_LINEAR_CORE_RE = re.compile(
    r"子空间|张成|span|线性空间|线性变换|线性映射|核空间|像空间|零空间|"
    r"特征值|特征向量|对角化|行列式|线性方程组|解空间|正交补|投影矩阵|"
    r"基向量|维数|内积|正交投影|Gram|施密特|二次型|双线性|正定|惯性|"
    r"对称矩阵|酉空间|酉变换|酉矩阵|复内积|Hermitian|辛空间|辛变换|"
    r"辛矩阵|辛形式|各向同性|Lagrangian|相空间|仿射|射影|无穷远|交比|"
    r"SVD|奇异值|unitary|symplectic|极分解|条件数|低秩",
    re.IGNORECASE,
)


def looks_linear(question: str) -> bool:
    return bool(_LINEAR_RE.search(question or ""))


def looks_linear_core(question: str) -> bool:
    """是否明确是高等代数语义题;避免 R^2/R^3 把多元微积分也拦成线性题。"""
    return bool(_LINEAR_CORE_RE.search(question or ""))


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


def _complex(value: object) -> complex | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    real, imag = _num(value[0]), _num(value[1])
    if real is None or imag is None:
        return None
    return complex(real, imag)


def _cvec(value: object, size: int) -> list[complex] | None:
    if not isinstance(value, list) or len(value) != size:
        return None
    out = [_complex(item) for item in value]
    if any(item is None for item in out):
        return None
    return [item for item in out if item is not None]


def _cmatrix(value: object, size: int) -> list[list[complex]] | None:
    if not isinstance(value, list) or len(value) != size:
        return None
    rows: list[list[complex]] = []
    for item in value:
        row = _cvec(item, size)
        if row is None:
            return None
        rows.append(row)
    return rows


def _cmatvec(matrix: list[list[complex]], vector: list[complex]) -> list[complex]:
    return [sum(a * b for a, b in zip(row, vector)) for row in matrix]


def _cabs(value: complex) -> float:
    return abs(value)


def _is_unitary(matrix: list[list[complex]]) -> bool:
    size = len(matrix)
    for row in range(size):
        for col in range(size):
            value = sum(
                matrix[index][row].conjugate() * matrix[index][col]
                for index in range(size)
            )
            expected = 1.0 if row == col else 0.0
            if abs(value - expected) > 1e-7:
                return False
    return True


def _j_matrix(dimension: int) -> list[list[float]]:
    size = dimension * 2
    matrix = [[0.0] * size for _ in range(size)]
    for index in range(dimension):
        matrix[index][dimension + index] = 1.0
        matrix[dimension + index][index] = -1.0
    return matrix


def _is_symplectic(matrix: list[list[float]], dimension: int) -> bool:
    size = dimension * 2
    if len(matrix) != size or any(len(row) != size for row in matrix):
        return False
    j = _j_matrix(dimension)
    for row in range(size):
        for col in range(size):
            value = sum(
                matrix[k][row] * j[k][l] * matrix[l][col]
                for k in range(size) for l in range(size)
            )
            if abs(value - j[row][col]) > 1e-7:
                return False
    return True


def _project_complex(vector: list[complex], kind: str) -> list[float]:
    real = []
    for value in vector:
        real.extend([value.real, value.imag])
    if kind == "r4_to_3d":
        # 固定投影 (Re z1, Im z1, Re z2),丢掉 Im z2;图上必须标注。
        return real[:3]
    if kind == "r4_to_2d":
        return [real[0], real[1]]
    return real



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


def _transpose(matrix: list[list[float]]) -> list[list[float]]:
    return [list(row) for row in zip(*matrix)]


def _matmul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [sum(left[row][k] * right[k][col] for k in range(len(right)))
         for col in range(len(right[0]))]
        for row in range(len(left))
    ]


def _svd(matrix: list[list[float]]) -> tuple[list[float], list[list[float]], list[list[float]]]:
    """小矩阵 SVD:A = U diag(σ) Vᵀ,只用于 2×2/3×3 教学图。"""
    transpose = _transpose(matrix)
    ata = _matmul(transpose, matrix)
    pairs = _eigen_symmetric(ata)
    singular: list[float] = []
    right: list[list[float]] = []
    left: list[list[float]] = []
    for value, vector in pairs:
        sigma = math.sqrt(max(0.0, value))
        if sigma <= 1e-9:
            continue
        unit = _unit(vector)
        if unit is None:
            continue
        image = _matvec(matrix, unit)
        u = _unit(image)
        if u is None:
            continue
        singular.append(sigma)
        right.append(unit)
        left.append(u)
    return singular, left, right



def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _solve_small(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    size = len(matrix)
    if size == 1:
        return [rhs[0] / matrix[0][0]] if abs(matrix[0][0]) > TOL else None
    if size == 2:
        det = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        if abs(det) <= TOL:
            return None
        return [
            (rhs[0] * matrix[1][1] - rhs[1] * matrix[0][1]) / det,
            (matrix[0][0] * rhs[1] - matrix[1][0] * rhs[0]) / det,
        ]
    return None


def _gram_schmidt(vectors: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for vector in vectors:
        work = vector[:]
        for basis in out:
            coefficient = _dot(work, basis) / max(_dot(basis, basis), TOL)
            work = [value - coefficient * base for value, base in zip(work, basis)]
        if _norm(work) > 1e-7:
            out.append(work)
    return out


def _project_onto(basis: list[list[float]], vector: list[float]) -> list[float]:
    if not basis:
        return [0.0] * len(vector)
    gram = [[_dot(a, b) for b in basis] for a in basis]
    rhs = [_dot(a, vector) for a in basis]
    coefficients = _solve_small(gram, rhs)
    if coefficients is None:
        return [0.0] * len(vector)
    return [
        sum(coefficients[index] * basis[index][axis]
            for index in range(len(basis)))
        for axis in range(len(vector))
    ]


def _quadratic_shapes(matrix: list[list[float]], level: float,
                      ambient: int) -> list[dict]:
    if any(abs(matrix[i][j] - matrix[j][i]) > 1e-7
           for i in range(ambient) for j in range(ambient)):
        return []
    pairs = _eigen_symmetric(matrix)
    values = [value for value, _vector in pairs]
    vectors = [vector for _value, vector in pairs]
    positive = sum(1 for value in values if value > 1e-7)
    negative = sum(1 for value in values if value < -1e-7)
    zero = ambient - positive - negative
    lvl = abs(level)
    if zero:
        return []

    def rotate(local: list[float]) -> list[float]:
        return [
            sum(local[index] * vectors[index][axis]
                for index in range(ambient))
            for axis in range(ambient)
        ]

    if ambient == 2:
        shapes: list[dict] = []
        if positive == 2:
            a = math.sqrt(lvl / max(values[0], TOL))
            b = math.sqrt(lvl / max(values[1], TOL))
            points = [rotate([a * math.cos(t), b * math.sin(t)])
                      for t in (2 * math.pi * i / 120 for i in range(121))]
            shapes.append({"kind": "curve", "points": points,
                           "label": f"xᵀAx = {level:g}"})
        elif negative == 2:
            a = math.sqrt(lvl / max(-values[0], TOL))
            b = math.sqrt(lvl / max(-values[1], TOL))
            points = [rotate([a * math.cos(t), b * math.sin(t)])
                      for t in (2 * math.pi * i / 120 for i in range(121))]
            shapes.append({"kind": "curve", "points": points,
                           "label": f"xᵀAx = {level:g}"})
        elif positive == 1 and negative == 1:
            a = math.sqrt(lvl / max(values[0], TOL))
            b = math.sqrt(lvl / max(-values[1], TOL))
            for sign in (1, -1):
                points = [
                    rotate([sign * a * math.cosh(t), b * math.sinh(t)])
                    for t in (-2 + 4 * i / 100 for i in range(101))
                ]
                shapes.append({"kind": "curve", "points": points})
        return shapes

    if ambient != 3:
        return []
    rows, cols = 31, 31
    points: list[list[float]] = []
    if positive == 3:
        a = math.sqrt(lvl / max(values[0], TOL))
        b = math.sqrt(lvl / max(values[1], TOL))
        c = math.sqrt(lvl / max(values[2], TOL))
        for row in range(rows):
            u = -math.pi / 2 + math.pi * row / (rows - 1)
            for col in range(cols):
                v = 2 * math.pi * col / (cols - 1)
                points.append(rotate([
                    a * math.cos(u) * math.cos(v),
                    b * math.cos(u) * math.sin(v),
                    c * math.sin(u),
                ]))
    elif negative == 3:
        a = math.sqrt(lvl / max(-values[0], TOL))
        b = math.sqrt(lvl / max(-values[1], TOL))
        c = math.sqrt(lvl / max(-values[2], TOL))
        for row in range(rows):
            u = -math.pi / 2 + math.pi * row / (rows - 1)
            for col in range(cols):
                v = 2 * math.pi * col / (cols - 1)
                points.append(rotate([
                    a * math.cos(u) * math.cos(v),
                    b * math.cos(u) * math.sin(v),
                    c * math.sin(u),
                ]))
    elif positive == 2 and negative == 1:
        a = math.sqrt(lvl / max(values[0], TOL))
        b = math.sqrt(lvl / max(values[1], TOL))
        c = math.sqrt(lvl / max(-values[2], TOL))
        for row in range(rows):
            u = -1.2 + 2.4 * row / (rows - 1)
            for col in range(cols):
                v = 2 * math.pi * col / (cols - 1)
                points.append(rotate([
                    a * math.cosh(u) * math.cos(v),
                    b * math.cosh(u) * math.sin(v),
                    c * math.sinh(u),
                ]))
    elif positive == 1 and negative == 2:
        a = math.sqrt(lvl / max(values[0], TOL))
        b = math.sqrt(lvl / max(-values[1], TOL))
        c = math.sqrt(lvl / max(-values[2], TOL))
        for row in range(rows):
            u = -1.2 + 2.4 * row / (rows - 1)
            for col in range(cols):
                v = 2 * math.pi * col / (cols - 1)
                points.append(rotate([
                    a * math.cosh(u),
                    b * math.sinh(u) * math.cos(v),
                    c * math.sinh(u) * math.sin(v),
                ]))
    if not points:
        return []
    return [{
        "kind": "surface", "points": points,
        "rows": rows, "cols": cols,
        "label": f"xᵀAx = {level:g}",
    }]


def _signature(matrix: list[list[float]]) -> tuple[int, int, int]:
    values = [value for value, _vector in _eigen_symmetric(matrix)]
    positive = sum(1 for value in values if value > 1e-7)
    negative = sum(1 for value in values if value < -1e-7)
    return positive, negative, len(values) - positive - negative



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
    """校验模型给出的线性代数语义计划;实空间 2D/3D,复空间 C/C² 投影。"""
    if not isinstance(raw, dict):
        return None
    visual = _text(raw.get("visual"), 30).lower()
    if visual not in LINEAR_VISUALS:
        return None
    domain = _text(raw.get("domain", "real"), 20).lower()
    if visual == "unitary":
        if domain != "complex":
            return None
        ambient = _integer(raw.get("ambient"), 1, 2)
        # 模型常把 2×2 复矩阵的 ambient 写成 1;矩阵本身是 2×2 时按 C² 处理,
        # 不能截成 1×1,否则会把旋转/特征值关系画错。
        if ambient == 1:
            candidate = _cmatrix(raw.get("matrix"), 2)
            if candidate is not None:
                ambient = 2
    elif visual == "symplectic":
        if domain != "real":
            return None
        ambient = _integer(raw.get("ambient"), 2, 4)
        if ambient not in (2, 4):
            return None
    else:
        if domain != "real":
            return None
        ambient = _integer(raw.get("ambient"), 2, 3)
    if ambient is None:
        return None
    result: dict = {
        "visual": visual,
        "domain": domain,
        "ambient": ambient,
    }
    title = _text(raw.get("title"), 200)
    if title:
        result["title"] = title
    projection = raw.get("projection")
    if isinstance(projection, dict):
        kind = _text(projection.get("kind"), 30).lower()
        if kind not in ("none", "complex_to_real", "r4_to_3d", "r4_to_2d"):
            return None
        note = _text(projection.get("note"), 160)
        result["projection"] = {"kind": kind, "note": note}
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
    elif visual == "quadratic_form":
        matrix = _matrix(raw.get("matrix"), ambient)
        if matrix is None:
            return None
        level = _num(raw.get("level", 1.0))
        if level is None or abs(level) < TOL:
            level = 1.0
        result["matrix"] = matrix
        result["level"] = level
    elif visual == "bilinear_form":
        matrix = _matrix(raw.get("matrix"), ambient)
        if matrix is None:
            return None
        result["matrix"] = matrix
    elif visual == "inner_product":
        operation = _text(raw.get("operation"), 30).lower()
        if operation not in (
                "projection", "orthogonal_complement",
                "gram_schmidt", "orthonormal_basis"):
            return None
        result["operation"] = operation
        if operation == "projection":
            vector = _vec(raw.get("vector"), ambient)
            subspace = raw.get("subspace")
            if vector is None or not isinstance(subspace, dict):
                return None
            basis = _subspace_basis(subspace, ambient)
            if basis is None:
                return None
            dimension, kind, offset, vectors = basis
            result["vector"] = vector
            result["subspace"] = {
                "dimension": dimension, "kind": kind,
                "offset": offset, "basis": vectors,
            }
        elif operation == "orthogonal_complement":
            subspace = raw.get("subspace")
            if not isinstance(subspace, dict):
                return None
            basis = _subspace_basis(subspace, ambient)
            if basis is None:
                return None
            dimension, kind, offset, vectors = basis
            result["subspace"] = {
                "dimension": dimension, "kind": kind,
                "offset": offset, "basis": vectors,
            }
        else:
            vectors = _vectors(raw.get("vectors"), ambient)
            if vectors is None or not 1 <= len(vectors) <= ambient:
                return None
            if any(_norm(vector) < TOL for vector in vectors):
                return None
            result["vectors"] = vectors
    elif visual == "unitary":
        matrix = _cmatrix(raw.get("matrix"), ambient)
        if matrix is None or not _is_unitary(matrix):
            return None
        vector = _cvec(raw.get("vector", None), ambient)
        if vector is None:
            vector = [1.0 + 0.0j] + [0.0j] * (ambient - 1)
        projection = result.get("projection") or {}
        if ambient == 1:
            result["projection"] = {
                "kind": "complex_to_real",
                "note": _text(projection.get("note"), 160) or "C → R² 实坐标",
            }
        elif not projection or projection.get("kind") not in (
                "r4_to_3d", "r4_to_2d"):
            result["projection"] = {
                "kind": "r4_to_3d",
                "note": "C² → R⁴ → R³ 投影,虚线方向仅示意",
            }
        result["matrix"] = matrix
        result["vector"] = vector
    elif visual == "symplectic":
        size = ambient
        matrix = _matrix(raw.get("matrix"), size)
        if matrix is None:
            matrix = _j_matrix(size // 2)
        if not _is_symplectic(matrix, size // 2):
            return None
        projection = result.get("projection") or {}
        if ambient == 4 and projection.get("kind") not in (
                "r4_to_3d", "r4_to_2d"):
            result["projection"] = {
                "kind": "r4_to_3d",
                "note": "R⁴ → R³ 投影,只示意辛基与面积关系",
            }
        result["matrix"] = matrix
    elif visual == "affine":
        operation = _text(
            raw.get("operation")
            or ("subspace" if raw.get("subspace") else "transform"), 20).lower()
        if operation not in ("transform", "subspace"):
            return None
        result["operation"] = operation
        if operation == "transform":
            matrix = _matrix(raw.get("matrix"), ambient)
            translation = _vec(raw.get("translation", [0.0] * ambient), ambient)
            if matrix is None or translation is None:
                return None
            result["matrix"] = matrix
            result["translation"] = translation
            source = _text(raw.get("source"), 20).lower()
            if source in ("triangle", "square", "parallelogram"):
                result["source"] = source
        else:
            subspace = raw.get("subspace")
            if not isinstance(subspace, dict):
                return None
            basis = _subspace_basis(subspace, ambient)
            if basis is None:
                return None
            dimension, kind, offset, vectors = basis
            result["subspace"] = {
                "dimension": dimension, "kind": kind,
                "offset": offset, "basis": vectors,
            }
    elif visual == "projective":
        if ambient != 2:
            return None
        operation = _text(
            raw.get("operation")
            or ("transform" if raw.get("matrix") else "line_at_infinity"),
            25).lower()
        if operation not in ("line_at_infinity", "transform", "cross_ratio"):
            return None
        result["operation"] = operation
        if operation == "transform":
            matrix = _matrix(raw.get("matrix"), 3)
            if matrix is None:
                return None
            result["matrix"] = matrix
        elif operation == "cross_ratio":
            points = _vectors(raw.get("points"), 2, 4)
            if points is None:
                return None
            result["points"] = points
    elif visual == "svd":
        matrix = _matrix(raw.get("matrix"), ambient)
        if matrix is None:
            return None
        operation = _text(raw.get("operation", "svd"), 20).lower()
        if operation not in ("svd", "polar", "condition"):
            return None
        result["operation"] = operation
        result["matrix"] = matrix
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


def _build_quadratic(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    level = linear.get("level", 1.0)
    shapes = _quadratic_shapes(matrix, level, ambient)
    if not shapes:
        return None
    shapes.insert(0, _point([0.0] * ambient, "O"))
    positive, negative, zero = _signature(matrix)
    notes = [_annotation(
        [0.8] * ambient,
        f"signature = ({positive}, {negative}, {zero})",
    )]
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _build_bilinear(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    symmetric = all(
        abs(matrix[i][j] - matrix[j][i]) < 1e-7
        for i in range(ambient) for j in range(ambient)
    )
    if symmetric:
        built = _build_quadratic({
            "ambient": ambient, "matrix": matrix, "level": 1.0,
        })
        if built is None:
            return None
        type_name, shapes, notes = built
        notes.append(_annotation([0.8] * ambient, "对称双线性型"))
        return type_name, shapes, notes
    if ambient == 2:
        # 反对称型在二维就是有向面积形式。
        e1 = [1.0, 0.0]
        e2 = [0.0, 1.0]
        shapes = [
            _point([0.0, 0.0], "O"),
            _vector([0.0, 0.0], e1, "e1"),
            _vector([0.0, 0.0], e2, "e2"),
            _polygon([[0.0, 0.0], e1, [1.0, 1.0], e2], "ω"),
        ]
        value = matrix[0][1]
        notes = [_annotation([0.6, 0.6], f"ω(e1,e2) = {value:.3g}")]
        return "plot2d", shapes, notes
    return None


def _build_inner_product(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    operation = linear["operation"]
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    if operation == "projection":
        vector = linear["vector"]
        subspace = linear["subspace"]
        offset = subspace["offset"]
        basis = subspace["basis"]
        shifted = [value - base for value, base in zip(vector, offset)]
        projected = _add(offset, _project_onto(basis, shifted))
        residual = [value - base for value, base in zip(vector, projected)]
        shapes.extend(_subspace_through(offset, basis, "S", ambient))
        shapes.append(_vector(origin, vector, "v"))
        shapes.append(_vector(origin, projected, "proj_S v"))
        shapes.append(_vector(projected, vector, "v - proj"))
        notes.append(_annotation(
            _add(projected, residual, 0.25),
            "残差与 S 正交",
        ))
    elif operation == "orthogonal_complement":
        subspace = linear["subspace"]
        offset = subspace["offset"]
        basis = subspace["basis"]
        transpose = [
            [basis[j][axis] for j in range(len(basis))]
            for axis in range(ambient)
        ]
        complement = _nullspace(transpose)
        shapes.extend(_subspace_through(offset, basis, "S", ambient))
        shapes.extend(_subspace_through(origin, complement, "S⊥", ambient))
        notes.append(_annotation(
            _add(origin, [0.8] * ambient),
            f"dim S = {len(basis)}, dim S⊥ = {len(complement)}",
        ))
    else:
        vectors = linear["vectors"]
        basis = _gram_schmidt(vectors)
        for index, vector in enumerate(basis):
            unit = _unit(vector) if operation == "orthonormal_basis" else None
            display = unit if unit is not None else _unit(vector)
            if display is None:
                continue
            shapes.append(_vector(origin, _add(origin, display, DISPLAY),
                                  f"u{index + 1}"))
        if operation == "orthonormal_basis":
            notes.append(_annotation(_add(origin, [0.8] * ambient),
                                     "标准正交基"))
        else:
            notes.append(_annotation(_add(origin, [0.8] * ambient),
                                     "Gram-Schmidt 正交化"))
    type_name = "geometry3d" if ambient == 3 else "plot2d"
    return type_name, shapes, notes


def _project_real4(vector: list[float], kind: str) -> list[float]:
    if kind == "r4_to_3d":
        return vector[:3]
    if kind == "r4_to_2d":
        return vector[:2]
    return vector[:]


def _angle_text(angle: float) -> str:
    """把弧度角写成 π 的简约分数;非有理数才退回小数。"""
    ratio = angle / math.pi
    for denominator in range(1, 13):
        numerator = round(ratio * denominator)
        if abs(ratio - numerator / denominator) < 1e-6:
            if numerator == 0:
                return "0"
            sign = "-" if numerator < 0 else ""
            numerator = abs(numerator)
            if denominator == 1:
                return f"{sign}π" if numerator == 1 else f"{sign}{numerator}π"
            if numerator == 1:
                return f"{sign}π/{denominator}"
            return f"{sign}{numerator}π/{denominator}"
    return f"{angle:.3g} rad"


def _build_unitary(linear: dict) -> tuple[str, list[dict], list[dict]]:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    vector = linear["vector"]
    image = _cmatvec(matrix, vector)
    projection = linear.get("projection", {})
    kind = projection.get("kind", "complex_to_real")
    note = projection.get("note", "")
    shapes: list[dict] = []
    notes: list[dict] = []
    if ambient == 1:
        z = [vector[0].real, vector[0].imag]
        uz = [image[0].real, image[0].imag]
        circle = [
            [math.cos(2 * math.pi * i / 120), math.sin(2 * math.pi * i / 120)]
            for i in range(121)
        ]
        shapes.append({"kind": "curve", "points": circle, "label": "|z|=1"})
        shapes.append(_point([0.0, 0.0], "O"))
        shapes.append(_vector([0.0, 0.0], z, "z"))
        shapes.append(_vector([0.0, 0.0], uz, "Uz"))
        start = math.atan2(z[1], z[0])
        angle = math.atan2(uz[1], uz[0]) - start
        while angle <= -math.pi:
            angle += 2 * math.pi
        while angle > math.pi:
            angle -= 2 * math.pi
        if abs(angle) > 1e-6:
            # 从 z 到 Uz 的短弧:直接标在映射发生的位置,不另设图例。
            arc = [
                [math.cos(start + angle * step / 48),
                 math.sin(start + angle * step / 48)]
                for step in range(49)
            ]
            shapes.append({
                "kind": "curve", "points": arc,
                "label": f"旋转 {_angle_text(angle)}",
            })
        notes.append(_annotation([0.8, 0.8],
                                 f"|z| = {math.hypot(*z):.3g}"))
        type_name = "plot2d"
    else:
        project = lambda value: _project_complex(value, kind)  # noqa: E731
        z = project(vector)
        uz = project(image)
        shapes.append(_point([0.0] * len(z), "O"))
        shapes.append(_vector([0.0] * len(z), z, "z"))
        shapes.append(_vector([0.0] * len(z), uz, "Uz"))
        if len(z) >= 3:
            shapes.append(_plane([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 2.4, "C² 投影"))
        notes.append(_annotation(_add([0.0] * len(z), [0.7] * len(z)),
                                 f"|z| = {math.sqrt(sum(abs(v) ** 2 for v in vector)):.3g}"))
        type_name = "geometry3d" if len(z) >= 3 else "plot2d"
    if note:
        notes.append(_annotation([0.0] * len(z), note))
    return type_name, shapes, notes


def _build_symplectic(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    projection = linear.get("projection", {})
    kind = projection.get("kind", "none")
    note = projection.get("note", "")
    origin = [0.0] * ambient
    shapes: list[dict] = []
    notes: list[dict] = []
    if ambient == 2:
        e1 = [1.0, 0.0]
        f1 = [0.0, 1.0]
        shapes.append(_point(origin, "O"))
        shapes.append(_vector(origin, e1, "e1"))
        shapes.append(_vector(origin, f1, "f1"))
        shapes.append(_polygon([origin, e1, [1.0, 1.0], f1], "ω"))
        shapes.append(_segment([-1.4, -1.4], [1.4, 1.4], "各向同性"))
        shapes.append(_segment([-1.4, 1.4], [1.4, -1.4], "各向同性"))
        notes.append(_annotation([0.7, 0.7], "ω(e1,f1) = 1"))
        return "plot2d", shapes, notes
    if ambient != 4:
        return None
    basis = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
    labels = ["e1", "e2", "f1", "f2"]
    projected = [_project_real4(vector, kind) for vector in basis]
    dim = len(projected[0])
    shapes.append(_point([0.0] * dim, "O"))
    for vector, label in zip(projected, labels):
        unit = _unit(vector)
        if unit is not None:
            shapes.append(_vector([0.0] * dim, _add([0.0] * dim, unit, DISPLAY),
                                  label))
    if dim >= 3:
        shapes.append(_plane([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], 2.4,
                             "Lagrangian 投影"))
    notes.append(_annotation([0.7] * dim, "ω 由辛基与面积给"))
    if note:
        notes.append(_annotation([0.0] * dim, note))
    return "geometry3d" if dim >= 3 else "plot2d", shapes, notes


def _build_affine(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    operation = linear["operation"]
    if operation == "subspace":
        built = _build_subspace({
            "ambient": ambient, "subspace": linear["subspace"],
        })
        type_name, shapes, notes = built
        offset = linear["subspace"]["offset"]
        if linear["subspace"]["kind"] == "affine" and _norm(offset) > TOL:
            shapes.append(_segment([0.0] * ambient, offset, "b"))
        return type_name, shapes, notes
    matrix = linear["matrix"]
    translation = linear["translation"]
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    if ambient == 2:
        source_kind = linear.get("source", "square")
        if source_kind == "triangle":
            source = [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]
        elif source_kind == "parallelogram":
            source = [[0.0, 0.0], [1.0, 0.0], [1.4, 0.8], [0.4, 0.8]]
        else:
            source = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        image = [
            _add(_matvec(matrix, point), translation)
            for point in source
        ]
        shapes.append(_polygon(source, "原像"))
        shapes.append(_polygon(image, "像"))
        for index, point in enumerate(source):
            shapes.append(_point(point, chr(ord("A") + index)))
        for index, point in enumerate(image):
            shapes.append(_point(point, f"{chr(ord('A') + index)}'"))
        notes.append(_annotation(_add(image[0], [-0.8, -0.8]),
                                 "x ↦ Ax + b"))
        if source_kind != "triangle":
            notes.append(_annotation(
                _add(image[1], [0.7, -0.7]),
                "对应边保持平行",
            ))
        else:
            notes.append(_annotation(
                _add(image[0], [0.4, -0.8]),
                "仿射不保方向,只保平行;三角形无平行边可对照",
            ))
        type_name = "plot2d"
    else:
        basis = [[1.0 if i == j else 0.0 for j in range(ambient)]
                 for i in range(ambient)]
        for index, vector in enumerate(basis):
            shapes.append(_vector(origin, vector, f"e{index + 1}"))
            image = _add(_matvec(matrix, vector), translation)
            shapes.append(_vector(translation, image, f"Ae{index + 1}"))
        shapes.append(_point(translation, "b"))
        notes.append(_annotation(_add(translation, [0.6, 0.6, 0.6]),
                                 "x ↦ Ax + b"))
        type_name = "geometry3d"
    return type_name, shapes, notes


def _homography(matrix: list[list[float]], point: list[float]) -> list[float] | None:
    vector = [point[0], point[1], 1.0]
    result = [sum(row[index] * vector[index] for index in range(3))
              for row in matrix]
    if abs(result[2]) < 1e-9:
        return None
    return [result[0] / result[2], result[1] / result[2]]


def _build_projective(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    operation = linear["operation"]
    shapes: list[dict] = []
    notes: list[dict] = []
    if operation == "line_at_infinity":
        shapes.append(_segment([-2.4, 2.0], [2.4, 2.0], "无穷远线"))
        shapes.append(_segment([-2.4, 0.0], [2.4, 0.0]))
        shapes.append(_segment([-2.4, 1.0], [2.4, 1.0]))
        shapes.append(_point([0.0, 2.0], "∞"))
        notes.append(_annotation([0.5, 2.25], "平行线在无穷远点相交"))
    elif operation == "cross_ratio":
        points = linear["points"]
        shapes.append(_point(points[0], "P1"))
        shapes.append(_point(points[1], "P2"))
        shapes.append(_point(points[2], "P3"))
        shapes.append(_point(points[3], "P4"))
        direction = [points[-1][0] - points[0][0],
                     points[-1][1] - points[0][1]]
        length = max(_norm(direction), TOL)
        unit = [direction[0] / length, direction[1] / length]
        params = [_dot([p[0] - points[0][0], p[1] - points[0][1]], unit)
                  for p in points]
        denominator = (params[0] - params[3]) * (params[1] - params[2])
        value = (
            (params[0] - params[2]) * (params[1] - params[3]) / denominator
            if abs(denominator) > TOL else float("inf")
        )
        shapes.append(_segment(
            [points[0][0] - unit[0], points[0][1] - unit[1]],
            [points[-1][0] + unit[0], points[-1][1] + unit[1]],
        ))
        notes.append(_annotation([0.4, 0.4], f"交比 = {value:.3g}"))
    else:
        matrix = linear["matrix"]
        source = [[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]]
        image = [_homography(matrix, point) for point in source]
        if any(point is None for point in image):
            return None
        shapes.append(_polygon(source, "原像"))
        shapes.append(_polygon([point for point in image if point is not None],
                               "射影像"))
        shapes.append(_segment([-2.4, 2.0], [2.4, 2.0], "无穷远线"))
        notes.append(_annotation([1.4, 1.3], "齐次坐标 / 投影变换"))
        notes.append(_annotation([1.4, -1.4],
                                 "射影不保平行;原图平行边交于无穷远"))
    return "plot2d", shapes, notes


def _build_svd(linear: dict) -> tuple[str, list[dict], list[dict]] | None:
    ambient = linear["ambient"]
    matrix = linear["matrix"]
    operation = linear.get("operation", "svd")
    singular, left, _right = _svd(matrix)
    if not singular:
        return None
    origin = [0.0] * ambient
    shapes: list[dict] = [_point(origin, "O")]
    notes: list[dict] = []
    for index, (sigma, vector) in enumerate(zip(singular, left)):
        axis = _scale(vector, sigma)
        shapes.append(_vector(origin, axis, f"σ{index + 1}"))
    if ambient == 2:
        circle = [[math.cos(2 * math.pi * i / 120),
                   math.sin(2 * math.pi * i / 120)] for i in range(121)]
        shapes.append({"kind": "curve", "points": circle, "label": "单位圆"})
        ellipse = [_matvec(matrix, point) for point in circle]
        shapes.append({"kind": "curve", "points": ellipse, "label": "A(S¹)"})
        type_name = "plot2d"
    else:
        rows, cols = 25, 25
        points: list[list[float]] = []
        for row in range(rows):
            u = -math.pi / 2 + math.pi * row / (rows - 1)
            for col in range(cols):
                v = 2 * math.pi * col / (cols - 1)
                unit = [math.cos(u) * math.cos(v),
                        math.cos(u) * math.sin(v), math.sin(u)]
                points.append(_matvec(matrix, unit))
        shapes.append({
            "kind": "surface", "points": points,
            "rows": rows, "cols": cols, "label": "A(S²)",
        })
        type_name = "geometry3d"
    values = ", ".join(f"{value:.3g}" for value in singular)
    if len(singular) >= 2:
        condition = singular[0] / max(singular[-1], TOL)
        notes.append(_annotation([0.6] * ambient,
                                 f"σ = ({values}), cond = {condition:.3g}"))
    else:
        notes.append(_annotation([0.6] * ambient, f"σ = ({values})"))
    if operation == "polar":
        notes.append(_annotation([0.6] * ambient, "极分解 = 旋转 × 对称拉伸"))
    elif operation == "condition":
        notes.append(_annotation([0.6] * ambient, "条件数 = 最大/最小拉伸"))
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
    elif visual == "quadratic_form":
        built = _build_quadratic(linear)
    elif visual == "bilinear_form":
        built = _build_bilinear(linear)
    elif visual == "inner_product":
        built = _build_inner_product(linear)
    elif visual == "unitary":
        built = _build_unitary(linear)
    elif visual == "symplectic":
        built = _build_symplectic(linear)
    elif visual == "affine":
        built = _build_affine(linear)
    elif visual == "projective":
        built = _build_projective(linear)
    elif visual == "svd":
        built = _build_svd(linear)
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
            "inner_product": "内积与正交",
            "quadratic_form": "二次型的几何形状",
            "bilinear_form": "双线性型的几何意义",
            "unitary": "酉变换与复结构投影",
            "symplectic": "辛结构与相空间",
            "affine": "仿射变换与仿射子空间",
            "projective": "射影几何",
            "svd": "SVD 与矩阵拉伸",
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


def _parse_complex_entry(value: str) -> complex | None:
    text = value.strip().replace("−", "-").replace(" ", "")
    if not text:
        return None
    if text in ("i", "+i"):
        return 1j
    if text == "-i":
        return -1j
    try:
        return complex(float(text), 0.0)
    except ValueError:
        pass
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))?([+-])?i", text)
    if match and match.group(1) is None:
        return complex(0.0, -1.0 if match.group(2) == "-" else 1.0)
    match = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([+-])(\d+(?:\.\d*)?|\.\d+)?i",
        text)
    if match:
        real = float(match.group(1))
        imag = float(match.group(3) or 1.0)
        return complex(real, -imag if match.group(2) == "-" else imag)
    return None


def _question_matrix(question: str) -> list[list[complex]] | None:
    """从题面里的 [[a,b],[c,d]] 提取 2×2 复矩阵,并处理常见 1/√2 因子。"""
    match = re.search(
        r"\[\s*\[[^\]]+\]\s*,\s*\[[^\]]+\]\s*\]", question or "")
    if not match:
        return None
    rows = re.findall(r"\[([^\[\]]+)\]", match.group(0))
    if len(rows) != 2:
        return None
    matrix: list[list[complex]] = []
    for row in rows:
        cells = [cell for cell in re.split(r"[,，]", row) if cell.strip()]
        if len(cells) != 2:
            return None
        parsed = [_parse_complex_entry(cell) for cell in cells]
        if any(item is None for item in parsed):
            return None
        matrix.append([item for item in parsed if item is not None])
    factor = 1.0
    before = (question or "")[:match.start()]
    scale = re.search(r"1\s*/\s*(?:√|sqrt\()?\s*(2)\s*\)?\s*$", before)
    if scale:
        factor = 1.0 / math.sqrt(float(scale.group(1)))
    return [[item * factor for item in row] for row in matrix]


def _eigenvalues_2x2(matrix: list[list[complex]]) -> tuple[complex, complex]:
    a, b = matrix[0]
    c, d = matrix[1]
    trace = a + d
    determinant = a * d - b * c
    root = cmath.sqrt(trace * trace - 4 * determinant)
    return (trace + root) / 2, (trace - root) / 2


def _complex_text(value: complex) -> str:
    if abs(abs(value) - 1.0) < 1e-6:
        angle = cmath.phase(value)
        if abs(angle) < 1e-9:
            return "1"
        if abs(abs(angle) - math.pi) < 1e-9:
            return "-1"
        text = _angle_text(angle)
        if text in ("π", "-π"):
            return "-1"
        if text == "π/2":
            return "i"
        if text == "-π/2":
            return "-i"
        if angle < 0:
            return f"e^(-i{text[1:]})"
        return f"e^(i{text})"
    return f"{value.real:.3g}{value.imag:+.3g}i"


def _unitary_spectrum_from_question(question: str) -> dict | None:
    """语义规划失败时的确定性兜底:把 2×2 酉矩阵的谱画在复平面单位圆上。

    每个 λ 点用自己算出的坐标和角度标注,不再让模型自由摆放 λ 标签。
    """
    if not re.search(r"酉|unitary", question or "", re.IGNORECASE):
        return None
    matrix = _question_matrix(question)
    if matrix is None or not _is_unitary(matrix):
        return None
    first, second = _eigenvalues_2x2(matrix)
    circle = [
        [math.cos(2 * math.pi * index / 120),
         math.sin(2 * math.pi * index / 120)]
        for index in range(121)
    ]
    shapes: list[dict] = [
        {"kind": "curve", "points": circle, "label": "|z|=1"},
        _point([0.0, 0.0], "O"),
    ]
    notes: list[dict] = []
    for index, value in enumerate((first, second)):
        label = f"λ{'₁₂'[index]}"
        shapes.append(_point([value.real, value.imag], label))
        notes.append(_annotation(
            [value.real * 1.18, value.imag * 1.18],
            f"{label} = {_complex_text(value)}",
        ))
    notes.append(_annotation([0.0, -1.22], "C² 保范:单位圆→单位圆"))
    notes.append(_annotation([0.0, -1.46], "2×2 U;单平面只画谱"))
    return {
        "schemaVersion": 1,
        "type": "plot2d",
        "title": "2×2 酉矩阵:保范与谱",
        "nodes": [], "edges": [],
        "shapes": shapes, "annotations": notes,
    }


_LINEAR_SYSTEM = """你是高等代数图解规划器。只输出一个 JSON 对象,不要 Markdown、不要解释。
模型只给代数语义,不要给 shapes/points/坐标网格。
schema:
{
  "visual": "subspace|linear_map|determinant|system|eigen|inner_product|quadratic_form|bilinear_form|unitary|symplectic|affine|projective|svd",
  "domain": "real|complex",
  "ambient": 1|2|3|4,
  "title": "中文标题",
  "operation": "projection|orthogonal_complement|gram_schmidt|orthonormal_basis|transform|subspace|line_at_infinity|cross_ratio|svd|polar|condition",
  "projection": {"kind": "none|complex_to_real|r4_to_3d|r4_to_2d", "note": "投影说明"},
  "subspace": {"dimension": 0-3, "kind": "linear|affine",
               "offset": [x,y] 或 [x,y,z], "basis": [[...]], "label": "短标签"},
  "matrix": [[...]],
  "translation": [x,y] 或 [x,y,z],
  "source": "triangle|square|parallelogram",
  "vectors": [[...]],
  "vector": [x,y] 或 [x,y,z],
  "points": [[x,y]],
  "level": 1,
  "equations": [[a,b,c] 或 [a,b,c,d]]
}
规则:
1. R^2/R² 用 ambient 2;R^3/R³/空间子空间用 ambient 3。
2. 线性子空间 offset 必须为零;仿射子空间 offset 非零。
3. basis 数量必须等于 dimension,且线性无关。
4. determinant 的 vectors 数量等于 ambient。
5. eigen 只给实对称矩阵。
6. system 每条方程:2D 为 [a,b,c] 表示 ax+by=c;3D 为 [a,b,c,d] 表示 ax+by+cz=d。
7. inner_product:
   - projection 给 vector + subspace;
   - orthogonal_complement 给 subspace;
   - gram_schmidt / orthonormal_basis 给 vectors。
8. quadratic_form / bilinear_form 给对称矩阵;二次型曲面默认 level=1。
9. unitary 用 domain=complex;1×1 复矩阵才用 ambient=1,2×2 复矩阵必须用
   ambient=2;复数矩阵元素写 [实部,虚部];ambient=2 时必须给 projection
   r4_to_3d 或 r4_to_2d 和 note。不要把 2×2 矩阵硬塞成 1×1。
10. symplectic 用 domain=real,ambient=2 或 4;矩阵必须满足 MᵀJM=J;
    ambient=4 时必须给 projection r4_to_3d 或 r4_to_2d 和 note。
11. affine: transform 给 matrix + translation;subspace 给 subspace。
   用户说三角形时 source=triangle,说平行四边形时 source=parallelogram,
   否则 source=square。
12. projective: ambient=2;transform 给 3×3 齐次矩阵;cross_ratio 给 4 个共线点。
13. svd: 给 2×2/3×3 实矩阵;operation 为 svd/polar/condition。
14. 不要输出 abstract 的商空间/张量/PID 模;这些不在本期内。
15. 不要解释选型或权重。
示例: R^3 中由 e1,e2 张成的平面
{"visual":"subspace","domain":"real","ambient":3,"title":"R^3 中的坐标平面",
 "subspace":{"dimension":2,"kind":"linear","offset":[0,0,0],
 "basis":[[1,0,0],[0,1,0]],"label":"span(e1,e2)"}}
示例: 二次型 x^2+2y^2=1
{"visual":"quadratic_form","domain":"real","ambient":2,
 "matrix":[[1,0],[0,2]],"level":1}
"""


async def plan_linear(question: str, before: str, role: str = "main") -> dict | None:
    """让模型输出高等代数语义计划;酉矩阵可走确定性谱图兜底。"""
    if not llm.is_configured(role):
        return _unitary_spectrum_from_question(question)
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
        return _unitary_spectrum_from_question(question)
    raw = _load_json("".join(parts))
    if raw is None:
        return _unitary_spectrum_from_question(question)
    if not raw.get("type"):
        raw["type"] = "geometry3d" if raw.get("ambient") == 3 else "geometry2d"
    built = build_linear_diagram({"type": raw.get("type"),
                                  "title": raw.get("title"),
                                  "linear": raw})
    # 2×2 酉矩阵问“复平面/单位圆/特征值”时,C² 的四维投影会绕开用户要看的谱;
    # 用题面矩阵确定性地画单位圆上的 λ,不依赖模型摆标签。
    if re.search(r"复平面|单位圆|特征值|谱", question or ""):
        spectrum = _unitary_spectrum_from_question(question)
        if spectrum is not None:
            return spectrum
    if built is None:
        built = _unitary_spectrum_from_question(question)
    return built
