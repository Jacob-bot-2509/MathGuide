#!/usr/bin/env python3
"""按审计清单修复临时题库:答案回填、语种纠正、坏译文丢弃待复译、源数据清洗。"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises import schema  # noqa: E402
from exercises.gate import gate_exercise, latex_balanced  # noqa: E402
from exercises.importers.common import clean_text, has_leak  # noqa: E402
from exercises.store import load_jsonl  # noqa: E402
from exercises.translate import _answer_needs_translation  # noqa: E402

CJK_RE = re.compile(r"[㐀-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]{2,}")
PLACEHOLDER_RE = re.compile(r"\[\[M\d+\]\]")
HEADINGS = {
    "误译": "answers",
    "提示词": "leaks",
    "单语": "mono",
    "中文字段其实是英文": "reversed",
    "公式被破坏": "broken",
    "PageIndex": "pageindex",
    "HTML": "html",
    "left": "leftright",
    "可疑": "suspicious",
}
ISSUE_TYPES = {
    "identical_zh_en": "identical",
    "untranslated_english_prose": "untranslated_en",
}


def parse_id_list(path: Path) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {name: set() for name in HEADINGS.values()}
    current = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            current = next((key for key in HEADINGS if key in line), "")
            continue
        if not current:
            continue
        match = re.search(r"`([^`]+)`", line)
        if match:
            groups[HEADINGS[current]].add(match.group(1))
    return groups


def parse_issues(path: Path) -> dict[str, set[str]]:
    import csv

    groups: dict[str, set[str]] = {name: set() for name in ISSUE_TYPES.values()}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            name = ISSUE_TYPES.get(row.get("issue_type", ""))
            if name:
                groups[name].add(row["id"])
    return groups


def _script(text: str) -> str:
    cjk = len(CJK_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    return "zh" if cjk >= max(5, latin * 0.5) else ("en" if latin else "mixed")


def _drop_target(data: dict) -> str | None:
    """删掉不合格的译文块;返回被删语言。"""
    original = data["original_language"]
    target = "zh" if original == "en" else "en"
    if target in data["content"]:
        data["content"].pop(target)
        return target
    return None


def _block_ok(block: dict) -> bool:
    for name in ("question", "answer", "solution"):
        value = block[name]
        if PLACEHOLDER_RE.search(value) or not latex_balanced(value):
            return False
    return True


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _drop_identical_target(data: dict, notes: list[str]) -> None:
    """中英字段相同、或“译文”仍是原文语种:删掉伪译文,排队重译。"""
    original = data["original_language"]
    target = "zh" if original == "en" else "en"
    content = data["content"]
    if target not in content:
        return
    source = content[original]
    translated = content[target]
    identical = all(_norm(source[name]) == _norm(translated[name])
                    for name in ("question", "answer", "solution"))
    if identical or _script(translated["question"]) == _script(source["question"]):
        content.pop(target)
        notes.append("drop_pseudo_translation")


def _normalize_language(data: dict, notes: list[str]) -> None:
    content = data["content"]
    original = data["original_language"]
    block = content.get(original)
    if block is None:
        return
    detected = _script(block["question"])
    if detected != "mixed" and detected != original:
        content[detected] = content.pop(original)
        data["original_language"] = detected
        notes.append(f"relabel:{original}->{detected}")
        original = detected
    # 与原文同文字的“译文”不是翻译,删掉待重译。
    for lang in list(content):
        if lang == original:
            continue
        if lang == "zh" and len(CJK_RE.findall(content[lang]["question"])) < 5:
            content.pop(lang)
            notes.append("drop_pseudo_zh")
        elif lang == "en" and (
            len(LATIN_RE.findall(content[lang]["question"])) < 3
            or len(CJK_RE.findall(content[lang]["question"])) > 3
        ):
            content.pop(lang)
            notes.append("drop_pseudo_en")


def _clean_block(block: dict) -> None:
    for name in ("question", "answer", "solution"):
        block[name] = clean_text(block[name])


def _fix_answer(data: dict) -> bool:
    original = data["original_language"]
    source = data["content"][original]
    if _answer_needs_translation(source["answer"]):
        return False
    for lang, block in data["content"].items():
        if lang != original:
            block["answer"] = source["answer"]
    return True


def _refresh_kuttler(data: dict, staging: dict[str, dict]) -> bool:
    item = staging.get(data["id"])
    if not item:
        return False
    source = item["content"][item["original_language"]]
    current = data["content"][data["original_language"]]
    if all(current[name] == source[name] for name in ("question", "answer", "solution")):
        return False
    data["content"][data["original_language"]] = dict(source)
    _drop_target(data)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="按审计清单修复题库")
    parser.add_argument("--bank", default="data/exercises/bilingual/all.jsonl")
    parser.add_argument("--staging", default="data/exercises/staging/kuttler.jsonl")
    parser.add_argument("--ids", required=True, help="ID_LIST.md")
    parser.add_argument("--issues", default="", help="issues.csv(可选)")
    parser.add_argument("--output", default="data/exercises/bilingual/all.remediated.jsonl")
    parser.add_argument("--queue", default="data/exercises/bilingual/remediate.queue.jsonl")
    args = parser.parse_args()

    groups = parse_id_list(Path(args.ids))
    if args.issues:
        for name, ids in parse_issues(Path(args.issues)).items():
            groups.setdefault(name, set()).update(ids)
    bank = [json.loads(line) for line in Path(args.bank).read_text(encoding="utf-8").splitlines() if line.strip()]
    staging = {
        item.id: item.to_dict()
        for item in load_jsonl(Path(args.staging))
    }

    queue: list[dict] = []
    excluded: list[dict] = []
    kept: list[dict] = []
    counts = {name: 0 for name in set(HEADINGS.values()) | set(ISSUE_TYPES.values())}
    notes_counts: dict[str, int] = {}

    for data in bank:
        item_id = data["id"]
        notes: list[str] = []
        tags = [name for name, ids in groups.items() if item_id in ids]
        for tag in tags:
            counts[tag] += 1

        for block in data["content"].values():
            _clean_block(block)

        if "leftright" in tags:
            excluded.append({"id": item_id, "reason": "source_latex_broken"})
            continue

        if "pageindex" in tags or data["id"].startswith("kuttler:"):
            if _refresh_kuttler(data, staging):
                notes.append("kuttler_refresh")

        if "reversed" in tags:
            _normalize_language(data, notes)
        elif item_id in groups.get("identical", set()) or item_id in groups.get("untranslated_en", set()):
            _drop_identical_target(data, notes)

        _fix_answer(data)

        original = data["original_language"]
        source = data["content"][original]
        target = "zh" if original == "en" else "en"
        if target in data["content"]:
            translated = data["content"][target]
            bad = (
                "broken" in tags
                or "reversed" in tags
                or "suspicious" in tags
                or not _block_ok(translated)
            )
            if has_leak(json.dumps(translated, ensure_ascii=False)):
                notes.append("leak_in_translation")
                bad = True
            if bad:
                data["content"].pop(target)
                notes.append("drop_translation")

        if has_leak(json.dumps(source, ensure_ascii=False)):
            excluded.append({"id": item_id, "reason": "source_prompt_leak"})
            continue
        if not all(source[name].strip() for name in ("question", "answer", "solution")):
            excluded.append({"id": item_id, "reason": "empty_field_after_clean"})
            continue

        try:
            exercise = schema.parse_exercise(data)
        except schema.SchemaError as exc:
            excluded.append({"id": item_id, "reason": f"schema:{exc}"})
            continue
        if exercise.type == "proof" and exercise.content[original].answer.strip().lower() == "proof":
            pass
        gate = gate_exercise(exercise)
        if not gate.accepted:
            excluded.append({"id": item_id, "reason": "gate:" + ",".join(gate.reasons)})
            continue

        data = exercise.to_dict()
        for note in notes:
            notes_counts[note] = notes_counts.get(note, 0) + 1
        kept.append(data)
        if len(data["content"]) < 2:
            queue.append(data)

    output = Path(args.output)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for data in kept:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")
    with Path(args.queue).open("w", encoding="utf-8", newline="\n") as handle:
        for data in queue:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    report = {
        "input": len(bank),
        "kept": len(kept),
        "excluded": len(excluded),
        "queue": len(queue),
        "flagged": counts,
        "notes": notes_counts,
        "excluded_items": excluded,
        "queue_ids": [data["id"] for data in queue],
    }
    Path(args.output).with_suffix(".report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: report[k] for k in ("input", "kept", "excluded", "queue", "flagged", "notes")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
