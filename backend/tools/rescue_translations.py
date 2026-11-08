#!/usr/bin/env python3
"""抢救单语题:带校验反馈重试;救不回的题输出待删除清单。"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import rag.llm as llm  # noqa: E402
from exercises import schema  # noqa: E402
from exercises.store import load_jsonl  # noqa: E402
from exercises.translate import (  # noqa: E402
    _answer_needs_translation,
    _needs_raw_translation,
    _numbers,
    _strip_stray_math,
    extract_math,
    restore_math,
    validate_prose_math,
    validate_translation,
)

SYSTEM_ZH = (
    "你是严谨的数学题目翻译。只翻译文字,不要解题,不要改写题意。"
    "必须原样保留 [[M1]] 这类占位符、所有数字、单位与 LaTeX 命令,"
    "不得增删、合并或重新编号占位符。只输出译文,不要解释。"
)
SYSTEM_EN = (
    "You are a precise math exercise translator. Translate the text only; do not "
    "solve or rephrase the problem. Preserve every [[M1]] placeholder, all numbers, "
    "units and LaTeX commands exactly; never add, drop, merge or renumber "
    "placeholders. Output the translation only."
)


def feedback(template: str, output: str, placeholders, target: str) -> str:
    expected = Counter(f"[[M{index}]]" for index in range(1, len(placeholders) + 1))
    actual = Counter(re.findall(r"\[\[M\d+\]\]", output))
    missing = sorted(set((expected - actual).elements()))
    extra = sorted(set((actual - expected).elements()))
    missing_numbers = list((_numbers(template) - _numbers(output)).elements())
    lines = []
    if missing:
        lines.append("缺少占位符: " + ", ".join(missing))
    if extra:
        lines.append("多出占位符: " + ", ".join(extra))
    if missing_numbers:
        lines.append("缺少原文数字: " + ", ".join(missing_numbers))
    if target == "zh" and not re.search(r"[㐀-鿿]", output):
        lines.append("译文必须使用中文")
    if target == "en":
        lines.append("译文必须使用英文,不得保留中文句子")
    return "；".join(lines)


async def call(system: str, user: str, role: str, semaphore: asyncio.Semaphore, max_tokens=8192) -> str:
    async with semaphore:
        parts = []
        async for delta in llm.stream_chat(
            system, user, role=role, fallback=True, max_tokens=max_tokens, thinking=False
        ):
            parts.append(delta)
        return "".join(parts).strip()


async def translate_field(
    text: str, source: str, target: str, roles: list[str], semaphore: asyncio.Semaphore
) -> str:
    system = SYSTEM_ZH if target == "zh" else SYSTEM_EN
    prose_math = _needs_raw_translation(text, target)
    if prose_math:
        template, placeholders = text, ()
    else:
        template, placeholders = extract_math(text)
    last_reasons: list[str] = []
    for attempt, role in enumerate(roles):
        user = f"Source language: {source}\nTarget language: {target}\n\n{template}"
        if last_reasons:
            user += "\n\n上一次译文被拒绝: " + "; ".join(last_reasons) + "。请修正后重译。"
        output = await call(system, user, role, semaphore)
        if prose_math:
            check = validate_prose_math(text, output, target)
            candidate = output
        else:
            candidate = _strip_stray_math(output)
            check = validate_translation(template, candidate, placeholders, target)
        if check.ok:
            return candidate if prose_math else restore_math(candidate, placeholders)
        last_reasons = list(check.reasons)
        detail = "" if prose_math else feedback(template, candidate, placeholders, target)
        if detail:
            last_reasons.append(detail)
    raise ValueError("; ".join(last_reasons) or "translation_failed")


async def rescue_item(item, roles: list[str], semaphore: asyncio.Semaphore):
    source = item.content[item.original_language]
    target = "zh" if item.original_language == "en" else "en"
    translated = {}
    for name in ("question", "answer", "solution"):
        text = getattr(source, name)
        if name == "answer" and not _answer_needs_translation(text):
            translated[name] = text
            continue
        translated[name] = await translate_field(
            text, item.original_language, target, roles, semaphore
        )
    steps = []
    for step in source.solution_steps:
        steps.append(await translate_field(
            step, item.original_language, target, roles, semaphore
        ))
    data = item.to_dict()
    data["content"][target] = {
        "question": translated["question"],
        "answer": translated["answer"],
        "solution": translated["solution"],
        "solution_steps": steps,
        "translation": {
            "status": "machine",
            "model": "+".join(roles),
            "version": 1,
            "reviewed": False,
        },
    }
    return schema.parse_exercise(data)


async def run(args) -> int:
    config.load_env()
    items = [item for item in load_jsonl(Path(args.input))]
    roles = args.roles
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    rescued = []
    failed = []

    async def one(item):
        try:
            return item, await rescue_item(item, roles, semaphore), None
        except Exception as exc:  # noqa: BLE001
            return item, None, str(exc)

    for future in asyncio.as_completed([one(item) for item in items]):
        item, translated, error = await future
        if translated is not None:
            rescued.append(translated)
        else:
            failed.append({"id": item.id, "reason": error})
        print(".", end="", flush=True)
    print()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for item in rescued:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    Path(args.failed).write_text(
        json.dumps(failed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "input": len(items),
        "rescued": len(rescued),
        "failed": len(failed),
        "output": str(output),
        "failed_list": args.failed,
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="带反馈抢救单语题")
    parser.add_argument("--input", default="data/exercises/bilingual/rescue.queue.jsonl")
    parser.add_argument("--output", default="data/exercises/bilingual/rescue.bilingual.jsonl")
    parser.add_argument("--failed", default="data/exercises/bilingual/rescue.failed.json")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--roles", nargs="+", default=["main", "deep"])
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
