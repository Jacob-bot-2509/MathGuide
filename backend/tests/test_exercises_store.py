"""习题存储:JSONL 加载、来源分层过滤、语言/板块过滤与确定性抽样。"""
from __future__ import annotations

import json

import pytest

from exercises import schema
from exercises.store import ExerciseStore, load_jsonl


def make(
    exercise_id: str,
    *,
    topic: str = "analysis",
    cross: tuple[str, ...] = (),
    exercise_type: str = "compute",
    difficulty: int = 2,
    languages: tuple[str, ...] = ("en",),
    tier: str = "safe",
):
    content = {}
    for lang in languages:
        if lang == "en":
            question = f"Compute the exact value of integral number {exercise_id}."
            answer = "2"
            solution = f"Integral {exercise_id} evaluates to 2 after the substitution step."
        else:
            question = f"计算第 {exercise_id} 个积分的精确值。"
            answer = "2"
            solution = f"第 {exercise_id} 个积分经过换元后得到 2,所以结果是 2。"
        content[lang] = {"question": question, "answer": answer, "solution": solution}
    data = {
        "id": exercise_id,
        "source": {
            "name": "Test",
            "tier": tier,
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test Source",
        },
        "original_language": "en",
        "content": content,
        "type": exercise_type,
        "difficulty": difficulty,
        "difficulty_source": "rule",
        "primary_topic": topic,
        "topics": [topic],
        "cross_topics": list(cross),
        "tag_source": "rule",
    }
    return schema.parse_exercise(data)


def test_load_jsonl_skips_blank_lines_and_reports_bad_line(tmp_path):
    path = tmp_path / "items.jsonl"
    path.write_text(
        json.dumps(make("store:1").to_dict(), ensure_ascii=False) + "\n\n",
        encoding="utf-8",
    )

    loaded = load_jsonl(path)

    assert [item.id for item in loaded] == ["store:1"]

    path.write_text("{bad json}\n", encoding="utf-8")
    with pytest.raises(schema.SchemaError, match="第 1 行"):
        load_jsonl(path)


def test_store_filters_blocked_sources_even_when_requested():
    safe = make("store:safe", tier="safe")
    blocked = make("store:blocked", tier="blocked")

    default = ExerciseStore([safe, blocked])
    requested = ExerciseStore([safe, blocked], tiers=("blocked",))

    assert [item.id for item in default.exercises] == ["store:safe"]
    assert requested.exercises == ()


def test_filter_by_topic_type_difficulty_and_language():
    analysis = make("store:a", topic="analysis", difficulty=1)
    algebra = make("store:b", topic="algebra", difficulty=3)
    bilingual = make("store:c", topic="analysis", exercise_type="proof", difficulty=3, languages=("en", "zh"))
    store = ExerciseStore([analysis, algebra, bilingual])

    assert [item.id for item in store.filter(topics=("analysis",))] == ["store:a", "store:c"]
    assert [item.id for item in store.filter(types=("proof",))] == ["store:c"]
    assert [item.id for item in store.filter(difficulty=(3, 3))] == ["store:b", "store:c"]
    assert [item.id for item in store.filter(lang="zh")] == ["store:c"]
    assert [item.id for item in store.filter(lang="both")] == ["store:c"]
    assert [item.id for item in store.filter(lang="en")] == ["store:a", "store:b", "store:c"]


def test_filter_by_cross_topic():
    a = make("store:x", cross=("least-squares",))
    b = make("store:y", cross=("eigen",))
    store = ExerciseStore([a, b])

    assert [item.id for item in store.filter(cross_topics=("least-squares",))] == ["store:x"]


def test_filter_rejects_empty_result_without_raising():
    store = ExerciseStore([make("store:only")])

    assert store.filter(topics=("topology",)) == ()


def test_sample_is_deterministic_and_bounded():
    items = [make(f"store:{index:02d}") for index in range(10)]
    store = ExerciseStore(items)

    first = store.sample(4, seed=7)
    second = store.sample(4, seed=7)
    all_items = store.sample(100, seed=7)

    assert [item.id for item in first] == [item.id for item in second]
    assert len(first) == 4
    assert len(all_items) == 10
    assert [item.id for item in all_items] == sorted(item.id for item in all_items)


def test_coverage_counts_topics_types_difficulties_and_languages():
    store = ExerciseStore([
        make("store:c1", topic="analysis", exercise_type="compute", difficulty=1),
        make("store:c2", topic="analysis", exercise_type="proof", difficulty=2,
             languages=("en", "zh"), cross=("least-squares",)),
        make("store:c3", topic="algebra", exercise_type="compute", difficulty=2),
    ])

    coverage = store.coverage()

    assert coverage["topics"]["analysis"] == 2
    assert coverage["topics"]["algebra"] == 1
    assert coverage["cross_topics"]["least-squares"] == 1
    assert coverage["types"]["compute"] == 2
    assert coverage["types"]["proof"] == 1
    assert coverage["difficulties"]["2"] == 2
    assert coverage["languages"]["en"] == 2
    assert coverage["languages"]["both"] == 1


def test_store_from_directory_loads_jsonl_files_in_order(tmp_path):
    (tmp_path / "b.jsonl").write_text(
        json.dumps(make("store:from-b").to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "a.jsonl").write_text(
        json.dumps(make("store:from-a").to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    store = ExerciseStore.from_directory(tmp_path)

    assert [item.id for item in store.exercises] == ["store:from-a", "store:from-b"]
