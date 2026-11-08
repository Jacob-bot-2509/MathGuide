#!/usr/bin/env python3
"""合并抢救结果,并删除仍未翻译的题(保留人工复验清单)。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.store import load_jsonl  # noqa: E402

GARBLE_RE = re.compile(
    "[�\u0000-\u0008\u000b\u000c\u000e-\u001f]|â€|ï¿½|Ã[\x80-\xbf]"
)


def _garbled(item) -> str | None:
    for lang, block in item.content.items():
        for name in ("question", "answer", "solution"):
            if GARBLE_RE.search(getattr(block, name)):
                return f"{lang}:{name}"
        for index, step in enumerate(block.solution_steps):
            if GARBLE_RE.search(step):
                return f"{lang}:step{index}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="合并抢救结果并清理单语题")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--rescued", default="data/exercises/bilingual/rescue.bilingual.jsonl")
    parser.add_argument("--staging", default="data/exercises/staging")
    parser.add_argument("--hold", nargs="*", default=["clp:4.3.13", "clp:4.3.17", "clp2:3.6.8.30"])
    args = parser.parse_args()

    bank = {item.id: item for item in load_jsonl(Path(args.bank))}
    merged = 0
    for item in load_jsonl(Path(args.rescued)):
        if item.id in bank:
            bank[item.id] = item
            merged += 1

    hold = set(args.hold)
    removed: dict[str, str] = {}
    for item_id, item in list(bank.items()):
        where = _garbled(item)
        if where:
            removed[item_id] = f"garbled:{where}"
            bank.pop(item_id)
            continue
        if len(item.content) < 2 and item_id not in hold:
            removed[item_id] = "untranslated"
            bank.pop(item_id)

    output = Path(args.bank)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in bank.values():
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    removed_set = set(removed)
    for path in sorted(Path(args.staging).glob("*.jsonl")):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        kept = [line for line in lines if json.loads(line)["id"] not in removed_set]
        if len(kept) == len(lines):
            continue
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        manifest = path.with_suffix(".manifest.json")
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["accepted"] = len(kept)
            data["removed_untranslated"] = len(lines) - len(kept)
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    bilingual = sum(1 for item in bank.values() if len(item.content) >= 2)
    print(json.dumps({
        "bank": len(bank),
        "merged": merged,
        "removed": len(removed),
        "bilingual": bilingual,
        "held_mono": sorted(hold),
    }, ensure_ascii=False, indent=2))
    (output.parent / "purge.report.json").write_text(
        json.dumps({"removed": removed}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
