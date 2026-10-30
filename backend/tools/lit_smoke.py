"""
分学科文献源冒烟与金标准评测。

用法(backend 目录下):
    python tools/lit_smoke.py                 # 每学科 3 条查询
    python tools/lit_smoke.py --full          # 每学科全部查询
    python tools/lit_smoke.py --field physics --limit 10

指标:
    authority_precision@N  Top-N 中 T0/T1 场所占比
    peer_rate              同行评审结果占比
    oa_rate                已知开放获取地址占比
    retraction_rate        撤稿标记占比
    source_errors          来源超时/限流次数

通过线:每学科至少 1 条结果,来源错误率 <= 50%。
报告落盘 tools/lit_smoke_report.txt。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import config  # noqa: E402
import research_lit as rl  # noqa: E402
import research_sources as rs  # noqa: E402

config.load_env()

CASES: dict[str, list[str]] = {
    "general": [
        "climate change ocean circulation",
        "machine learning protein structure",
        "quantum error correction",
        "CRISPR gene editing",
        "perovskite solar cell stability",
        "single cell sequencing",
    ],
    "math": [
        "Riemann hypothesis zeros",
        "Navier-Stokes regularity",
        "algebraic geometry moduli space",
        "random matrix eigenvalue",
        "partial differential equations weak solution",
        "number theory elliptic curve",
    ],
    "physics": [
        "Higgs boson coupling",
        "quantum entanglement decoherence",
        "topological insulator",
        "gravitational waves black hole merger",
        "dark matter direct detection",
        "superconductivity high pressure",
    ],
    "chemistry": [
        "photocatalytic water splitting",
        "metal organic framework adsorption",
        "asymmetric catalysis",
        "electrochemical CO2 reduction",
        "polymer electrolyte battery",
        "enzyme reaction mechanism",
    ],
    "biology": [
        "CRISPR off target effect",
        "Alzheimer amyloid tau",
        "T cell exhaustion",
        "gut microbiome immunity",
        "protein folding chaperone",
        "cancer immunotherapy resistance",
    ],
}

PROVIDERS = {
    "crossref": rl._crossref,
    "arxiv": rl._arxiv,
    "europepmc": rl._europe_pmc,
    "pubmed": rl._pubmed,
    "inspire": rl._inspire,
    "ads": rl._ads,
    "zbmath": rl._zbmath,
    "openalex": rl._openalex,
    "semanticscholar": rl._semantic_scholar,
    "doaj": rl._doaj,
}


async def run_case(client: httpx.AsyncClient, field: str, query: str,
                   limit: int, peer_only: bool,
                   include_preprints: bool) -> tuple[list[dict], list[str]]:
    specs = [
        spec for spec in rs.specs_for(field, include_preprints)
        if spec.id in PROVIDERS
    ]
    outcomes = await rl._run_providers(
        client, [(spec.id, PROVIDERS[spec.id]) for spec in specs],
        query, limit, None, deadline=12.0)
    warnings = []
    gathered: list[dict] = []
    for name, outcome in outcomes:
        if isinstance(outcome, Exception):
            warnings.append(rl._provider_warning(name, outcome))
            continue
        gathered.extend(outcome)  # type: ignore[arg-type]
    results = rl._sort_results(rl._enrich(rl._merge(gathered), field), field)
    results = rl._filter_results(
        results, peer_reviewed=peer_only, oa_only=False,
        include_preprints=include_preprints)
    return rl._sort_results(results, field)[:limit], warnings


async def main_async(args: argparse.Namespace) -> int:
    fields = [args.field] if args.field else list(CASES)
    lines: list[str] = []
    failures = 0
    started = time.monotonic()
    async with httpx.AsyncClient(
            timeout=rl.TIMEOUT, follow_redirects=True,
            headers={"User-Agent": "MathGuide/1.14 (literature smoke)"}) as client:
        for field in fields:
            queries = CASES[field]
            if not args.full:
                queries = queries[:3]
            top: list[dict] = []
            field_warnings: list[str] = []
            field_failures = 0
            for query in queries:
                results, warnings = await run_case(
                    client, field, query, args.limit,
                    args.peer_only, args.preprints)
                top.extend(results)
                field_warnings.extend(warnings)
                if not results:
                    field_failures += 1
                first = results[0] if results else None
                detail = ""
                if first:
                    detail = f" | top: {first.get('venueTier') or '-'} " \
                             f"{(first.get('title') or '')[:60]}"
                lines.append(f"[{field}] {query} -> {len(results)} results"
                             f" warnings={len(warnings)}{detail}")
            n = len(top)
            authority = sum(
                1 for item in top if item.get("venueTier") in {"T0", "T1"})
            peer = sum(1 for item in top if item.get("peerReviewed"))
            oa = sum(
                1 for item in top
                if item.get("oaStatus") in {"gold", "diamond", "hybrid", "green", "bronze"}
                or item.get("oaUrl"))
            retracted = sum(
                1 for item in top if item.get("retractionStatus") == "retracted")
            rate = lambda value: f"{(value / n * 100) if n else 0:.0f}%"  # noqa: E731
            errors = len(field_warnings)
            lines.append(
                f"== {field}: queries={len(queries)} results={n} "
                f"authority_precision={rate(authority)} peer={rate(peer)} "
                f"oa={rate(oa)} retracted={rate(retracted)} "
                f"source_errors={errors} empty_queries={field_failures}")
            if n == 0 or errors > len(queries) * 3:
                failures += 1
                lines.append(f"== {field}: FAIL")
    elapsed = time.monotonic() - started
    lines.append(f"elapsed={elapsed:.1f}s fields={len(fields)} failures={failures}")
    report = "\n".join(line.rstrip() for line in lines)
    print(report)
    Path(__file__).with_name("lit_smoke_report.txt").write_text(
        report + "\n", encoding="utf-8")
    return 1 if failures else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="分学科文献源冒烟评测")
    parser.add_argument("--field", choices=list(CASES), default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--peer-only", action=argparse.BooleanOptionalAction,
                        default=True)
    parser.add_argument("--preprints", action="store_true")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
