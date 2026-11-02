"""图解运行指标:只记阶段、原因、耗时、点数;不记用户身份、问题或回答正文。"""
from __future__ import annotations

import threading
from collections import Counter

_lock = threading.Lock()
_counts: Counter[str] = Counter()
_plan_count = 0
_plan_failures = 0
_total_ms = 0
_total_points = 0


def record(kind: str, ok: bool = True, reason: str = "",
           duration_ms: int = 0, points: int = 0) -> None:
    global _plan_count, _plan_failures, _total_ms, _total_points
    key = f"{kind}:{'ok' if ok else 'fail'}:{reason or 'none'}"
    with _lock:
        _counts[key] += 1
        if kind == "plan":
            _plan_count += 1
            if not ok:
                _plan_failures += 1
            _total_ms += max(0, duration_ms)
            _total_points += max(0, points)
    print(f"[diagram] {key} ms={max(0, duration_ms)} points={max(0, points)}")


def snapshot() -> dict:
    with _lock:
        return {
            "counts": dict(_counts),
            "planCount": _plan_count,
            "planFailures": _plan_failures,
            "avgPlanMs": round(_total_ms / _plan_count, 1) if _plan_count else 0,
            "totalPoints": _total_points,
        }


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def prometheus() -> str:
    """Prometheus 文本格式;交给外部抓取,不引入厂商依赖。"""
    with _lock:
        counts = dict(_counts)
        plan_count = _plan_count
        plan_failures = _plan_failures
        avg_ms = round(_total_ms / plan_count, 1) if plan_count else 0
        points = _total_points
    lines = [
        "# HELP mg_diagram_events_total Diagram events by stage/result/reason.",
        "# TYPE mg_diagram_events_total counter",
    ]
    for key, count in sorted(counts.items()):
        parts = key.split(":")
        kind = parts[0] if parts else "unknown"
        result = parts[1] if len(parts) > 1 else "unknown"
        reason = ":".join(parts[2:]) if len(parts) > 2 else "none"
        lines.append(
            f'mg_diagram_events_total{{kind="{_escape(kind)}",'
            f'result="{_escape(result)}",reason="{_escape(reason)}"}} {count}')
    lines.extend([
        "# TYPE mg_diagram_plan_total gauge",
        f"mg_diagram_plan_total {plan_count}",
        "# TYPE mg_diagram_plan_failures_total gauge",
        f"mg_diagram_plan_failures_total {plan_failures}",
        "# TYPE mg_diagram_plan_duration_ms_avg gauge",
        f"mg_diagram_plan_duration_ms_avg {avg_ms}",
        "# TYPE mg_diagram_points_total gauge",
        f"mg_diagram_points_total {points}",
    ])
    return "\n".join(lines) + "\n"


def reset() -> None:
    global _plan_count, _plan_failures, _total_ms, _total_points
    with _lock:
        _counts.clear()
        _plan_count = 0
        _plan_failures = 0
        _total_ms = 0
        _total_points = 0
