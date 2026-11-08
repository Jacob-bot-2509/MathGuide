#!/usr/bin/env python3
"""剔除不合格译文:公式损坏、提示词残留、中文夹英文、英文夹中文。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.gate import latex_balanced  # noqa: E402

CJK_RE = re.compile(r"[㐀-鿿]")
LATIN_RUN_RE = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,}){4,}")
LEAK_RE = re.compile(
    r"请提供需要翻译|保留源文本的换行|直接输出翻译结果|"
    r"line\s+breaks\s+and\s+format|output\s+the\s+translation\s+result",
    re.I,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理不合格译文")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--queue", default="data/exercises/bilingual/clean.queue.jsonl")
    args = parser.parse_args()

    items = [
        json.loads(line)
        for line in Path(args.bank).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    kept = []
    queue = []
    reasons: dict[str, int] = {}
    for data in items:
        original = data["original_language"]
        target = "zh" if original == "en" else "en"
        block = data["content"].get(target)
        if block is not None:
            bad: list[str] = []
            if not all(latex_balanced(block[name])
                       for name in ("question", "answer", "solution")):
                bad.append("latex")
            if LEAK_RE.search(block["question"] + block["solution"] + block["answer"]):
                bad.append("leak")
            if target == "zh" and LATIN_RUN_RE.search(block["question"]):
                bad.append("english_run")
            if target == "en" and len(CJK_RE.findall(block["question"])) >= 10:
                bad.append("residual_chinese")
            if bad:
                data["content"].pop(target)
                for reason in bad:
                    reasons[reason] = reasons.get(reason, 0) + 1
                queue.append(data)
        kept.append(data)

    Path(args.bank).write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in kept) + "\n",
        encoding="utf-8",
    )
    Path(args.queue).write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in queue) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "kept": len(kept),
        "reverted_to_mono": len(queue),
        "reasons": reasons,
        "queue": str(args.queue),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
