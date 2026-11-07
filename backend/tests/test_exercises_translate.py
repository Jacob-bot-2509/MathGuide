"""双语翻译流水线:公式占位、数字校验、译文写回。"""
from __future__ import annotations

import asyncio

import pytest

from exercises import schema
from exercises.translate import (
    TranslationError,
    extract_math,
    restore_math,
    translate_exercise,
    translate_exercise_async,
    validate_translation,
)


def make_exercise():
    data = {
        "id": "translate:1",
        "source": {
            "name": "Test",
            "tier": "research",
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test Source",
        },
        "original_language": "en",
        "content": {
            "en": {
                "question": "Compute the value of $x+1$ when $x=1$.",
                "answer": "2",
                "solution": "Substitute $x=1$ into $x+1$ to get $2$. Therefore the answer is 2.",
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
    return schema.parse_exercise(data)


def fake_translator(text: str, source: str, target: str) -> str:
    return ("中文翻译 " if target == "zh" else "English translation ") + text


def test_extract_and_restore_math_round_trip():
    text = "Solve $x+1$ and $$y=2$$ with \\(z\\) and \\[w\\]."
    template, placeholders = extract_math(text)

    assert "[[M1]]" in template
    assert len(placeholders) == 4
    assert "$x+1$" in placeholders
    assert "$$y=2$$" in placeholders
    assert restore_math(template, placeholders) == text


def test_validate_rejects_missing_placeholder():
    template, placeholders = extract_math("Compute $x+1$.")
    check = validate_translation(
        "Compute [[M1]].",
        "计算 x+1。",
        placeholders,
        "zh",
    )

    assert check.ok is False
    assert any("placeholder" in reason for reason in check.reasons)


def test_validate_rejects_changed_number():
    _, placeholders = extract_math("Compute $x+1$ when x=2.")
    check = validate_translation(
        "Compute [[M1]] when x=2.",
        "计算 [[M1]] 当 x=3。",
        placeholders,
        "zh",
    )

    assert check.ok is False
    assert any("number" in reason for reason in check.reasons)


def test_validate_allows_math_only_answer_without_target_language():
    check = validate_translation(
        r"\frac{1}{4}",
        r"\frac{1}{4}",
        (),
        "zh",
    )

    assert check.ok is True


def test_validate_allows_latex_only_solution():
    source = (
        r"\begin{align*} f(f(f(f(512)))) &=f(f(f(-8)))\\ &=f(64)\\ "
        r"&=f(-4)\\ &=\boxed{16}. \end{align*}"
    )
    check = validate_translation(source, source, (), "zh")

    assert check.ok is True


def test_validate_allows_unit_only_answer():
    check = validate_translation(r"25 \text{ ft}", r"25 \text{ ft}", (), "zh")

    assert check.ok is True


def test_validate_treats_chinese_numerals_as_same_number():
    _, placeholders = extract_math("How many 3-digit numbers have a triple final digit?")
    check = validate_translation(
        "How many 3-digit numbers have a triple final digit?",
        "有多少个三位数，其首位数字是末位数字的三倍？",
        placeholders,
        "zh",
    )

    assert check.ok is True


def test_validate_allows_explanatory_extra_numbers():
    _, placeholders = extract_math(
        "There is a total of 20 quarters stacked in four piles."
    )
    check = validate_translation(
        "There is a total of 20 quarters stacked in four piles.",
        "共有20个25美分硬币堆成四堆。",
        placeholders,
        "zh",
    )

    assert check.ok is True


def test_validate_still_rejects_lost_number():
    _, placeholders = extract_math("There are 20 quarters in the pile.")
    check = validate_translation(
        "There are 20 quarters in the pile.",
        "这堆里有25枚硬币。",
        placeholders,
        "zh",
    )

    assert check.ok is False
    assert "number_mismatch" in check.reasons


def test_validate_allows_shorter_chinese_translation():
    _, placeholders = extract_math(
        "Two different 2-digit numbers are randomly chosen and multiplied "
        "together. What is the probability that the resulting product is even?"
    )
    check = validate_translation(
        "Two different 2-digit numbers are randomly chosen and multiplied "
        "together. What is the probability that the resulting product is even?",
        "随机选择两个不同的两位数并将它们相乘。所得乘积为偶数的概率是多少？",
        placeholders,
        "zh",
    )

    assert check.ok is True


def test_validate_rejects_untranslated_prose():
    _, placeholders = extract_math("Compute the value of x when x=2.")
    check = validate_translation(
        "Compute the value of [[M1]] when x=2.",
        "Compute the value of [[M1]] when x=2.",
        placeholders,
        "zh",
    )

    assert check.ok is False
    assert "target_language_mismatch" in check.reasons


def test_validate_allows_compact_chinese_question():
    source = (
        "What is the sum, in degrees, of the measures of the interior angles "
        "in the convex hexagon shown?"
    )
    check = validate_translation(source, "如图所示的凸六边形的内角和是多少度？", (), "zh")

    assert check.ok is True


def test_validate_ignores_latex_wrapper_in_length_ratio():
    check = validate_translation(r"\text{circle}", "圆", (), "zh")

    assert check.ok is True


def test_validate_treats_base_numerals_as_numbers():
    source = (
        "When the base 10 integer 269 is converted to base 5, what is the "
        "sum of the digits?"
    )
    check = validate_translation(
        source,
        "当十进制整数 269 转换为五进制时，其各位数字之和是多少？",
        (),
        "zh",
    )

    assert check.ok is True


def test_translate_exercise_adds_machine_translation():
    exercise = make_exercise()

    translated = translate_exercise(exercise, "zh", fake_translator, model="fake-model")

    assert translated.available_languages == ("en", "zh")
    assert translated.content["zh"].translation.status == "machine"
    assert translated.content["zh"].translation.reviewed is False
    assert "[[M1]]" not in translated.content["zh"].question
    assert "$x+1$" in translated.content["zh"].question


def test_translate_exercise_rejects_bad_translation():
    exercise = make_exercise()

    def broken(text: str, source: str, target: str) -> str:
        return "中文翻译"

    with pytest.raises(TranslationError) as excinfo:
        translate_exercise(exercise, "zh", broken, model="fake")

    assert any("placeholder" in reason for reason in excinfo.value.reasons)


def test_translate_exercise_does_not_mutate_original():
    exercise = make_exercise()

    translate_exercise(exercise, "zh", fake_translator, model="fake")

    assert exercise.available_languages == ("en",)
    assert "zh" not in exercise.content


def test_translate_exercise_async_adds_machine_translation():
    exercise = make_exercise()

    async def fake(text: str, source: str, target: str) -> str:
        return ("中文翻译 " if target == "zh" else "English translation ") + text

    translated = asyncio.run(
        translate_exercise_async(exercise, "zh", fake, model="fake-async")
    )

    assert translated.available_languages == ("en", "zh")
    assert translated.content["zh"].translation.status == "machine"
    assert translated.content["zh"].translation.model == "fake-async"
