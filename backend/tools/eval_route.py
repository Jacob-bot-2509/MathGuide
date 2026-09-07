"""
路由分流评测(P0 执行表):验证「研究型 / 知识直答 / 方法论框架 / 会话应答」
四路分流的判定与 chat.py 实际链路一致。

用法(backend 目录下):
    python tools/eval_route.py            # 全部用例
    python tools/eval_route.py --verbose  # 打印每条判定明细

通过标准:期望路由与实际路由一致;新增/修改分流规则后必须重跑。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chat  # noqa: E402  复用 chat.py 的判定函数,保证与线上链路同源
import rag  # noqa: E402

# (问法, 期望路由)  route ∈ research / knowledge / framework / chat
CASES: list[tuple[str, str]] = [
    # ---- 研究型(应触发深度搜索占位分支) ----
    ("极限理论的最新研究进展", "research"),
    ("泰勒展开的前沿成果", "research"),
    ("有哪些关于黎曼猜想的最新论文", "research"),
    ("微分方程的学术动态", "research"),
    ("概率论研究现状", "research"),
    ("拓扑学文献综述", "research"),
    ("矩阵计算的最新研究", "research"),
    ("recent research on limits", "research"),
    ("state of the art in numerical ODE", "research"),
    ("latest papers on Fourier analysis", "research"),
    # ---- 知识直答(知识库命中) ----
    ("什么是泰勒展开", "knowledge"),
    ("极限的定义", "knowledge"),
    ("导数的几何意义", "knowledge"),
    ("积分怎么算", "knowledge"),
    ("级数收敛", "knowledge"),
    ("微分方程通解", "knowledge"),
    ("矩阵的特征值", "knowledge"),
    ("正态分布", "knowledge"),
    ("留数定理", "knowledge"),
    ("拓扑学是什么", "knowledge"),
    ("傅里叶变换", "knowledge"),
    ("拉格朗日中值定理", "knowledge"),
    ("黎曼和", "knowledge"),
    ("柯西黎曼条件", "knowledge"),
    ("同胚", "knowledge"),
    ("What is Taylor expansion", "knowledge"),
    ("explain limits with intuition", "knowledge"),
    ("线性代数基础", "knowledge"),
    # ---- 方法论框架(确切数学题但知识库未命中) ----
    ("帮我看看这道题怎么做", "framework"),
    ("证明哥德巴赫猜想", "framework"),
    ("这道题怎么解", "framework"),
    # 检索真实命中「证明不等式的标准套路」(中值定理篇)→ 知识直答是正确行为
    ("求证一个不等式", "knowledge"),
    ("solve this problem for me", "framework"),
    ("数学题怎么破", "framework"),
    ("帮我做一下这道例题", "framework"),
    ("求值:sin30 度等于多少", "framework"),
    # ---- 会话应答(非数学问题) ----
    ("你好", "chat"),
    ("谢谢", "chat"),
    ("再见", "chat"),
    ("今天天气不错", "chat"),
    ("你是谁", "chat"),
    ("你会什么", "chat"),
    ("我学不会好难过", "chat"),
    ("Hello! How are you?", "chat"),
    ("请求帮助", "chat"),
    ("好的", "chat"),
    # ---- 边界:研究意图 > 知识命中;知识命中 > 寒暄 ----
    ("泰勒展开的最新研究进展", "research"),
    ("你好,什么是泰勒展开", "knowledge"),
    ("论文里的这道题怎么做", "research"),
    ("帮我写一篇关于极限的综述", "research"),
]


def decide(question: str) -> str:
    """与 chat.py chat_stream 同源的判定顺序(研究 → 知识 → 框架 → 会话)"""
    chunks = rag.search(question, top_k=3)
    if rag.route.is_research_intent(question):
        return "research"
    if chunks:
        return "knowledge"
    if chat._math_re().search(question):
        return "framework"
    return "chat"  # 含 _chitchat_kind 命中与一般陈述(同走会话大脑)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="路由分流评测")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    rag.init()
    total = len(CASES)
    passed = 0
    misses: list[tuple[str, str, str]] = []
    for query, expect in CASES:
        actual = decide(query)
        if actual == expect:
            passed += 1
        else:
            misses.append((query, expect, actual))
        if args.verbose or actual != expect:
            mark = "[OK]" if actual == expect else "[MISS]"
            print(f"  {mark} {query:30s} 期望 {expect:10s} 实际 {actual}")

    rate = passed / total * 100
    print(f"\n路由命中率:{passed}/{total} = {rate:.0f}%")
    if misses:
        print(f"\n未命中 {len(misses)} 条:")
        for q, e, a in misses:
            print(f"  - {q} (期望 {e},实际 {a})")
        return 1
    print("全部分流正确,可以进入 P1。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
