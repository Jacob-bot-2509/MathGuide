#!/usr/bin/env python3
"""把补题 JSONL 合并、去重,生成补题目录与报告(不改动正式题库)。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.dedupe import jaccard, ngrams  # noqa: E402
from exercises.schema import question_hash  # noqa: E402
from exercises.store import load_jsonl  # noqa: E402

THRESHOLD = 0.92


def main() -> int:
    parser = argparse.ArgumentParser(description="合并补题并去重")
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--existing", default="data/exercises/bilingual/input-all.jsonl")
    parser.add_argument("--output", default="data/exercises/supplement/all.jsonl")
    args = parser.parse_args()

    existing = list(load_jsonl(Path(args.existing))) if Path(args.existing).exists() else []
    exact = {question_hash(item.content[item.original_language].question) for item in existing}
    grams = [ngrams(item.content[item.original_language].question) for item in existing]

    kept = []
    dropped = []
    for path in args.inputs:
        for item in load_jsonl(Path(path)):
            question = item.content[item.original_language].question
            duplicate = question_hash(question) in exact or any(
                jaccard(ngrams(question), gram) >= THRESHOLD for gram in grams
            )
            if duplicate:
                dropped.append({"id": item.id, "source": item.source.name})
                continue
            kept.append(item)
            exact.add(question_hash(question))
            grams.append(ngrams(question))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in kept:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    report = {
        "output": str(output),
        "existing": len(existing),
        "kept": len(kept),
        "duplicates": len(dropped),
        "duplicate_ids": dropped,
        "by_source": {},
    }
    for item in kept:
        report["by_source"][item.source.name] = report["by_source"].get(item.source.name, 0) + 1
    (output.parent / (output.stem + ".report.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
