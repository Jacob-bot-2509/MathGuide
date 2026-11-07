#!/usr/bin/env python3
"""把补题译文并入正式题库(按 id 去重),同步翻译输入。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.store import load_jsonl  # noqa: E402


def _write(path: Path, items) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="补题并入正式题库")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--supplement", default="data/exercises/supplement/all.bilingual.jsonl")
    parser.add_argument("--input", default="data/exercises/bilingual/input-all.jsonl")
    args = parser.parse_args()

    bank = {item.id: item for item in load_jsonl(Path(args.bank))}
    supplement = list(load_jsonl(Path(args.supplement)))
    added = 0
    for item in supplement:
        if item.id not in bank:
            added += 1
        bank[item.id] = item

    _write(Path(args.bank), bank.values())

    inputs = {item.id: item for item in load_jsonl(Path(args.input))}
    input_added = 0
    for item in supplement:
        if item.id not in inputs:
            inputs[item.id] = item
            input_added += 1
    _write(Path(args.input), inputs.values())

    print(json.dumps({
        "bank": len(bank),
        "supplement": len(supplement),
        "added": added,
        "input": len(inputs),
        "input_added": input_added,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
