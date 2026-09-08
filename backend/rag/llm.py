"""
LLM 客户端(OpenAI 兼容流式,多平台 + 多角色 + 容灾切换)。

配置(backend/.env.local,由 config.load_env 装载;见 .env.local.example):
    平台:MG_ALIYUN_BASE_URL/API_KEY、MG_ZHIPU_BASE_URL/API_KEY
    角色:MG_ROLE_MAIN / MG_ROLE_BACKUP / MG_ROLE_DEEP / MG_ROLE_LONG
          取值 "平台:模型名",如 aliyun:qwen3.8-flash、zhipu:glm-5.2

角色语义:
    main   日常问答 / 查询改写 / 精排 / 综合(便宜快模型)
    backup 异平台备胎:main 调用失败自动切换(多厂商容灾)
    deep   深答路由:证明 / 竞赛 / 复杂综合(强模型)
    long   长文档分析(长上下文模型)

stream_chat(system, user, role='main', fallback=True):
    fallback=True 时 main 失败自动重试 backup(跨平台),仍失败抛异常由调用方降级。
"""
import json
import os
from typing import AsyncIterator

import httpx

def _providers() -> dict:
    """惰性读取平台配置(config.load_env 在 main 启动时执行,晚于模块导入)"""
    return {
        "aliyun": {
            "base": os.getenv("MG_ALIYUN_BASE_URL", ""),
            "key": os.getenv("MG_ALIYUN_API_KEY", ""),
        },
        "zhipu": {
            "base": os.getenv("MG_ZHIPU_BASE_URL", ""),
            "key": os.getenv("MG_ZHIPU_API_KEY", ""),
        },
    }


def _roles() -> dict:
    return {
        "main": os.getenv("MG_ROLE_MAIN", "aliyun:qwen3.8-flash"),
        "backup": os.getenv("MG_ROLE_BACKUP", "zhipu:glm-5.2"),
        "deep": os.getenv("MG_ROLE_DEEP", "aliyun:qwen3-235b-a22b"),
        "long": os.getenv("MG_ROLE_LONG", "aliyun:qwen-long"),
    }


def resolve(role: str = "main") -> tuple[str, str, str] | None:
    """角色 → (base_url, api_key, model);未配置该平台则 None"""
    spec = _roles().get(role, "")
    if ":" not in spec:
        return None
    provider, _, model = spec.partition(":")
    cfg = _providers().get(provider, {})
    base, key = cfg.get("base", ""), cfg.get("key", "")
    if not (base and key and model):
        return None
    return base, key, model


def is_configured(role: str = "main") -> bool:
    return resolve(role) is not None


async def _stream_once(base: str, key: str, model: str,
                       system: str, user: str) -> AsyncIterator[str]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", f"{base.rstrip('/')}/chat/completions",
                                 json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


async def stream_chat(system: str, user: str, role: str = "main",
                      fallback: bool = True) -> AsyncIterator[str]:
    """流式对话;role 失败且 fallback 时自动切 backup(异平台容灾)"""
    spec = resolve(role)
    if spec is None:
        raise RuntimeError(f"LLM 角色 {role} 未配置")
    try:
        async for delta in _stream_once(*spec, system, user):
            yield delta
        return
    except Exception:
        if not fallback or role == "backup":
            raise
        backup = resolve("backup")
        if backup is None:
            raise
        print(f"[llm] {role} 调用失败,切换到 backup")
        async for delta in _stream_once(*backup, system, user):
            yield delta
