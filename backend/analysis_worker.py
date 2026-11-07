"""独立分析 worker:只接受结构化请求,不执行用户代码或网络操作。"""
from __future__ import annotations

import json
import sys
from typing import Any


def _error(request_id: str, code: str, message: str) -> dict:
    return {
        "id": request_id,
        "ok": False,
        "error": {"code": code, "message": message[:500]},
    }


def handle_request(request: Any) -> dict:
    if not isinstance(request, dict):
        return _error("", "bad_request", "request must be an object")
    request_id = request.get("id")
    if not isinstance(request_id, str) or not request_id.strip():
        return _error("", "bad_request", "missing id")
    op = request.get("op")
    if op == "ping":
        return {"id": request_id, "ok": True, "result": {"pong": True}}
    if op == "regression":
        from analysis_regression import fit_regression

        payload = request.get("payload") or {}
        try:
            result = fit_regression(
                payload.get("columns") or [],
                payload.get("rows") or [],
                payload.get("formulas") or {},
                payload.get("spec") or {},
            )
        except ValueError as exc:
            return _error(request_id, str(exc), "regression rejected")
        return {"id": request_id, "ok": True, "result": result}
    return _error(request_id, "unsupported_op", f"unsupported op: {op}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error("", "bad_request", "invalid json")
        else:
            try:
                response = handle_request(request)
            except Exception as exc:  # noqa: BLE001 单次请求失败不能杀掉 worker
                response = _error(
                    str(request.get("id") or "") if isinstance(request, dict) else "",
                    "internal_error", type(exc).__name__)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
