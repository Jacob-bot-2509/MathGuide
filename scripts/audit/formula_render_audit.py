"""Audit formula rendering against the actual KaTeX and Word export engines.

Run from the repository root: python scripts/audit/formula_render_audit.py
The JSON report contains question IDs and failure reasons, not question text.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import math_render  # noqa: E402
import math_table_render  # noqa: E402
from exercises.source_repairs import repair_source  # noqa: E402

DATASET = ROOT / "backend" / "data" / "exercises" / "bilingual" / "all.jsonl"
KATEX = ROOT / "backend" / "static" / "katex" / "katex.min.js"

_CHECK_KATEX = r"""
const fs = require('fs');
const katex = require(process.argv[1]);
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const macros = {...input.macros, '\\knowl': '\\def\\mgIgnore##1{}\\mgIgnore{#1}#2'};
const failures = [];
console.warn = () => {};
input.formulas.forEach(([tex, display], i) => {
  try {
    katex.renderToString(tex, {
      displayMode: display, throwOnError: true, strict: 'ignore',
      macros: {...macros}, output: 'mathml'
    });
  } catch (error) {
    failures.push([i, error.message
      .replace(/ at position \d+[\s\S]*/, '')
      .replace(/ at end of input[\s\S]*/, '')]);
  }
});
process.stdout.write(JSON.stringify(failures));
"""


def collect_formulas(records):
    """Count occurrences and preserve their locations without copying user data."""
    formulas = {}
    for record in records:
        record = repair_source(record)
        for language, content in record.get("content", {}).items():
            for field in ("question", "answer", "solution"):
                value = content.get(field, "")
                if not isinstance(value, str):
                    continue
                for is_math, display, tex in math_render.segments(value):
                    if is_math:
                        key = (math_render.prepare(tex), display)
                        locations = formulas.setdefault(key, [])
                        locations.append((record.get("id", ""), language, field))
    return formulas


def audit(formulas):
    keys = list(formulas)
    payload = json.dumps({"macros": math_render.MACROS, "formulas": keys}, ensure_ascii=False)
    result = subprocess.run(
        ["node", "-e", _CHECK_KATEX, str(KATEX)],
        input=payload, capture_output=True, text=True, encoding="utf8",
        check=True, timeout=120,
    )
    katex_errors = {index: error for index, error in json.loads(result.stdout)}
    word_errors = {}
    word_images = {}
    word_layout_warnings = {}
    for index, (tex, _display) in enumerate(keys):
        try:
            if math_render.requires_table_image(tex):
                if index in katex_errors:
                    raise ValueError("Unsupported ruled array syntax")
                math_table_render.render_table_image(tex)
                word_images[index] = "Ruled array rendered as an image"
            else:
                math_render.to_omml(tex)
        except ValueError as exc:
            word_errors[index] = str(exc)
        if (index + 1) % 10000 == 0:
            print(f"Word: {index + 1}/{len(keys)} unique formulas checked", file=sys.stderr, flush=True)

    def summarize(errors):
        counts = Counter()
        affected = defaultdict(set)
        for index, reason in errors.items():
            locations = formulas[keys[index]]
            counts[reason] += len(locations)
            affected[reason].update(item[0] for item in locations)
        return [
            {"reason": reason, "occurrences": count, "exercise_ids": sorted(affected[reason])}
            for reason, count in counts.most_common()
        ]

    total = sum(map(len, formulas.values()))
    assert total >= len(keys)
    return {
        "formula_occurrences": total,
        "unique_formulas": len(keys),
        "katex_failed_occurrences": sum(len(formulas[keys[i]]) for i in katex_errors),
        "word_failed_occurrences": sum(len(formulas[keys[i]]) for i in word_errors),
        "katex_failures": summarize(katex_errors),
        "word_failures": summarize(word_errors),
        "word_image_occurrences": sum(len(formulas[keys[i]]) for i in word_images),
        "word_images": summarize(word_images),
        "word_layout_warning_occurrences": sum(len(formulas[keys[i]]) for i in word_layout_warnings),
        "word_layout_warnings": summarize(word_layout_warnings),
    }


def main():
    with DATASET.open(encoding="utf8") as handle:
        formulas = collect_formulas(json.loads(line) for line in handle if line.strip())
    print(json.dumps(audit(formulas), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
