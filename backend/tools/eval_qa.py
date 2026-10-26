"""正确率 / 幻觉率 / 检索命中 评测入口。

用法(backend 目录下):
    # 只测检索(不调 LLM,快)
    python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage retrieval

    # 完整评测:生产链路回答 + 评审
    python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage all --limit 10

    # 只跑回答,不评审(省钱,自己看输出)
    python tools/eval_qa.py --data evaluation/data/sample.jsonl --stage answer --no-judge

输出目录(默认 reports/eval_<时间>):
    records.jsonl   每条样本的检索、回答、判分
    summary.json    聚合指标 + 配置 + 数据集指纹
    report.md       人读报告
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import rag  # noqa: E402
from evaluation import metrics, report, runner  # noqa: E402
from evaluation.datasets import dataset_hash, load_items  # noqa: E402


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="MathGuide 正确率/幻觉率评测")
    ap.add_argument("--data", required=True, help="JSONL 评测集路径")
    ap.add_argument("--out", default="", help="输出目录(默认 reports/eval_<时间>)")
    ap.add_argument("--stage", choices=("retrieval", "answer", "all"), default="all")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条(0=全部)")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--judge-role", default="backup",
                    help="评审模型角色:backup/deep/main(默认 backup,与生成模型异源)")
    ap.add_argument("--no-judge", action="store_true", help="只生成不评审")
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--include-research", action="store_true",
                    help="允许研究型问题(会访问外部检索源,默认跳过)")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args()


def _print_summary(summary: dict) -> None:
    ans = summary.get("answers") or {}
    ret = summary.get("retrieval") or {}
    una = summary.get("unanswerable") or {}
    claim = ans.get("claim_hallucination") or {}

    def rate(block, key="rate"):
        v = (block or {}).get(key)
        return "—" if v is None else f"{v:.3f}"

    print("\n== 评测结果 ==")
    print(f"样本数: {summary.get('n_items')}")
    print(f"正确率: {rate(ans.get('accuracy'))} "
          f"(n={ (ans.get('accuracy') or {}).get('n') })")
    print(f"答案级幻觉率: {rate(ans.get('answer_hallucination'))} "
          f"(n={ (ans.get('answer_hallucination') or {}).get('n') })")
    print(f"断言级幻觉率: {rate(claim)} "
          f"({claim.get('bad_claims', 0)}/{claim.get('total_claims', 0)})")
    print(f"不可答编造率: {rate(una.get('fabrication'))} "
          f"(n={ (una.get('fabrication') or {}).get('n') })")
    print(f"检索 hit@k: {rate(ret.get('hit_rate'))}  recall: {ret.get('recall', '—')}  "
          f"MRR: {ret.get('mrr', '—')}")
    health = summary.get("health") or {}
    print(f"运行错误: {health.get('run_errors', 0)}  评审失败: {health.get('judge_errors', 0)}  "
          f"降级: {health.get('degraded', 0)}")


async def _main() -> int:
    args = _parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config.load_env()

    items = load_items(args.data)
    if args.limit > 0:
        items = items[: args.limit]
    if not items:
        print("评测集为空", file=sys.stderr)
        return 2

    use_judge = not args.no_judge and args.stage in ("answer", "all")
    if use_judge and not rag.llm.is_configured(args.judge_role):
        print(f"评审角色 {args.judge_role} 未配置;请检查 backend/.env.local", file=sys.stderr)
        return 2

    print(f"加载评测集: {args.data} ({len(items)} 条, hash={dataset_hash(items)})")
    print("初始化检索索引...")
    rag.init()
    if use_judge:
        print(f"评审角色: {args.judge_role}(与 main 异源才可信)")

    out_dir = args.out or str(Path("reports") / f"eval_{time.strftime('%Y%m%d_%H%M%S')}")
    done = 0

    def on_done(rec: dict) -> None:
        nonlocal done
        done += 1
        if args.quiet:
            return
        status = "ERR" if rec.get("error") else (
            "DEGRADED" if rec.get("degraded") else "OK")
        print(f"[{done}/{len(items)}] {rec['id']} {status} "
              f"{rec.get('latency_s', 0):.2f}s")

    records = await runner.run_items(
        items,
        stage=args.stage,
        top_k=args.top_k,
        judge_role=args.judge_role,
        use_judge=use_judge,
        concurrency=args.concurrency,
        skip_research=not args.include_research,
        on_done=on_done,
    )
    summary = metrics.compute_metrics(records)
    cfg = {
        "data": args.data,
        "dataset_hash": dataset_hash(items),
        "stage": args.stage,
        "top_k": args.top_k,
        "judge_role": args.judge_role if use_judge else None,
        "use_judge": use_judge,
        "limit": args.limit,
        "include_research": args.include_research,
        "models": {
            "main": rag.llm._roles().get("main"),  # noqa: SLF001 报告需要记录模型名
            "backup": rag.llm._roles().get("backup"),
            "deep": rag.llm._roles().get("deep"),
        },
    }
    answers_path, summary_path, report_path = report.write_outputs(
        out_dir, records, summary, cfg)
    _print_summary(summary)
    print(f"\n输出:\n  {answers_path}\n  {summary_path}\n  {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
