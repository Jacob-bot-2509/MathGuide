"""从 Hugging Face datasets-server 取原始行,交给 build 流程。

采样与分页复用阶段 0 审计工具,避免两套网络代码漂移。
"""
from __future__ import annotations

import math
import random
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tools.audit_exercise_sources import (
    MATH_CONFIGS,
    NUMINAMATH_RANGES,
    OLYMPIADBENCH_CONFIGS,
    Fetcher,
    hf_rows,
    hf_size,
    largest_remainder,
    sample_hf_config,
)

MATH_DATASET = "EleutherAI/hendrycks_math"
OLYMPIADBENCH_DATASET = "Hothan/OlympiadBench"
NUMINAMATH_DATASET = "project-numina/NuminaMath-1.5"
NUMINAMATH_DEFAULT = {"cn_k12": 1500, "cn_contest": 750}

# 首批只取 text-only、open-ended 的数学竞赛/高考题;多模态与证明题在
# 阶段 0 审计里分别受图片依赖和 no-final-answer 拖累。
OLYMPIADBENCH_TEXT_CONFIGS = tuple(
    config for config in OLYMPIADBENCH_CONFIGS
    if config.startswith("OE_TO_")
)


def fetch_math(limit: int, seed: int, cache: Path) -> Mapping[str, list[dict[str, Any]]]:
    fetcher = Fetcher(Path(cache))
    sizes = hf_size(fetcher, MATH_DATASET)
    totals = {config: sizes.get(config, {}).get("test", 0) for config in MATH_CONFIGS}
    quotas = largest_remainder(totals, limit)
    rng = random.Random(seed)
    return {
        config: sample_hf_config(
            fetcher, MATH_DATASET, config, "test", quotas.get(config, 0), total, rng
        )
        for config, total in totals.items()
        if quotas.get(config, 0) > 0 and total > 0
    }


def fetch_olympiadbench(limit: int, seed: int, cache: Path) -> Mapping[str, list[dict[str, Any]]]:
    fetcher = Fetcher(Path(cache))
    sizes = hf_size(fetcher, OLYMPIADBENCH_DATASET)
    totals = {
        config: sizes.get(config, {}).get("train", 0)
        for config in OLYMPIADBENCH_TEXT_CONFIGS
    }
    quotas = largest_remainder(totals, limit)
    rng = random.Random(seed)
    return {
        config: sample_hf_config(
            fetcher, OLYMPIADBENCH_DATASET, config, "train", quotas.get(config, 0), total, rng
        )
        for config, total in totals.items()
        if quotas.get(config, 0) > 0 and total > 0
    }


def fetch_numinamath(
    quotas: Mapping[str, int] | None,
    seed: int,
    cache: Path,
) -> Mapping[str, list[dict[str, Any]]]:
    """按 cn_k12 / cn_contest 的内部窗口取样;逐页校验 source 防止上游漂移。"""
    wanted = dict(quotas or NUMINAMATH_DEFAULT)
    fetcher = Fetcher(Path(cache))
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for source_name, quota in wanted.items():
        if source_name not in NUMINAMATH_RANGES or quota <= 0:
            continue
        start, end = NUMINAMATH_RANGES[source_name]
        page_count = max(1, (end - start) // 100)
        pages_needed = max(1, math.ceil(quota / 100))
        offsets = rng.sample(range(start, end - 100, 100), min(pages_needed, page_count))
        collected: list[dict[str, Any]] = []
        for offset in offsets:
            page = hf_rows(fetcher, NUMINAMATH_DATASET, "default", "train", offset, 100)
            for item in page.get("rows", []):
                row = item.get("row") or {}
                if row.get("source") == source_name:
                    collected.append(row)
        if len(collected) < quota:
            raise RuntimeError(f"NuminaMath {source_name}: only {len(collected)} rows sampled")
        rows.extend(rng.sample(collected, quota))
    return {"": rows}


def fetch_source(source: str, limit: int, seed: int, cache: Path):
    if source == "math":
        return fetch_math(limit, seed, cache)
    if source == "olympiadbench":
        return fetch_olympiadbench(limit, seed, cache)
    if source == "numinamath":
        quotas = {
            "cn_k12": max(1, round(limit * 2 / 3)),
            "cn_contest": max(1, round(limit / 3)),
        }
        return fetch_numinamath(quotas, seed, cache)
    raise ValueError(f"未知来源: {source}")
