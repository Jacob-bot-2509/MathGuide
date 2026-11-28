"""隐式曲面网格误差指标:三角形数 / 二进制体积 / 最大弦高 / 法向偏差。

用途:决定是否值得做自适应网格。只用确定性的 F(x,y,z) 与 marching tetra,
不调用模型,不需要登录。

用法(backend 目录下):
    python tools/diagram_mesh_metrics.py
    python tools/diagram_mesh_metrics.py --resolutions 12,20,28,36,44
    python tools/diagram_mesh_metrics.py --json docs/reports/diagram-mesh-metrics.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import research_diagrams as rd  # noqa: E402

SURFACES = {
    "sphere": {
        "expr": "x^2+y^2+z^2-1",
        "domain": [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
    },
    "paraboloid": {
        "expr": "z-x^2-y^2",
        "domain": [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
    },
    "saddle": {
        "expr": "z-x^2+y^2",
        "domain": [-1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
    },
    "torus": {
        # R=1, r=0.4
        "expr": "(x^2+y^2+z^2+0.84)^2 - 4*(x^2+y^2)",
        "domain": [-1.5, 1.5, -1.5, 1.5, -1.0, 1.0],
    },
    "two_spheres": {
        # 两个半径 0.6 的球,球心相距 1.4,中间留 0.2 的窄缝
        "expr": "(x^2+y^2+z^2-0.36)*((x-1.4)^2+y^2+z^2-0.36)",
        "domain": [-0.8, 2.2, -0.8, 0.8, -0.8, 0.8],
    },
}


def _sample_points(triangle: list[list[float]]) -> list[tuple[float, float, float]]:
    return [tuple(sum(point[index] for point in triangle) / 3
                  for index in range(3))]


def _gradient(run, point: tuple[float, float, float]):
    x, y, z = point
    h = 1e-4 * max(1.0, abs(x), abs(y), abs(z))
    try:
        value = run(x, y, z)
        gx = (run(x + h, y, z) - run(x - h, y, z)) / (2 * h)
        gy = (run(x, y + h, z) - run(x, y - h, z)) / (2 * h)
        gz = (run(x, y, z + h) - run(x, y, z - h)) / (2 * h)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    norm = math.sqrt(gx * gx + gy * gy + gz * gz)
    if norm < 1e-9 or not all(math.isfinite(v) for v in (value, gx, gy, gz)):
        return None
    return value, (gx / norm, gy / norm, gz / norm)


def _project(run, point: tuple[float, float, float]):
    current = point
    for _ in range(4):
        result = _gradient(run, current)
        if result is None:
            break
        value, unit = result
        # 用中心差分的未归一化梯度做牛顿步；unit 只是方向。
        x, y, z = current
        h = 1e-4 * max(1.0, abs(x), abs(y), abs(z))
        raw = ((run(x + h, y, z) - run(x - h, y, z)) / (2 * h),
               (run(x, y + h, z) - run(x, y - h, z)) / (2 * h),
               (run(x, y, z + h) - run(x, y, z - h)) / (2 * h))
        denom = sum(item * item for item in raw)
        if denom < 1e-18:
            break
        current = tuple(current[index] - value * raw[index] / denom
                        for index in range(3))
        if abs(value) < 1e-8:
            break
    return current


def _surface_distance(run, point) -> float | None:
    # F/|∇F| 是到零水平面的近似距离;不能先投影再量,否则恒为 0。
    result = _gradient(run, point)
    if result is None:
        return None
    return abs(result[0])


def _normal_deviation(normal, true_normal) -> float:
    dot = abs(sum(normal[index] * true_normal[index] for index in range(3)))
    dot = max(-1.0, min(1.0, dot))
    return math.degrees(math.acos(dot))


def measure(surface: dict, resolution: int, stride: int = 1) -> dict:
    shape = {
        "kind": "implicit_surface",
        "expr": surface["expr"],
        "domain": surface["domain"],
        "resolution": resolution,
    }
    if not rd._sample_shape(shape):
        return {"resolution": resolution, "error": "sample_failed"}
    run = rd._compile_xyz_expr(shape["expr"])
    positions = shape["positions"]
    indices = shape["indices"]
    triangles = [
        [
            [positions[indices[i] * 3], positions[indices[i] * 3 + 1],
             positions[indices[i] * 3 + 2]]
            for i in range(triangle, triangle + 3)
        ]
        for triangle in range(0, len(indices) - 2, 3)
    ]
    sample_step = max(1, stride)
    max_chord = 0.0
    max_normal = 0.0
    sampled = 0
    for triangle in triangles[::sample_step]:
        a, b, c = triangle
        u = [b[index] - a[index] for index in range(3)]
        v = [c[index] - a[index] for index in range(3)]
        normal = [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ]
        length = math.sqrt(sum(item * item for item in normal))
        if length < 1e-12:
            continue
        normal = [item / length for item in normal]
        for point in _sample_points(triangle):
            distance = _surface_distance(run, point)
            if distance is not None:
                max_chord = max(max_chord, distance)
            result = _gradient(run, point)
            if result is not None:
                max_normal = max(max_normal, _normal_deviation(normal, result[1]))
        sampled += 1
    encoded = rd._encode_mesh(positions, indices)
    bytes_used = len(encoded["positions_b64"]) + len(encoded["indices_b64"])
    return {
        "resolution": resolution,
        "vertices": len(positions) // 3,
        "triangles": len(indices) // 3,
        "bytes": bytes_used,
        "max_chord": round(max_chord, 6),
        "max_normal_deg": round(max_normal, 4),
        "sampled_triangles": sampled * sample_step,
        "stride": sample_step,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolutions", default="12,20,28,36,44,52,60,64")
    parser.add_argument("--surfaces", default=",".join(SURFACES))
    parser.add_argument("--json", default="")
    args = parser.parse_args()
    resolutions = [int(item) for item in args.resolutions.split(",") if item.strip()]
    names = [item for item in args.surfaces.split(",") if item in SURFACES]
    rows = []
    for name in names:
        for resolution in resolutions:
            stride = 1 if resolution <= 44 else 2 if resolution <= 60 else 3
            rows.append({"surface": name,
                         **measure(SURFACES[name], resolution, stride)})
    print("| surface | res | vertices | triangles | binary KB | max chord | max normal° |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in rows:
        if "error" in row:
            print(f"| {row['surface']} | {row['resolution']} | - | - | - | - | - |")
            continue
        print(f"| {row['surface']} | {row['resolution']} | {row['vertices']} | "
              f"{row['triangles']} | {row['bytes'] / 1024:.0f} | "
              f"{row['max_chord']:.6f} | {row['max_normal_deg']:.3f} |")
    if args.json:
        target = Path(args.json)
        if not target.is_absolute():
            target = ROOT.parent / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
