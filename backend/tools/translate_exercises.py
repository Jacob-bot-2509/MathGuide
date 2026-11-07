#!/usr/bin/env python3
"""习题翻译试点:加载 JSONL,调用项目现有 LLM 角色,逐字段翻译并校验。

只写试点输出到 backend/data/exercises/pilot;不修改 final 题库。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import rag.llm as llm  # noqa: E402
from exercises import schema  # noqa: E402
from exercises.store import load_jsonl  # noqa: E402
from exercises.translate import TranslationError, translate_exercise_async  # noqa: E402

SYSTEM_ZH = (
    "你是严谨的数学题目翻译。只翻译文字,不要解题,不要改写题意。"
    "必须原样保留 [[M1]] 这类占位符、所有数字、单位与 LaTeX 命令。"
    "只输出译文,不要解释。"
)
SYSTEM_EN = (
    "You are a precise math exercise translator. Translate the text only; do not "
    "solve or rephrase the problem. Preserve every [[M1]] placeholder, all numbers, "
    "units and LaTeX commands exactly. Output the translation only."
)


def build_translator(role: str, timeout_tokens: int):
    async def translate(text: str, source: str, target: str) -> str:
        system = SYSTEM_ZH if target == "zh" else SYSTEM_EN
        user = f"Source language: {source}\nTarget language: {target}\n\n{text}"
        parts: list[str] = []
        async for delta in llm.stream_chat(
            system, user, role=role, fallback=True,
            max_tokens=timeout_tokens, thinking=False,
        ):
            parts.append(delta)
        return "".join(parts).strip()

    return translate


async def run(args: argparse.Namespace) -> int:
    config.load_env()
    if not llm.is_configured(args.role):
        print(f"LLM 角色未配置: {args.role}", file=sys.stderr)
        return 2

    source_path = Path(args.input)
    items = list(load_jsonl(source_path))
    candidates = [
        item for item in items
        if args.target not in item.available_languages
        and item.original_language != args.target
    ][: args.limit]
    if not candidates:
        print("没有需要翻译的题", file=sys.stderr)
        return 1

    spec = llm.resolve(args.role)
    model = spec[2] if spec else args.role
    translator = build_translator(args.role, args.max_tokens)
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    failures: Counter[str] = Counter()
    failure_details: list[dict[str, object]] = []
    results: list[tuple[schema.Exercise, schema.Exercise | None]] = []

    async def one(exercise: schema.Exercise) -> None:
        async with semaphore:
            try:
                translated = await translate_exercise_async(
                    exercise, args.target, translator, model=model,
                )
            except TranslationError as exc:
                failures[",".join(exc.reasons)] += 1
                failure_details.append({"id": exercise.id, "reasons": list(exc.reasons)})
                results.append((exercise, None))
            except Exception as exc:  # noqa: BLE001
                failures[f"llm:{type(exc).__name__}"] += 1
                failure_details.append({
                    "id": exercise.id,
                    "reasons": [f"llm:{type(exc).__name__}"],
                })
                results.append((exercise, None))
            else:
                results.append((exercise, translated))

    await asyncio.gather(*(one(item) for item in candidates))

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for original, translated in results:
            handle.write(json.dumps((translated or original).to_dict(), ensure_ascii=False) + "\n")

    report = {
        "input": str(source_path),
        "output": str(output),
        "target": args.target,
        "role": args.role,
        "model": model,
        "requested": len(candidates),
        "translated": sum(1 for _, translated in results if translated is not None),
        "failed": sum(failures.values()),
        "failures": dict(sorted(failures.items())),
        "failure_details": failure_details,
    }
    (output.parent / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="习题翻译试点")
    parser.add_argument("--input", default="data/exercises/final/math.jsonl")
    parser.add_argument("--output", default="data/exercises/pilot/math-zh.jsonl")
    parser.add_argument("--target", choices=("zh", "en"), default="zh")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--role", default="main")
    parser.add_argument("--max-tokens", type=int, default=4096)
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit 必须为正整数")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
