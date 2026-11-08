#!/usr/bin/env python3
"""补题:Kuttler 线性代数两章习题,抓取 → 质量门 → 与现库去重 → 写 JSONL。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from exercises.dedupe import jaccard, ngrams  # noqa: E402
from exercises.importers import kuttler  # noqa: E402
from exercises.schema import question_hash  # noqa: E402
from exercises.store import load_jsonl  # noqa: E402


def fetch(url: str, cache_dir: Path) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha256(url.encode()).hexdigest() + ".html"
    path = cache_dir / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    with httpx.Client(timeout=60, trust_env=True, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        response.encoding = "utf-8"
        path.write_text(response.text, encoding="utf-8")
        return response.text


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 Kuttler 习题")
    parser.add_argument("--input", default="data/exercises/bilingual/input-all.jsonl")
    parser.add_argument("--output", default="data/exercises/staging/kuttler.jsonl")
    parser.add_argument("--cache", default="data/exercises/cache")
    args = parser.parse_args()

    cache_dir = Path(args.cache)
    items = []
    stats: dict[str, object] = {}
    for prefix, (url, cross_topic) in kuttler.PAGES.items():
        html = fetch(url, cache_dir)
        parsed, skipped = kuttler.parse_page(html, url, cross_topic, prefix)
        items.extend(parsed)
        stats[prefix] = {"url": url, "accepted": len(parsed), "skipped": skipped}

    existing = list(load_jsonl(Path(args.input))) if Path(args.input).exists() else []
    # 同源旧结果不参与去重;否则重跑导入会把已入库的 Kuttler 全判成重复。
    existing = [item for item in existing if not item.id.startswith("kuttler:")]
    # 只把新题与现库比对;全量 dedupe 在 6800+ 题上会退化成 O(n²)。
    exact = {question_hash(item.content[item.original_language].question) for item in existing}
    grams = [
        ngrams(item.content[item.original_language].question)
        for item in existing
    ]
    kept = []
    dropped = []
    for item in items:
        question = item.content[item.original_language].question
        duplicate = question_hash(question) in exact or any(
            jaccard(ngrams(question), gram) >= 0.92 for gram in grams
        )
        if duplicate:
            dropped.append(item.id)
        else:
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
        "parsed": len(items),
        "kept": len(kept),
        "duplicates": len(dropped),
        "duplicate_ids": dropped,
        "pages": stats,
    }
    (output.parent / (output.stem + ".report.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rejected: dict[str, int] = {}
    for page in stats.values():
        for reason, count in page["skipped"].items():
            rejected[reason] = rejected.get(reason, 0) + count
    manifest = {
        "schema_version": 1,
        "source": "kuttler",
        "tier": kuttler.SOURCE.tier,
        "license": kuttler.SOURCE.license,
        "license_url": kuttler.SOURCE.url,
        "license_scope": kuttler.SOURCE.license_scope,
        "attribution": kuttler.SOURCE.attribution,
        "parsed": len(items) + sum(rejected.values()),
        "accepted": len(kept),
        "duplicates": len(dropped),
        "rejected": dict(sorted(rejected.items())),
    }
    (output.parent / (output.stem + ".manifest.json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
