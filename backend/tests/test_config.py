"""config.py:演示模式部署守卫(公网绑定/公网 CORS 直接拒绝)。"""
from __future__ import annotations

import pytest

import config


def _clear_env(monkeypatch):
    for key in ("MG_DEMO_MODE", "MG_HOST", "UVICORN_HOST", "MG_CORS_ORIGINS"):
        monkeypatch.delenv(key, raising=False)


def test_demo_mode_defaults_on_and_can_be_disabled(monkeypatch):
    _clear_env(monkeypatch)
    assert config.demo_mode() is True
    monkeypatch.setenv("MG_DEMO_MODE", "off")
    assert config.demo_mode() is False


def test_demo_mode_allows_loopback(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    config.assert_safe_demo_mode(["--host", "127.0.0.1"])
    config.assert_safe_demo_mode(["--host", "localhost"])
    config.assert_safe_demo_mode(["--host", "::1"])


def test_demo_mode_rejects_public_bind(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    with pytest.raises(RuntimeError, match="只允许本机"):
        config.assert_safe_demo_mode(["--host", "0.0.0.0"])
    with pytest.raises(RuntimeError, match="只允许本机"):
        config.assert_safe_demo_mode(["--host=192.168.1.10"])


def test_demo_mode_rejects_public_env_host(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setenv("MG_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="只允许本机"):
        config.assert_safe_demo_mode([])


def test_demo_mode_rejects_public_cors_origin(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setenv("MG_CORS_ORIGINS", "http://localhost:5173,https://mg.example.com")
    with pytest.raises(RuntimeError, match="CORS"):
        config.assert_safe_demo_mode(["--host", "127.0.0.1"])


def test_demo_mode_rejects_wildcard_cors(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "1")
    monkeypatch.setenv("MG_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="不能为"):
        config.assert_safe_demo_mode(["--host", "127.0.0.1"])


def test_production_mode_allows_public_bind(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("MG_DEMO_MODE", "0")
    config.assert_safe_demo_mode(["--host", "0.0.0.0"])
