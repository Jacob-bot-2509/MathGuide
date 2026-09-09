"""
用量报表:打印测试期调用统计 —— 谁问了多少、回复多少字、各模型角色调用多少次。
数据来源 backend/data/usage.json(每次聊天流结束后由后端落盘)。

用法(backend 目录下):
    python tools/usage.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usage  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 规避 Windows GBK 控制台
    s = usage.summary()
    print("=" * 52)
    print("  MathGuide 用量统计")
    print("=" * 52)
    print(f"总调用 {s['calls']} 次 | 回复总字数 {s['totalChars']}")
    print()
    if s["users"]:
        print(f"{'用户':<20}{'提问数':>8}{'回复字数':>10}")
        print("-" * 38)
        for u in s["users"]:
            label = u.get("phone") or u.get("user") or "访客"
            print(f"{label:<20}{u['calls']:>8}{u['chars']:>10}")
    else:
        print("暂无记录(还没有人提问,或 usage.json 被清空)")
    print()
    if s["roles"]:
        print("按模型角色:")
        for role, n in sorted(s["roles"].items(), key=lambda kv: -kv[1]):
            print(f"  {role:<12}{n:>6} 次")
    return 0


if __name__ == "__main__":
    sys.exit(main())
