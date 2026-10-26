"""评测集加载与校验。

JSONL 每行一条,最小字段:
    {"id": "...", "question": "...", "reference_answer": "...",
     "answer_type": "concept|numeric|expr|choice|proof|unanswerable",
     "domain": "...", "difficulty": 1,
     "gold_chunk_ids": ["03-taylor#1"],
     "answerable": true}

`gold_chunk_ids` 留空时不参与召回率统计；不可答题用 `answerable: false`
且 `reference_answer` 留空。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .types import EvalItem

ANSWER_TYPES = {"concept", "numeric", "expr", "choice", "proof", "unanswerable"}


def _as_str(value: object, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _as_int(value: object, default: int = 1) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_item(raw: dict, line_no: int = 0) -> EvalItem:
    item_id = _as_str(raw.get("id")) or f"line-{line_no}"
    question = _as_str(raw.get("question"))
    if not question:
        raise ValueError(f"{item_id}: question 为空")
    answer_type = _as_str(raw.get("answer_type"), "concept") or "concept"
    if answer_type not in ANSWER_TYPES:
        raise ValueError(f"{item_id}: answer_type 非法: {answer_type}")
    answerable = raw.get("answerable", True)
    if not isinstance(answerable, bool):
        answerable = True
    gold = raw.get("gold_chunk_ids") or []
    if not isinstance(gold, list):
        gold = []
    tags = raw.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return EvalItem(
        id=item_id,
        question=question,
        reference_answer=_as_str(raw.get("reference_answer")),
        answer_type=answer_type,
        domain=_as_str(raw.get("domain"), "other") or "other",
        difficulty=_as_int(raw.get("difficulty")),
        answerable=answerable,
        gold_chunk_ids=[str(x) for x in gold if str(x).strip()],
        tags=[str(x) for x in tags if str(x).strip()],
    )


def load_items(path: str | Path) -> list[EvalItem]:
    """读取 JSONL;坏行直接报错并指出行号,不静默跳过。"""
    items: list[EvalItem] = []
    seen: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} 不是合法 JSON: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"{path}:{line_no} 必须是 JSON 对象")
            item = parse_item(raw, line_no)
            if item.id in seen:
                raise ValueError(f"{path}:{line_no} id 重复: {item.id}")
            seen.add(item.id)
            items.append(item)
    return items


def dataset_hash(items: list[EvalItem]) -> str:
    """数据集指纹:内容或顺序变化都会变,用于报告里标记不可直接比较的两次运行。"""
    payload = [
        {
            "id": i.id,
            "question": i.question,
            "reference_answer": i.reference_answer,
            "answer_type": i.answer_type,
            "answerable": i.answerable,
            "gold_chunk_ids": i.gold_chunk_ids,
        }
        for i in items
    ]
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]
