"""评测结果落盘与 Markdown 报告。"""
from __future__ import annotations

import json
import time
from pathlib import Path


def _fmt_rate(block: dict | None) -> str:
    if not block or block.get("rate") is None:
        return "—"
    lo, hi = block.get("ci95", [0, 1])
    return f"{block['rate']:.3f} [{lo:.3f}, {hi:.3f}] (n={block['n']})"


def write_outputs(out_dir: str | Path, records: list[dict], summary: dict,
                  config: dict) -> tuple[Path, Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    answers_path = out / "records.jsonl"
    summary_path = out / "summary.json"
    report_path = out / "report.md"

    with open(answers_path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    payload = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "config": config, "summary": summary}
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    lines = [
        "# MathGuide 评测报告",
        "",
        f"- 生成时间:{payload['generated_at']}",
        f"- 数据集:{config.get('data')} (hash `{config.get('dataset_hash')}`)",
        f"- 阶段:{config.get('stage')};检索 top-k:{config.get('top_k')}",
        f"- 评审角色:{config.get('judge_role')};条数:{summary.get('n_items')}",
        "",
        "## 总览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 正确率 | {_fmt_rate((summary.get('answers') or {}).get('accuracy'))} |",
        f"| 答案级幻觉率 | {_fmt_rate((summary.get('answers') or {}).get('answer_hallucination'))} |",
        f"| 不可答编造率 | {_fmt_rate((summary.get('unanswerable') or {}).get('fabrication'))} |",
        f"| 检索 hit@k | {_fmt_rate((summary.get('retrieval') or {}).get('hit_rate'))} |",
        f"| 检索 recall@k | {(summary.get('retrieval') or {}).get('recall', '—')} |",
        f"| 检索 MRR@k | {(summary.get('retrieval') or {}).get('mrr', '—')} |",
        "",
    ]
    claim = (summary.get("answers") or {}).get("claim_hallucination") or {}
    lines += [
        "## 断言级幻觉",
        "",
        f"- 无依据断言:{claim.get('bad_claims', 0)} / {claim.get('total_claims', 0)}",
        f"- 比例:{claim.get('rate') if claim.get('rate') is not None else '—'}",
        "",
    ]
    health = summary.get("health") or {}
    lines += [
        "## 运行健康度",
        "",
        f"- 运行错误:{health.get('run_errors', 0)}",
        f"- 评审失败:{health.get('judge_errors', 0)}",
        f"- 降级回答:{health.get('degraded', 0)} / {summary.get('n_items', 0)}",
        "",
    ]

    for title, key in (("按板块", "by_domain"), ("按难度", "by_difficulty"),
                       ("按题型", "by_answer_type")):
        lines += [f"## {title}", "", "| 分组 | n | 正确率 | 答案级幻觉率 |", "|---|---|---|---|"]
        for name, row in (summary.get(key) or {}).items():
            lines.append(
                f"| {name} | {row['n']} | {_fmt_rate(row.get('accuracy'))} | "
                f"{_fmt_rate(row.get('answer_hallucination'))} |")
        lines.append("")

    failures = [r for r in records if r.get("objective_correct") is False
                or (r.get("judge") or {}).get("correct") is False
                or r.get("error")]
    lines += ["## 失败样本(前 20)", ""]
    if not failures:
        lines.append("无。")
    else:
        for r in failures[:20]:
            reason = r.get("error") or r.get("objective_detail") or \
                (r.get("judge") or {}).get("rationale") or "判错"
            lines.append(f"- `{r['id']}` {r['question']} — {str(reason)[:200]}")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return answers_path, summary_path, report_path
