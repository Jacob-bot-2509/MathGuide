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


def merge(bank_path: Path, supplement_path: Path, input_path: Path) -> dict[str, int]:
    """把补题并入题库与翻译输入(按 id 去重)。

    **幂等**:同一个 id 已在库里就不再新增,重复执行本函数不会产生重复行 ——
    部署当天"导入脚本跑两遍"是常态(中断重跑、换人重跑),不能靠人记得只跑一次。
    """
    bank = {item.id: item for item in load_jsonl(bank_path)}
    supplement = list(load_jsonl(supplement_path))
    added = 0
    for item in supplement:
        if item.id not in bank:
            added += 1
        bank[item.id] = item

    _write(bank_path, bank.values())

    inputs = {item.id: item for item in load_jsonl(input_path)} if input_path.exists() else {}
    input_added = 0
    for item in supplement:
        if item.id not in inputs:
            inputs[item.id] = item
            input_added += 1
    _write(input_path, inputs.values())
    return {
        "bank": len(bank),
        "supplement": len(supplement),
        "added": added,
        "input": len(inputs),
        "input_added": input_added,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="补题并入正式题库")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--supplement", default="data/exercises/supplement/all.bilingual.jsonl")
    parser.add_argument("--input", default="data/exercises/bilingual/input-all.jsonl")
    args = parser.parse_args(argv)

    stats = merge(Path(args.bank), Path(args.supplement), Path(args.input))
    print(json.dumps(stats, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
