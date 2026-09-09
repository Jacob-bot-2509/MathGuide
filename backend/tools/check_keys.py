"""
LLM Key 快速校验:读取 backend/.env.local,逐平台实测鉴权。

用法(backend 目录下):
    python tools/check_keys.py

只显示校验结论,绝不打印 key 内容;两把都通过时退出码 0。
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
    ok1 = check("阿里云百炼", os.getenv("MG_ALIYUN_BASE_URL", ""),
                os.getenv("MG_ALIYUN_API_KEY", ""), "qwen3.8-flash")
    ok2 = check("智谱开放平台", os.getenv("MG_ZHIPU_BASE_URL", ""),
                os.getenv("MG_ZHIPU_API_KEY", ""), "glm-5.2")
    print("=" * 52)
    if ok1 and ok2:
        print("两把 key 均有效,可以进入真机验证。")
        return 0
    print("仍有无效 key:请回到对应平台控制台重新完整复制(见上一条说明)。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
