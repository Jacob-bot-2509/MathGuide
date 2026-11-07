"""习题去重:精确哈希与字符 5-gram 近似重复。"""
from __future__ import annotations

from exercises import schema
from exercises.dedupe import (
    DedupeResult,
    dedupe,
    is_near_duplicate,
    jaccard,
    ngrams,
    normalize_question,
    similarity,
)


def make(question: str, answer: str = "2", **overrides):
    data = {
        "id": overrides.pop("id", f"dedupe:{abs(hash(question))}"),
        "source": {
            "name": "Test",
            "tier": "safe",
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test Source",
        },
        "original_language": "en",
        "content": {
            "en": {
                "question": question,
                "answer": answer,
                "solution": f"The computation gives {answer}, therefore the result is {answer}.",
            }
        },
        "type": "compute",
        "difficulty": 2,
        "difficulty_source": "source",
        "primary_topic": "analysis",
        "topics": ["analysis"],
        "cross_topics": [],
        "tag_source": "rule",
    }
    data.update(overrides)
    return schema.parse_exercise(data)


def test_normalize_question_ignores_case_and_whitespace():
    assert normalize_question("  Compute   1 + 1. ") == normalize_question("compute 1+1.")


def test_ngrams_short_text_is_a_single_token():
    assert ngrams("abc") == {"abc"}


def test_jaccard_matches_identical_sets():
    left = ngrams("the quick brown fox jumps over the lazy dog")
    assert jaccard(left, left) == 1.0


def test_near_duplicate_detects_one_word_change():
    left = (
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two symmetric parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units."
    )
    right = (
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two equal parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units."
    )

    assert similarity(left, right) >= 0.92
    assert is_near_duplicate(left, right)


def test_unrelated_questions_are_not_duplicates():
    left = "Compute the exact value of the following definite integral by symmetry."
    right = "Prove that every finite group of prime order is cyclic and simple."

    assert is_near_duplicate(left, right) is False


def test_dedupe_keeps_first_and_reports_exact_duplicate():
    first = make("Compute the exact value of 1 + 1.", id="dedupe:first")
    second = make("  compute   the exact value of 1+1.  ", id="dedupe:second")

    result = dedupe([first, second])

    assert isinstance(result, DedupeResult)
    assert [item.id for item in result.kept] == ["dedupe:first"]
    assert result.dropped[0][0].id == "dedupe:first"
    assert result.dropped[0][1].id == "dedupe:second"


def test_dedupe_ignores_answer_difference_when_question_matches():
    first = make("Compute the exact value of 1 + 1.", answer="2", id="dedupe:a")
    second = make("Compute the exact value of 1 + 1.", answer="2.0", id="dedupe:b")

    result = dedupe([first, second])

    assert len(result.kept) == 1
    assert len(result.dropped) == 1


def test_dedupe_keeps_near_duplicates_when_threshold_is_high():
    left = make(
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two symmetric parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units.",
        id="dedupe:left",
    )
    right = make(
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two equal parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units.",
        id="dedupe:right",
    )

    result = dedupe([left, right], threshold=0.999)

    assert len(result.kept) == 2
    assert result.dropped == ()


def test_dedupe_drops_near_duplicate_at_default_threshold():
    left = make(
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two symmetric parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units.",
        id="dedupe:left2",
    )
    right = make(
        "Compute the exact value of the following definite integral by splitting "
        "the interval into two equal parts and applying the fundamental theorem. "
        "Show every intermediate step, justify each substitution, and simplify the "
        "final expression completely before reporting the answer. "
        "Use exact arithmetic throughout and state the final result with the "
        "correct units.",
        id="dedupe:right2",
    )

    result = dedupe([left, right])

    assert len(result.kept) == 1
    assert len(result.dropped) == 1
