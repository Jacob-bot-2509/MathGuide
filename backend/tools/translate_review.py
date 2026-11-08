#!/usr/bin/env python3
"""单题补译:带校验反馈重试,输出待人工复验的译文,不并入正式题库。"""
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
    _numbers,
    extract_math,
    restore_math,
    validate_translation,
)

DEFAULT_IDS = ("clp:4.3.13", "clp:4.3.17", "clp2:3.6.8.30")

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


def feedback_for(template: str, output: str, placeholders, target: str) -> str:
    expected = Counter(f"[[M{index}]]" for index in range(1, len(placeholders) + 1))
    actual = Counter(re.findall(r"\[\[M\d+\]\]", output))
    missing = list((expected - actual).elements())
    extra = list((actual - expected).elements())
    missing_numbers = list((_numbers(template) - _numbers(output)).elements())
    lines = []
    if missing:
        lines.append("缺少占位符: " + ", ".join(sorted(set(missing))))
    if extra:
        lines.append("多出占位符: " + ", ".join(sorted(set(extra))))
    if missing_numbers:
        lines.append("缺少原文数字: " + ", ".join(missing_numbers))
    if target == "zh" and not re.search(r"[㐀-鿿]", output):
        lines.append("译文必须使用中文")
    return "；".join(lines)


async def translate_field(
    text: str, source: str, target: str, role: str, retry_role: str, attempts: int
) -> tuple[str, list[str]]:
    template, placeholders = extract_math(text)
    system = SYSTEM_ZH if target == "zh" else SYSTEM_EN
    best = ""
    reasons: list[str] = []
    for attempt in range(attempts):
        current_role = role if attempt < attempts // 2 else retry_role
        user = f"Source language: {source}\nTarget language: {target}\n\n{template}"
        if best and reasons:
            user += f"\n\n上一次译文被拒绝: {'; '.join(reasons)}。请重译并修正。"
        parts = []
        async for delta in llm.stream_chat(
            system, user, role=current_role, fallback=True, max_tokens=8192, thinking=False
        ):
            parts.append(delta)
        candidate = "".join(parts).strip()
        check = validate_translation(template, candidate, placeholders, target)
        if check.ok:
            return restore_math(candidate, placeholders), []
        if not best or len(candidate) > len(best):
            best = candidate
        reasons = list(check.reasons)
        extra = feedback_for(template, candidate, placeholders, target)
        if extra:
            reasons.append(extra)
    raise ValueError("; ".join(reasons) or "translation_failed")


async def run(args) -> int:
    config.load_env()
    bank = {item.id: item for item in load_jsonl(Path(args.bank))}
    items = [bank[item_id] for item_id in args.ids if item_id in bank]
    missing = [item_id for item_id in args.ids if item_id not in bank]
    if missing:
        print("未找到: " + ", ".join(missing), file=sys.stderr)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    translated = []
    report = []
    for item in items:
        source = item.content[item.original_language]
        target = "zh" if item.original_language == "en" else "en"
        fields = {}
        status = {}
        for name in ("question", "answer", "solution"):
            text = getattr(source, name)
            try:
                value, reasons = await translate_field(
                    text, item.original_language, target, args.role, args.retry_role,
                    args.attempts,
                )
                fields[name] = value
                status[name] = {"ok": True, "reasons": []}
            except ValueError as exc:
                fields[name] = text
                status[name] = {"ok": False, "reasons": str(exc)}
        steps = []
        for step in source.solution_steps:
            try:
                value, _ = await translate_field(
                    step, item.original_language, target, args.role, args.retry_role,
                    args.attempts,
                )
            except ValueError:
                value = step
            steps.append(value)

        data = item.to_dict()
        data["content"][target] = {
            "question": fields["question"],
            "answer": fields["answer"],
            "solution": fields["solution"],
            "solution_steps": steps,
            "translation": {
                "status": "machine",
                "model": args.retry_role,
                "version": 1,
                "reviewed": False,
            },
        }
        translated.append(schema.parse_exercise(data))
        report.append({"id": item.id, "source": item.source.name, "status": status})

    jsonl_path = out_dir / "manual-translations.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in translated:
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    (out_dir / "manual-translations.report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = ["# 待复验翻译", "", f"共 {len(translated)} 题；译文未并入正式题库。", ""]
    for item, entry in zip(translated, report):
        lines.append(f"## {item.id} — {item.source.name}")
        lines.append("")
        lines.append("校验状态：")
        for name, state in entry["status"].items():
            mark = "通过" if state["ok"] else "需复验"
            detail = f"（{'; '.join(state['reasons'])}）" if state["reasons"] else ""
            lines.append(f"- {name}: {mark}{detail}")
        lines.append("")
        source = item.content[item.original_language]
        target = "zh" if item.original_language == "en" else "en"
        for name in ("question", "answer", "solution"):
            lines.append(f"### {name}")
            lines.append("")
            lines.append("**EN**：" + getattr(source, name))
            lines.append("")
            lines.append("**中**：" + getattr(item.content[target], name))
            lines.append("")
    (out_dir / "manual-translations.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="单题补译并输出复验材料")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--out-dir", default="data/exercises/review")
    parser.add_argument("--ids", nargs="+", default=list(DEFAULT_IDS))
    parser.add_argument("--role", default="main")
    parser.add_argument("--retry-role", default="deep")
    parser.add_argument("--attempts", type=int, default=4)
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
