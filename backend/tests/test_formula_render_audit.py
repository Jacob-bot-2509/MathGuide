"""Formula audit exercises the same KaTeX and Word engines as document exports."""
from __future__ import annotations

import runpy
from pathlib import Path


def test_formula_audit_reports_failures_without_changing_source():
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit" / "formula_render_audit.py"
    module = runpy.run_path(str(path))
    records = [{
        "id": "fixture:one",
        "content": {"en": {
            "question": r"Correct $\frac{1}{2}$ and bad $\notacommand{x}$.",
            "answer": "",
            "solution": r"$\begin{array}{cc}1&2\\\hline 3&4\end{array}$",
        }},
    }]
    formulas = module["collect_formulas"](records)
    report = module["audit"](formulas)
    assert report["formula_occurrences"] == 3
    assert report["word_layout_warning_occurrences"] == 1
    assert report["word_layout_warnings"][0]["exercise_ids"] == ["fixture:one"]
    assert report["katex_failed_occurrences"] == 1
    assert report["word_failed_occurrences"] == 1
    assert report["katex_failures"][0]["exercise_ids"] == ["fixture:one"]
    assert records[0]["content"]["en"]["question"].endswith(r"$\notacommand{x}$.")
