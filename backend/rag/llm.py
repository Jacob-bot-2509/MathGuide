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
import time
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


def pick(role: str) -> str:
    """按需路由:请求的角色已配置则用之,否则回退 main(链路永不断)"""
    return role if resolve(role) is not None else "main"


async def _stream_once(base: str, key: str, model: str, system: str, user: str,
                       history: list[dict] | None = None,
                       max_tokens: int | None = None,
                       first_token_secs: float = 20.0) -> AsyncIterator[str]:
    messages: list[dict] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user})
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    # trust_env=False 强制直连:阿里云/智谱 API 国内直连可达,走系统代理
    # (Clash 类工具)反而被中间人证书拦截(实测 SSL CERTIFICATE_VERIFY_FAILED);
    # 检索源则相反,外网源必须经代理,两处策略不同是有意的
    # 超时分段给:connect 快失败,read 限 30s —— 阿里云慢速期首字实测 70s+,
    # 保活空帧会不断重置单值超时导致永不切换;read 超时后 stream_chat
    # 自动切 backup(智谱,异平台容灾),用户最多等 ~35s 就换路,绝不干等
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        trust_env=False,
    ) as client:
        async with client.stream("POST", f"{base.rstrip('/')}/chat/completions",
                                 json=payload, headers=headers) as resp:
            resp.raise_for_status()
            # 首字超时看门狗:慢速期网关会发保活空帧,httpx 的 read 超时被不断
            # 重置形同虚设;这里按"首个正文 delta 的到达时间"硬限时,超时抛
            # TimeoutError,由 stream_chat 切换到 backup(异平台容灾)。
            # 正文开始后不再限时(长答案的帧间隙不受影响)
            started = time.monotonic()
            got_content = False
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
                    got_content = True
                    yield delta
                elif not got_content and time.monotonic() - started > first_token_secs:
                    raise TimeoutError(
                        f"首字超时 {first_token_secs}s(慢速期保活帧撑过 read 超时),切换 backup")


async def stream_chat(system: str, user: str, role: str = "main",
                      fallback: bool = True,
                      history: list[dict] | None = None,
                      max_tokens: int | None = None) -> AsyncIterator[str]:
    """流式对话;role 失败且 fallback 时自动切 backup(异平台容灾)。
    history:最近几轮对话 [{role, content}](调用方已校验/截断);
    max_tokens:约束输出长度(短任务转写/复核用,更快收尾)"""
    spec = resolve(role)
    if spec is None:
        raise RuntimeError(f"LLM 角色 {role} 未配置")
    # 首字上限:fast 角色给 20s(正常 <2s,慢速期实测 70s+);
    # deep/long 有思考阶段(期间只出 reasoning 帧、无 content delta),给 120s 防误伤
    ttft = 120.0 if role in ("deep", "long") else 20.0
    try:
        async for delta in _stream_once(*spec, system, user, history, max_tokens, ttft):
            yield delta
        return
    except Exception:
        if not fallback or role == "backup":
            raise
        backup = resolve("backup")
        if backup is None:
            raise
        print(f"[llm] {role} 调用失败,切换到 backup")
        async for delta in _stream_once(*backup, system, user, history, max_tokens, ttft):
            yield delta
