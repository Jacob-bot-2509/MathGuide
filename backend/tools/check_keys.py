"""
LLM Key 快速校验:读取 backend/.env.local,逐平台实测鉴权。

用法(backend 目录下):
    python tools/check_keys.py

只显示校验结论,绝不打印 key 内容;全部角色可用时退出码 0。
"""
import os
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import httpx  # noqa: E402

config.load_env()


def check(name: str, base: str, key: str, model: str) -> bool:
    print(f"[{name}] ", end="", flush=True)
    if not key:
        print("未配置(空)")
        return False
    if not base:
        print("未配置平台地址")
        return False
    try:
        r = httpx.post(
            base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"网络失败:{type(exc).__name__} {str(exc)[:60]}")
        return False
    if r.status_code == 200:
        print(f"有效 ✓({model} 可用)")
        return True
    try:
        msg = r.json().get("error", {}).get("message", "") or r.text
    except ValueError:
        msg = r.text
    print(f"无效 ✗ HTTP {r.status_code} 平台回复:{str(msg)[:100]}")
    return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 52)
    print("  LLM Key 校验(不打印 key 内容)")
    print("=" * 52)
    # 按当前角色配置逐项校验:平台 key 有效不等于具体模型已开通
    import rag.llm as llm

    platforms = {
        "aliyun": ("MG_ALIYUN_BASE_URL", "MG_ALIYUN_API_KEY", ""),
        "zhipu": ("MG_ZHIPU_BASE_URL", "MG_ZHIPU_API_KEY", ""),
        "deepseek": ("MG_DEEPSEEK_BASE_URL", "MG_DEEPSEEK_API_KEY",
                     "https://api.deepseek.com/v1"),
    }
    roles = llm._roles()
    results: list[bool] = []
    seen: set[tuple[str, str]] = set()
    for role in ("main", "backup", "deep", "long"):
        provider, _, model = roles.get(role, "").partition(":")
        if provider not in platforms or not model:
            print(f"[{role}] 未配置或平台未知: {roles.get(role, '')}")
            results.append(False)
            continue
        if (provider, model) in seen:
            continue
        seen.add((provider, model))
        base_env, key_env, default_base = platforms[provider]
        base = os.getenv(base_env, default_base)
        key = os.getenv(key_env, "")
        results.append(check(f"{role} · {provider}", base, key, model))
    print("=" * 52)
    if results and all(results):
        print("所有角色的 key 与模型均可用,可以进入真机验证。")
        return 0
    print("仍有不可用角色:请检查控制台模型开通状态,或调整 MG_ROLE_*。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
