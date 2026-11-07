"""主服务到 analysis worker 的 JSON 行协议客户端。"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path


class AnalysisError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def analysis_python() -> str:
    configured = os.getenv("MG_ANALYSIS_PYTHON", "").strip()
    if configured:
        return configured
    root = Path(__file__).resolve().parent
    windows = root / ".venv-analysis" / "Scripts" / "python.exe"
    posix = root / ".venv-analysis" / "bin" / "python"
    if windows.exists():
        return str(windows)
    if posix.exists():
        return str(posix)
    return "python"


async def run_analysis(payload: dict, timeout: float = 30.0) -> dict:
    worker = Path(__file__).resolve().with_name("analysis_worker.py")
    request = {
        "id": secrets.token_hex(8),
        "op": "regression",
        "payload": payload,
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            analysis_python(), str(worker),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).resolve().parent),
        )
    except OSError as exc:
        raise AnalysisError("unavailable", "analysis worker not installed") from exc
    try:
        out, err = await asyncio.wait_for(
            proc.communicate((json.dumps(request, ensure_ascii=False) + "\n").encode()),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise AnalysisError("unavailable", "analysis timeout") from exc
    if proc.returncode != 0:
        detail = (err or b"").decode("utf-8", "replace")[-300:]
        raise AnalysisError("unavailable", detail or "analysis worker failed")
    lines = [line for line in (out or b"").decode("utf-8", "replace").splitlines()
             if line.strip()]
    if not lines:
        raise AnalysisError("unavailable", "analysis worker returned no result")
    try:
        response = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise AnalysisError("unavailable", "invalid analysis response") from exc
    if not response.get("ok"):
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        raise AnalysisError(
            str(error.get("code") or "analysis_failed"),
            str(error.get("message") or "analysis failed"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise AnalysisError("unavailable", "analysis result is not an object")
    return result
