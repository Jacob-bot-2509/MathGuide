"""analysis_client:主服务与分析 worker 之间的 JSON 行协议客户端。

此前**完全没有测试**:这个文件 23.9% 是接口层用例顺带导入时蹭到的。
它负责起子进程、超时、崩溃、协议错行的映射 —— 任何一条漏掉,用户看到的都是
"分析失败"而不是可读原因(而且 worker 崩了主服务不能跟着崩)。
"""
from __future__ import annotations

import asyncio
import json

import pytest

import analysis_client as ac


class FakeProc:
    def __init__(self, out: bytes = b"", err: bytes = b"", returncode: int = 0):
        self.out = out
        self.err = err
        self.returncode = returncode
        self.killed = False
        self.payload = None

    async def communicate(self, payload=None):
        self.payload = payload
        return self.out, self.err

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


def _patch_spawn(monkeypatch, proc):
    async def fake_spawn(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)
    return proc


def _reply(**payload) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode()


# ---------- 子进程可用性 ----------

def test_analysis_python_prefers_env(monkeypatch):
    monkeypatch.setenv("MG_ANALYSIS_PYTHON", "D:/py/python.exe")
    assert ac.analysis_python() == "D:/py/python.exe"


def test_analysis_python_uses_bundled_venv_when_present(tmp_path, monkeypatch):
    monkeypatch.delenv("MG_ANALYSIS_PYTHON", raising=False)
    fake_module = tmp_path / "analysis_client.py"
    fake_module.write_text("", encoding="utf-8")
    win_python = tmp_path / ".venv-analysis" / "Scripts" / "python.exe"
    win_python.parent.mkdir(parents=True)
    win_python.write_text("", encoding="utf-8")
    monkeypatch.setattr(ac, "__file__", str(fake_module))

    assert ac.analysis_python() == str(win_python)


def test_analysis_python_falls_back_to_path_python(tmp_path, monkeypatch):
    monkeypatch.delenv("MG_ANALYSIS_PYTHON", raising=False)
    fake_module = tmp_path / "analysis_client.py"
    fake_module.write_text("", encoding="utf-8")
    monkeypatch.setattr(ac, "__file__", str(fake_module))

    assert ac.analysis_python() == "python"


def test_posix_limits_is_noop_on_windows():
    # 非 posix 平台直接返回;posix 上才设 rlimit
    assert ac._posix_limits() is None


# ---------- 协议正常路径 ----------

def test_run_worker_sends_request_and_returns_result(monkeypatch):
    proc = _patch_spawn(monkeypatch, FakeProc(_reply(id="x", ok=True, result={"n": 3})))

    result = asyncio.run(ac._run_worker("regression", {"a": 1}))

    assert result == {"n": 3}
    request = json.loads(proc.payload.decode())
    assert request["op"] == "regression"
    assert request["payload"] == {"a": 1}
    assert request["id"]


def test_run_analysis_and_capabilities_use_their_ops(monkeypatch):
    seen = []
    proc = FakeProc(_reply(id="x", ok=True, result={"ok": 1}))

    async def fake_spawn(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    asyncio.run(ac.run_analysis({"payload": 1}))
    seen.append(json.loads(proc.payload.decode())["op"])
    asyncio.run(ac.run_capabilities())
    seen.append(json.loads(proc.payload.decode())["op"])

    assert seen == ["regression", "capabilities"]


# ---------- 失败路径:每条都要映射成可读的 unavailable ----------

def test_spawn_failure_means_worker_not_installed(monkeypatch):
    async def fake_spawn(*_args, **_kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_spawn)

    with pytest.raises(ac.AnalysisError) as excinfo:
        asyncio.run(ac._run_worker("ping", {}))
    assert excinfo.value.code == "unavailable"
    assert "not installed" in excinfo.value.message


def test_timeout_kills_worker(monkeypatch):
    proc = _patch_spawn(monkeypatch, FakeProc())

    async def fake_wait_for(_awaitable, timeout=None):
        raise asyncio.TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(ac.AnalysisError, match="timeout"):
        asyncio.run(ac._run_worker("ping", {}))
    assert proc.killed is True


def test_cancellation_propagates_after_killing_worker(monkeypatch):
    proc = _patch_spawn(monkeypatch, FakeProc())

    async def fake_wait_for(_awaitable, timeout=None):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ac._run_worker("ping", {}))
    assert proc.killed is True


def test_nonzero_exit_reports_stderr_tail(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(err=b"Traceback: boom", returncode=2))

    with pytest.raises(ac.AnalysisError) as excinfo:
        asyncio.run(ac._run_worker("ping", {}))
    assert "Traceback: boom" in excinfo.value.message


def test_empty_output_is_reported(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(out=b"\n\n"))

    with pytest.raises(ac.AnalysisError, match="no result"):
        asyncio.run(ac._run_worker("ping", {}))


def test_invalid_json_output_is_reported(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(out=b"not-json\n"))

    with pytest.raises(ac.AnalysisError, match="invalid analysis response"):
        asyncio.run(ac._run_worker("ping", {}))


def test_error_envelope_becomes_analysis_error(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(
        out=_reply(id="x", ok=False, error={"code": "singular", "message": "退化"})))

    with pytest.raises(ac.AnalysisError) as excinfo:
        asyncio.run(ac._run_worker("regression", {}))
    assert excinfo.value.code == "singular"
    assert excinfo.value.message == "退化"


def test_error_envelope_without_details_uses_defaults(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(out=_reply(id="x", ok=False)))

    with pytest.raises(ac.AnalysisError) as excinfo:
        asyncio.run(ac._run_worker("regression", {}))
    assert excinfo.value.code == "analysis_failed"


def test_non_object_result_is_rejected(monkeypatch):
    _patch_spawn(monkeypatch, FakeProc(out=_reply(id="x", ok=True, result=[1, 2])))

    with pytest.raises(ac.AnalysisError, match="not an object"):
        asyncio.run(ac._run_worker("regression", {}))
