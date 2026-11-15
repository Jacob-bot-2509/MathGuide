"""tools/check_llm.py:连通性与容灾的两类判定必须能离线验证。

部署项 2.5 的价值全在「备胎真的接管」这一条上:如果脚本自己判错了,现场反而更敢赌。
所以这里用假流把三条路径都钉住 —— 打坏后切到异平台(通过)、同平台重试(失败)、
备胎也没接住(失败)。
"""
from __future__ import annotations

import asyncio
import os

from rag import llm
from tools import check_llm


def test_provider_key_env_known_and_unknown():
    assert check_llm.provider_key_env("aliyun") == "MG_ALIYUN_API_KEY"
    assert check_llm.provider_key_env("Zhipu") == "MG_ZHIPU_API_KEY"
    # 新加平台时不必改表:约定就是 MG_<PROVIDER>_API_KEY
    assert check_llm.provider_key_env("moonshot") == "MG_MOONSHOT_API_KEY"


def test_host_of_drops_path_and_key():
    assert check_llm.host_of("https://dashscope.aliyuncs.com/compatible-mode/v1") == \
        "dashscope.aliyuncs.com"
    assert check_llm.host_of("not-a-url") == "not-a-url"


def test_provider_of_role_spec():
    assert check_llm.provider_of("aliyun:qwen3.8-flash") == "aliyun"
    assert check_llm.provider_of("") == ""


def test_host_hint_classifies_failure_kinds():
    assert "白名单" in check_llm.host_hint(RuntimeError("401 Unauthorized"))
    assert "限流" in check_llm.host_hint(RuntimeError("429 rate limit exceeded"))
    assert "直连" in check_llm.host_hint(TimeoutError("connect timeout"))
    assert "MG_ROLE_" in check_llm.host_hint(ValueError("something else"))


def test_probe_role_skips_unconfigured(monkeypatch):
    monkeypatch.setattr(llm, "resolve", lambda role="main": None)
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:qwen3.8-flash")
    result = asyncio.run(check_llm.probe_role("main", timeout=5))
    assert result["status"] == "skip"
    assert "未配置" in result["detail"]


def test_probe_role_ok_reports_ttft(monkeypatch):
    monkeypatch.setattr(llm, "resolve", lambda role="main": ("https://x.example/v1", "k", "m1"))

    async def fake_stream(system, user, role="main", **kwargs):
        yield "在"
        yield "线"

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    result = asyncio.run(check_llm.probe_role("main", timeout=5))
    assert result["status"] == "ok"
    assert result["chars"] == 2
    assert result["host"] == "x.example"
    assert result["ttft"] is not None and result["ttft"] >= 0


def test_probe_role_reports_error_with_hint(monkeypatch):
    monkeypatch.setattr(llm, "resolve", lambda role="main": ("https://x.example/v1", "k", "m1"))

    async def boom(*args, **kwargs):
        raise RuntimeError("401 invalid api key")
        yield  # pragma: no cover 让它成为异步生成器

    monkeypatch.setattr(llm, "stream_chat", boom)
    result = asyncio.run(check_llm.probe_role("main", timeout=5))
    assert result["status"] == "fail"
    assert "白名单" in result["hint"]


def test_probe_role_flags_empty_body(monkeypatch):
    monkeypatch.setattr(llm, "resolve", lambda role="main": ("https://x.example/v1", "k", "m1"))

    async def only_think(system, user, role="main", **kwargs):
        return
        yield  # pragma: no cover

    monkeypatch.setattr(llm, "stream_chat", only_think)
    result = asyncio.run(check_llm.probe_role("main", timeout=5))
    assert result["status"] == "fail"
    assert "没出正文" in result["detail"]


def _fake_stream_once(fail_models: set[str]):
    """造一个 `_stream_once` 替身:命中 fail_models 的抛 401,其它正常出字。"""

    async def fake(base, key, model, system, user, history=None, max_tokens=None,
                   first_token_secs=20.0, thinking=True, temperature=None):
        if model in fail_models:
            raise RuntimeError(f"401 invalid api key for {model}")
        yield "在线"

    return fake


def _two_platforms(monkeypatch):
    specs = {
        "main": ("https://a.example/v1", "k", "model-a"),
        "backup": ("https://b.example/v1", "k", "model-b"),
    }
    monkeypatch.setattr(llm, "resolve", lambda role="main": specs.get(role))
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:model-a")
    monkeypatch.setenv("MG_ALIYUN_API_KEY", "real-key")


def test_failover_passes_when_backup_takes_over(monkeypatch):
    _two_platforms(monkeypatch)
    monkeypatch.setattr(llm, "_stream_once", _fake_stream_once({"model-a"}))
    result = asyncio.run(check_llm.probe_failover(timeout=5))
    assert result["status"] == "ok"
    assert "model-a" in result["detail"] and "model-b" in result["detail"]
    assert "接管" in result["detail"]
    # 现场最需要的一条:临时改写的 key 必须还原,否则后续检查全错
    assert os.environ["MG_ALIYUN_API_KEY"] == "real-key"


def test_failover_fails_when_retry_same_platform(monkeypatch):
    specs = {
        "main": ("https://a.example/v1", "k", "model-a"),
        "backup": ("https://a.example/v1", "k", "model-a"),  # 同平台同模型:不算容灾
    }
    monkeypatch.setattr(llm, "resolve", lambda role="main": specs.get(role))
    monkeypatch.setenv("MG_ROLE_MAIN", "aliyun:model-a")
    calls = {"n": 0}

    async def flaky(base, key, model, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # 第一次失败(主用被我们打坏),第二次"重试成功"
            raise RuntimeError("401 invalid api key")
        yield "在线"

    monkeypatch.setattr(llm, "_stream_once", flaky)
    result = asyncio.run(check_llm.probe_failover(timeout=5))
    assert result["status"] == "fail"
    assert "另一个平台" in result["hint"]


def test_failover_fails_when_backup_also_broken(monkeypatch):
    _two_platforms(monkeypatch)
    monkeypatch.setattr(llm, "_stream_once", _fake_stream_once({"model-a", "model-b"}))
    result = asyncio.run(check_llm.probe_failover(timeout=5))
    assert result["status"] == "fail"
    assert "备胎没接住" in result["detail"]


def test_failover_skips_without_two_platforms(monkeypatch):
    monkeypatch.setattr(llm, "resolve",
                        lambda role="main": ("https://a.example/v1", "k", "m") if role == "main" else None)
    result = asyncio.run(check_llm.probe_failover(timeout=5))
    assert result["status"] == "skip"
