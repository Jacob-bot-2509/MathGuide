"""
深度搜索评测(P1 执行表):研究型问题批量跑 deep_search,
验收口径 = 每问 ≥1 条高置信来源(带真实链接或知识库命中)+ 全链 ≤15s。

用法(backend 目录下):
    python tools/eval_search.py            # 网络依赖;离线时外部源自动跳过
    python tools/eval_search.py --verbose

通过线:≥80% 的问题有来源命中(单源失败不影响整体是设计目标);
报告落盘 tools/eval_search_report.txt。
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import rag  # noqa: E402

config.load_env()  # 与后端同一份环境:不加载会跑成"无向量/无 LLM"的另一套配置

CASES = [
    "泰勒展开的最新研究进展",
    "极限理论的学术动态",
    "黎曼猜想的最新论文",
    "微分方程数值解法的研究现状",
    "傅里叶分析的前沿成果",
    "矩阵计算的最新研究",
    "概率论的大数定律文献",
    "拓扑学与数据科学的交叉研究综述",
    "recent papers on taylor series",
    "state of the art in numerical integration",
]

TIMEOUT_LIMIT = rag.research.DEFAULT_TIMEOUT   # 与线上同一条预算线


async def run_one(question: str) -> tuple[str, bool, str]:
    outcome = await rag.research.deep_search(question, top_k=3, timeout=TIMEOUT_LIMIT)
    detail = f"{outcome.elapsed:.1f}s | terms={outcome.terms[:5]} | hits={len(outcome.hits)}"
    if outcome.sources:
        detail += " | " + " ".join(f"{k}:{v}" for k, v in outcome.sources.items())
    if outcome.errors:
        detail += f" | skipped:{','.join(outcome.errors)}"
    ok = outcome.any_hit and outcome.elapsed <= TIMEOUT_LIMIT
    return question, ok, detail


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="深度搜索评测")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    rag.init()
    print(f"深度搜索评测:{len(CASES)} 道研究型问题,全链限时 {TIMEOUT_LIMIT}s\n")

    async def run_all():
        return await asyncio.gather(*(run_one(q) for q in CASES))

    results = asyncio.run(run_all())
    passed = sum(1 for _, ok, _ in results if ok)
    lines = []
    for q, ok, detail in results:
        mark = "[OK]" if ok else "[MISS]"
        lines.append(f"{mark} {q[:34]:36s} {detail}")
        if args.verbose or not ok:
            print(lines[-1])
    rate = passed / len(CASES) * 100
    lines.append(f"\n通过:{passed}/{len(CASES)} = {rate:.0f}%(通过线 80%)")
    print(lines[-1])

    report = Path(__file__).resolve().parent / "eval_search_report.txt"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {report.name}")
    return 0 if rate >= 80 else 1


if __name__ == "__main__":
    sys.exit(main())
