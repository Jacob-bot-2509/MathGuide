"""
LLM 客户端(OpenAI 兼容流式接口)。

配置方式(环境变量,均可不设):
    MG_LLM_BASE_URL   接口地址,如 https://api.deepseek.com/v1 / https://api.openai.com/v1
    MG_LLM_API_KEY    API Key
    MG_LLM_MODEL      模型名,默认 gpt-4o-mini

未配置 API Key 时 is_configured() 返回 False,chat 层自动降级为「知识库直答」模式
(仅返回检索到的知识片段),全链路仍可运行;配置后无需改代码即接入真实模型。
"""
import json
import os
from typing import AsyncIterator

import httpx

BASE_URL = os.getenv("MG_LLM_BASE_URL", "")
API_KEY = os.getenv("MG_LLM_API_KEY", "")
MODEL = os.getenv("MG_LLM_MODEL", "gpt-4o-mini")


def is_configured() -> bool:
    return bool(BASE_URL and API_KEY)


async def stream_chat(system: str, user: str) -> AsyncIterator[str]:
    """流式对话:逐段产出模型文本增量(不含 SSE 帧包装,由 chat.py 统一包装)"""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": True,
    }
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", f"{BASE_URL.rstrip('/')}/chat/completions", json=payload, headers=headers) as resp:
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
