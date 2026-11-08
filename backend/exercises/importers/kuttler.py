"""Kuttler 线性代数导入器:LibreTexts 习题页的题干 + Answer 块。

教材以证明/说明题为主,Answer 块常直接给完整论证。只导入能确定题型的题:
证明题答案记为 Proof;是非题取 Yes/No;需要人工核验数值答案的题暂不导入。
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..schema import Source
from ..tagging import apply_tags
from .common import ImportSkip, finalize, make_exercise

SOURCE = Source(
    name="Kuttler",
    tier="research",
    license="CC BY 4.0",
    url="https://math.libretexts.org/Bookshelves/Linear_Algebra/"
        "A_First_Course_in_Linear_Algebra_(Kuttler)",
    attribution="Ken Kuttler / Lyryx, A First Course in Linear Algebra (LibreTexts)",
    license_scope="dataset",
)

_NUMBER_RE = re.compile(r"PageIndex\{(\d+)\}")
_PROOF_RE = re.compile(
    r"\b(show that|show this|show it|prove|explain|verify|justify)\b", re.I
)
_COMPUTE_RE = re.compile(
    r"\b(compute|calculate|find|determine|solve|evaluate|multiply)\b", re.I
)
_YESNO_ANSWER_RE = re.compile(r"^(yes|no)\b", re.I)

_BASE = (
    "https://math.libretexts.org/Bookshelves/Linear_Algebra/"
    "A_First_Course_in_Linear_Algebra_(Kuttler)/"
)
PAGES = {
    "m2": (_BASE + "02%3A_Matrices/2.E%3A_Exercises", ""),
    "r4": (_BASE + "04%3A_R/4.E%3A_Exercises", ""),
    "lt5": (_BASE + "05%3A_Linear_Transformations/5.E%3A_Exercises", ""),
    "cn6": (_BASE + "06%3A_Complex_Numbers/6.0E%3A_6.E%3A_Exercises", ""),
    "st7": (_BASE + "07%3A_Spectral_Theory/7.E%3A_Exercises", "orthogonal-transform"),
    "vs9": (_BASE + "09%3A_Vector_Spaces/9.E%3A_Exercises", "vector-space"),
}


def _text(node) -> str:
    if node is None:
        return ""
    clone = BeautifulSoup(str(node), "html.parser")
    for tag in clone.select(".autopermalink,.heading,summary,.box-legend,h2,h1"):
        tag.decompose()
    return clone.get_text(" ", strip=True)


def _statement(section) -> str:
    clone = BeautifulSoup(str(section), "html.parser")
    for tag in clone.select("dl,details,.autopermalink,.heading,.box-legend,h2,h1"):
        tag.decompose()
    value = " ".join(clone.get_text(" ", strip=True).split())
    return re.sub(r"^Exercise\s*\\\(\\PageIndex\{\d+\}\\\)\s*", "", value)


def _number(section) -> str:
    heading = section.select_one("h2, .box-legend")
    match = _NUMBER_RE.search(heading.get_text(" ", strip=True) if heading else "")
    return match.group(1) if match else ""


def parse_page(html: str, page_url: str, cross_topic: str, prefix: str):
    """解析一页;返回 (练习题列表, 跳过原因计数)。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    skipped: dict[str, int] = {}
    for section in soup.select("section.box-exercise"):
        question = _statement(section)
        answer_block = section.select_one("dl dd")
        solution = _text(answer_block)
        number = _number(section)
        if not question or not solution or not number:
            skipped["missing_block"] = skipped.get("missing_block", 0) + 1
            continue

        lowered = question.lower()
        proofish = "is this a vector space" in lowered or "explain why or why not" in lowered
        if proofish or (_PROOF_RE.search(question) and not _COMPUTE_RE.search(question)):
            exercise_type, answer = "proof", "Proof"
        elif _YESNO_ANSWER_RE.match(solution) and re.search(
            r"\b(is|are|can|does|do)\b", question, re.I
        ):
            match = _YESNO_ANSWER_RE.match(solution)
            if not match:
                skipped["answer_not_extractable"] = (
                    skipped.get("answer_not_extractable", 0) + 1
                )
                continue
            exercise_type, answer = "apply", match.group(1).capitalize()
        else:
            skipped["answer_not_extractable"] = (
                skipped.get("answer_not_extractable", 0) + 1
            )
            continue

        try:
            exercise = make_exercise(
                exercise_id=f"kuttler:{prefix}:{number}",
                source=SOURCE,
                language="en",
                question=question,
                answer=answer,
                solution=solution,
                exercise_type=exercise_type,
                difficulty=4 if exercise_type == "proof" else 3,
                primary_topic="algebra",
                cross_topics=((cross_topic,) if cross_topic else ()),
            )
            exercise = finalize(apply_tags(exercise))
        except ImportSkip as exc:
            skipped[str(exc)] = skipped.get(str(exc), 0) + 1
            continue
        items.append(exercise)
    return items, skipped
