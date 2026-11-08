#!/usr/bin/env python3
"""把复译结果并回修复后的题库,并保留待人工复验的题不自动入库。"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.store import load_jsonl  # noqa: E402

HOLD = ("clp:4.3.13", "clp:4.3.17", "clp2:3.6.8.30")


def main() -> int:
    parser = argparse.ArgumentParser(description="合并复译结果")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.remediated.jsonl")
    parser.add_argument("--queue", default="data/exercises/bilingual/remediate.queue.bilingual.jsonl")
    parser.add_argument("--output", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--backup", default="data/exercises/bilingual/all.pre-remediation.jsonl")
    parser.add_argument("--hold", nargs="*", default=list(HOLD))
    args = parser.parse_args()

    bank = {item.id: item for item in load_jsonl(Path(args.bank))}
    queue = {item.id: item for item in load_jsonl(Path(args.queue))}
    hold = set(args.hold)
    merged = 0
    kept_back = 0
    for item_id, item in queue.items():
        if item_id in hold:
            kept_back += 1
            continue
        if item_id in bank:
            bank[item_id] = item
            merged += 1

    output = Path(args.output)
    if output.exists() and not Path(args.backup).exists():
        shutil.copy2(output, args.backup)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for item in bank.values():
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    temporary.replace(output)

    bilingual = sum(1 for item in bank.values() if len(item.content) >= 2)
    print(json.dumps({
        "bank": len(bank),
        "merged": merged,
        "held_back": kept_back,
        "bilingual": bilingual,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
