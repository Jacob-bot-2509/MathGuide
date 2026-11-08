"""LLM 平台配置:DeepSeek 作为可选供应商(OpenAI 兼容)。"""
from __future__ import annotations

import rag.llm as llm


def test_deepseek_provider_resolves(monkeypatch):
    monkeypatch.setenv("MG_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("MG_DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("MG_ROLE_MAIN", "deepseek:deepseek-chat")
    assert llm.resolve("main") == (
        "https://api.deepseek.com/v1", "test-key", "deepseek-chat")


def test_deepseek_without_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("MG_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.delenv("MG_DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MG_ROLE_MAIN", "deepseek:deepseek-chat")
    assert llm.resolve("main") is None


def test_deepseek_default_base_url(monkeypatch):
    """只配 key 时用默认官方地址,避免必须手写 base。"""
    monkeypatch.delenv("MG_DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.setenv("MG_DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("MG_ROLE_MAIN", "deepseek:deepseek-chat")
    assert llm.resolve("main") == (
        "https://api.deepseek.com/v1", "test-key", "deepseek-chat")
