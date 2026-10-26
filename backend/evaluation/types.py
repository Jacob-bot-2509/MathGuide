"""评测数据与结果类型(供 runner / metrics / report 共用,避免各写一套字段)。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalItem:
    """一条评测样本。reference_answer 为空表示不可答题。"""

    id: str
    question: str
    reference_answer: str = ""
    answer_type: str = "concept"   # concept / numeric / expr / choice / proof / unanswerable
    domain: str = "other"
    difficulty: int = 1
    answerable: bool = True
    gold_chunk_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class ChunkTrace:
    """检索到的片段(只保留评测需要的字段)。"""

    id: str
    title: str
    section: str
    score: float
    text: str = ""


@dataclass
class AnswerTrace:
    """一次生产链路调用的结果。"""

    text: str
    meta: dict = field(default_factory=dict)
    chunks: list[ChunkTrace] = field(default_factory=list)
    latency_s: float = 0.0
    degraded: bool = False
    error: str = ""
