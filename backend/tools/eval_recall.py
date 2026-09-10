"""
知识库召回率评测:对每个知识主题的多种问法(同义 / 换词 / 中英 / 口语化)
批量跑检索,输出命中率报告;未命中项用于反哺 keywords 词表。

用法(backend 目录下):
    python tools/eval_recall.py                 # 当前检索模式
    python tools/eval_recall.py --top 5         # 自定义 top-k
    python tools/eval_recall.py --verbose       # 打印每条问法的得分明细

通过标准:top-k 命中片段中,任一 chunk 标题含预期主题词(大小写不敏感)。
闲聊类用例(expect 为空)通过标准:不产生任何知识命中(走会话应答)。

目标:封闭知识库上全部用例命中(100%),新文档入库后重跑本脚本做质检。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402 装载 .env.local(embedding/LLM 配置),与 main.py 同路径
import rag  # noqa: E402

config.load_env()

# (问法, 预期命中标题包含的主题词;空字符串 = 应不命中知识库的闲聊)
CASES: list[tuple[str, str]] = [
    # ---- 函数极限 ----
    ("极限的定义", "函数极限"),
    ("什么是极限", "函数极限"),
    ("极限概念通俗解释", "函数极限"),
    ("definition of limit", "Limits"),
    ("什么是收敛", "函数极限"),
    # ---- 导数 ----
    ("导数的定义", "导数"),
    ("什么是导数", "导数"),
    ("切线斜率怎么理解", "导数"),
    ("what is a derivative", "Derivatives"),
    ("求导是什么意思", "导数"),
    # ---- 泰勒 ----
    ("什么是泰勒展开", "泰勒展开"),
    ("麦克劳林公式", "泰勒展开"),
    ("taylor expansion", "Taylor Expansion"),
    ("泰勒级数是什么", "泰勒展开"),
    ("用多项式逼近函数", "泰勒展开"),
    # ---- 积分 ----
    ("积分的定义", "积分"),
    ("不定积分怎么算", "积分"),
    ("微积分基本定理", "积分"),
    ("what is an integral", "Integrals"),
    ("黎曼和是什么", "积分"),
    # ---- 级数 ----
    ("级数收敛是什么意思", "级数"),
    ("幂级数", "级数"),
    ("series convergence", "Series"),
    ("无穷级数求和", "级数"),
    # ---- 微分方程 ----
    ("微分方程怎么解", "微分方程"),
    ("常微分方程", "微分方程"),
    ("ODE 是什么", "Differential Equations"),
    ("separable equation", "Differential Equations"),
    # ---- 线性代数 ----
    ("矩阵的定义", "线性代数"),
    ("特征值是什么", "线性代数"),
    ("eigenvalues and eigenvectors", "Linear Algebra"),
    ("行列式怎么算", "线性代数"),
    ("对角化是什么意思", "线性代数"),
    # ---- 概率论与数理统计 ----
    ("期望怎么算", "概率论与数理统计"),
    ("正态分布是什么", "概率论与数理统计"),
    ("大数定律", "概率论与数理统计"),
    ("假设检验的步骤", "概率论与数理统计"),
    ("probability distribution", "Probability & Mathematical Statistics"),
    # ---- 数论 ----
    ("数论是什么", "数论"),
    ("素数怎么判断", "数论"),
    ("费马小定理", "数论"),
    ("同余是什么意思", "数论"),
    ("prime number theorem", "Number Theory"),
    # ---- 复变函数 ----
    ("复变函数是什么", "复变函数"),
    ("留数定理", "复变函数"),
    ("residue theorem", "Complex Analysis"),
    ("柯西黎曼条件", "复变函数"),
    # ---- 拓扑学 ----
    ("拓扑学是什么", "拓扑学"),
    ("紧致空间", "拓扑学"),
    ("topology basics", "Topology"),
    ("同胚是什么意思", "拓扑学"),
    # ---- 微分学应用 ----
    ("拉格朗日中值定理", "微分学应用"),
    ("mean value theorem", "Applications of Differentiation"),
    ("曲率公式", "微分学应用"),
    # ---- 傅里叶 ----
    ("傅里叶级数", "傅里叶分析"),
    ("fourier transform", "Fourier Analysis"),
    ("傅里叶展开", "傅里叶分析"),
    # ---- 闲聊(不应命中知识库) ----
    ("你好呀", ""),
    ("今天天气不错", ""),
    ("谢谢", ""),
]


def run_case(query: str, expect: str, top_k: int, verbose: bool) -> tuple[bool, str]:
    hits = rag.search(query, top_k=top_k)
    detail = "; ".join(f"{c.title}[{s:.1f}]" for c, s in hits) or "(无命中)"
    if expect:
        passed = any(expect.lower() in c.title.lower() or expect.lower() in c.title_en.lower()
                     for c, _ in hits)
        return passed, detail
    passed = len(hits) == 0  # 闲聊:不产生知识命中即正确
    return passed, detail


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 规避 Windows GBK 控制台
    ap = argparse.ArgumentParser(description="知识库召回率评测")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--verbose", action="store_true", help="打印每条问法得分明细")
    args = ap.parse_args()

    rag.init()
    total = len(CASES)
    passed = 0
    misses: list[tuple[str, str, str]] = []
    print(f"评测模式:{'向量混合' if rag.embed.is_configured() else '关键词+bigram'} | top-k={args.top} | 用例 {total} 条\n")

    for query, expect in CASES:
        okc, detail = run_case(query, expect, args.top, args.verbose)
        if okc:
            passed += 1
        else:
            misses.append((query, expect, detail))
        if args.verbose or not okc:
            mark = "[OK]" if okc else "[MISS]"
            print(f"  {mark} {query:26s} 期望「{expect or '(会话应答)'}」 → {detail}")

    rate = passed / total * 100
    print(f"\n命中率:{passed}/{total} = {rate:.0f}%")
    if misses:
        print(f"\n未命中 {len(misses)} 条(按此补 keywords):")
        for q, e, d in misses:
            print(f"  - {q} (期望 {e})  实际 → {d}")
    # 报告落盘(UTF-8),便于归档与迭代对比
    report = Path(__file__).resolve().parent / "eval_report.txt"
    lines = [f"mode={'vector' if rag.embed.is_configured() else 'keyword'} top_k={args.top}",
             f"rate={passed}/{total}={rate:.0f}%", ""]
    lines += [f"[{q}] expect={e or 'chat'} -> {d}" for q, e, d in misses]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {report.name}")
    return 0 if not misses else 1


if __name__ == "__main__":
    sys.exit(main())
