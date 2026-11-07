"""构建流程:解析原始行 → 拒绝统计 → 去重 → 写 JSONL 与 manifest。"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import schema
from .dedupe import dedupe
from .importers import math_dataset, numinamath, olympiadbench
from .importers.common import ImportSkip
from .tagging import apply_tags

SOURCES = {
    "math": (math_dataset, math_dataset.SOURCE),
    "olympiadbench": (olympiadbench, olympiadbench.SOURCE),
    "numinamath": (numinamath, numinamath.SOURCE),
}


@dataclass(frozen=True)
class BuildReport:
    source: str
    parsed: int
    accepted: int
    duplicates: int
    rejected: dict[str, int]
    path: Path
    manifest_path: Path


def _parse_rows(
    source: str,
    rows_by_config: Mapping[str, Iterable[Mapping[str, Any]]],
) -> tuple[list[schema.Exercise], Counter[str]]:
    module, _ = SOURCES[source]
    items: list[schema.Exercise] = []
    rejected: Counter[str] = Counter()
    for config, rows in rows_by_config.items():
        for index, row in enumerate(rows):
            try:
                if source == "numinamath":
                    item = module.parse_row(row, index)
                else:
                    item = module.parse_row(row, config, index)
            except ImportSkip as exc:
                rejected[str(exc)] += 1
                continue
            items.append(item)
    return items, rejected


def build_source(
    source: str,
    rows_by_config: Mapping[str, Iterable[Mapping[str, Any]]],
    output_dir: Path,
) -> BuildReport:
    if source not in SOURCES:
        raise ValueError(f"未知来源: {source}")
    _, source_meta = SOURCES[source]

    items, rejected = _parse_rows(source, rows_by_config)
    items = [apply_tags(item) for item in items]
    result = dedupe(items)
    kept = list(result.kept)
    duplicates = len(items) - len(kept)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{source}.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in kept:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    manifest = {
        "schema_version": 1,
        "source": source,
        "tier": source_meta.tier,
        "license": source_meta.license,
        "license_url": source_meta.url,
        "license_scope": source_meta.license_scope,
        "attribution": source_meta.attribution,
        "parsed": len(items) + sum(rejected.values()),
        "accepted": len(kept),
        "duplicates": duplicates,
        "rejected": dict(sorted(rejected.items())),
    }
    manifest_path = output / f"{source}.manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return BuildReport(
        source=source,
        parsed=manifest["parsed"],
        accepted=len(kept),
        duplicates=duplicates,
        rejected=manifest["rejected"],
        path=path,
        manifest_path=manifest_path,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    from .fetch import fetch_source

    parser = argparse.ArgumentParser(description="构建习题 JSONL 与 manifest")
    parser.add_argument("--source", choices=("all",) + tuple(SOURCES), default="all")
    parser.add_argument("--limit", type=int, default=2000, help="每个来源的最大抽样题数")
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--cache", default="/tmp/exercise_source_audit")
    parser.add_argument("--output", default="data/exercises/final")
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit 必须为正整数")

    names = tuple(SOURCES) if args.source == "all" else (args.source,)
    for name in names:
        rows = fetch_source(name, args.limit, args.seed, Path(args.cache))
        report = build_source(name, rows, Path(args.output))
        print(json.dumps({
            "source": report.source,
            "parsed": report.parsed,
            "accepted": report.accepted,
            "duplicates": report.duplicates,
            "rejected": report.rejected,
            "path": str(report.path),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
