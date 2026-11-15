"""analysis_client:主服务与分析 worker 之间的 JSON 行协议客户端。

此前**完全没有测试**:这个文件 23.9% 是接口层用例顺带导入时蹭到的。
它负责起子进程、超时、崩溃、协议错行的映射 —— 任何一条漏掉,用户看到的都是
"分析失败"而不是可读原因(而且 worker 崩了主服务不能跟着崩)。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import types

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


def test_posix_limits_sets_caps_on_posix_only(monkeypatch):
    """`_posix_limits` 是**子进程**的 preexec_fn,只能改 fork 出来那份地址空间。

    历史上这里直接调 `ac._posix_limits()`,在 Linux 上等于给 pytest 进程本身设
    `RLIMIT_AS=512MB` + `RLIMIT_CPU=30s` —— 硬限制、且不可逆。之后 analysis 三件套
    (numpy/scipy/statsmodels)一导入,地址空间就顶到 512MB 之上,再往后第一个
    `threading.Thread.start()`(典型是 starlette TestClient 的 portal 线程)会因为拿不到
    线程栈在内核里失败:新线程在 `_bootstrap_inner` 早早死掉,永远执行不到 `_started.set()`,
    父线程就卡死在 `start()` 里 —— 这正是 CI Linux 线"Test 步骤无声挂起六小时"的根因。
    Windows 上 `resource` 模块不存在、函数真是 no-op,所以那条线一直是绿的,问题被掩盖了。

    所以这里用假的 resource 模块观察调用,**绝不碰真实 rlimit**。
    """
    if os.name == "posix":
        import resource as real_resource

        before = real_resource.getrlimit(real_resource.RLIMIT_AS)
    else:  # pragma: no cover - Windows 没有 resource 模块
        real_resource = None
        before = None

    calls = []

    def fake_setrlimit(which, limits):
        calls.append((which, limits))

    monkeypatch.setitem(sys.modules, "resource", types.SimpleNamespace(
        RLIMIT_AS="RLIMIT_AS",
        RLIMIT_CPU="RLIMIT_CPU",
        setrlimit=fake_setrlimit,
    ))
    monkeypatch.setattr(os, "name", "posix")

    assert ac._posix_limits() is None
    assert calls == [
        ("RLIMIT_AS", (512 * 1024 * 1024, 512 * 1024 * 1024)),
        ("RLIMIT_CPU", (30, 30)),
    ]

    # 非 posix 平台直接返回,一条都不许调
    monkeypatch.setattr(os, "name", "nt")
    assert ac._posix_limits() is None
    assert len(calls) == 2

    # 真实上限必须原封不动:一旦被改,后面的用例会以"挂起"的形式失败
    if real_resource is not None:
        assert real_resource.getrlimit(real_resource.RLIMIT_AS) == before


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
