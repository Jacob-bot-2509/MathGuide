"""Source corrections are evidence-based and never mutate the source record."""
import json
from fractions import Fraction

from exercises.source_repairs import repair_source
from exercises.store import load_jsonl


def test_tangent_source_repair_is_guarded_and_loaded_without_changing_source(tmp_path):
    solution = ("$y-y\u2092=(6x_2_0-3)(x-x\u2092)$; "
                "$t-y\u2092=(6x_2_0-3)(1-x\u2092)$; "
                "$4x_3_0-6x_2_0+t+3=0$")
    row = {
        "id": "olympiadbench:OE_TO_maths_zh_CEE:3163",
        "source": {"name": "OlympiadBench", "tier": "research", "license": "MIT",
                   "url": "https://example.com", "attribution": "source"},
        "original_language": "zh",
        "content": {"zh": {"question": "f(x)=2x^3-3x", "answer": "(-3,-1)", "solution": solution}},
        "type": "compute", "difficulty": 3, "difficulty_source": "source",
        "primary_topic": "analysis", "topics": ["analysis"], "cross_topics": [], "tag_source": "rule",
    }
    fixed = repair_source(row)
    assert row["content"]["zh"]["solution"] == solution
    assert "x_2_0" not in fixed["content"]["zh"]["solution"]
    assert "x_0^2" in fixed["content"]["zh"]["solution"]
    assert "x_0^3" in fixed["content"]["zh"]["solution"]
    assert repair_source({**row, "id": "other"})["content"]["zh"]["solution"] == solution
    path = tmp_path / "items.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf8")
    loaded = load_jsonl(path)[0]
    assert loaded.content["zh"].solution == fixed["content"]["zh"]["solution"]
    assert "x_2_0" in path.read_text(encoding="utf8")


def test_tangent_equation_correction_follows_from_the_given_function():
    for x in map(Fraction, (-2, -1, 0, 1, 2)):
        for t in map(Fraction, (-3, 0, 5)):
            y = 2 * x**3 - 3 * x
            slope = 6 * x**2 - 3
            assert t - y - slope * (1 - x) == 4 * x**3 - 6 * x**2 + t + 3
