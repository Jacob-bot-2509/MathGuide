"""config.assert_single_worker:多 worker 必须"起不来",而不是"日志里提一句"。

背景:限流额度、会话缓存、检索缓存全是进程内存。多 worker 下额度会变成 N 倍,
登出/吊销只在一个进程生效 —— 这类问题在评测期最难查(用户说"我明明被限流了"),
所以宁可启动失败。
"""
from __future__ import annotations

import pytest

import config


def test_single_worker_starts(monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    config.assert_single_worker([])  # 不抛


def test_web_concurrency_above_one_is_refused(monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(RuntimeError) as excinfo:
        config.assert_single_worker([])
    message = str(excinfo.value)
    assert "4 个 worker" in message
    assert "单进程" in message


def test_workers_flag_is_refused_but_one_is_fine(monkeypatch):
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with pytest.raises(RuntimeError):
        config.assert_single_worker(["--workers", "2"])
    with pytest.raises(RuntimeError):
        config.assert_single_worker(["--workers=3"])
    config.assert_single_worker(["--workers", "1"])


def test_demo_mode_only_warns_so_local_dev_still_starts(monkeypatch):
    """本机反复起停不该被拦:演示模式保持"提示"语义,公网才硬拒。"""
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    warnings: list[str] = []

    class _Recorder:
        def info(self, message):
            pass

        def warning(self, message):
            warnings.append(message)

    monkeypatch.setattr(config, "log", _Recorder())
    config.assert_single_worker([])  # 不抛
    assert warnings and "3 个 worker" in warnings[0]
    assert "演示模式" in warnings[0]


def test_main_imports_cleanly_with_default_env(monkeypatch):
    """main.py 在导入期就校验 worker:默认环境(单 worker)必须能导入。"""
    import importlib

    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    module = importlib.import_module("main")
    assert module.app is not None
