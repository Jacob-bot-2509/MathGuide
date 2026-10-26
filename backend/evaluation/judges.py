"""LLM 评审:判正确性 + 拆断言判是否有依据。

注意:评审模型必须与生成模型不同源(默认 backup/glm),否则是自评。
评审结果只是"模型判分",论文里必须再用人工盲标校准 kappa。
"""
from __future__ import annotations

import json
import re

from rag import llm

from .types import ChunkTrace, EvalItem

JUDGE_SYSTEM = (
    "你是严格的数学评测员。给定题目、标准答案、检索资料和待评答案,只输出一个 JSON 对象,"
    "不要 Markdown、不要解释。字段:\n"
    "{\n"
    '  "correct": true/false,\n'
    '  "score": 0 | 0.5 | 1,\n'
    '  "refused": true/false,\n'
    '  "claims": [{"text": "关键断言", "supported": true/false, "reason": "依据"}],\n'
    '  "rationale": "一句话"\n'
    "}\n"
    "规则:\n"
    "1. correct 表示最终结论是否与标准答案一致;等价形式也算正确。\n"
    "2. refused 表示待评答案是否明确拒答或声明资料不足。\n"
    "3. claims 取最多 8 条关键断言;supported 仅当该断言能被标准答案或检索资料直接支持,"
    "或属于题目给出的条件。无依据、与资料矛盾、把猜测说成事实,都记 false。"
    "不得以「数学常识」「众所周知」为由判 supported:标准答案和检索资料都没写的,一律 false。\n"
    "4. 标准答案为空(不可答题)时,correct 表示是否恰当拒答;不要因为答案看起来合理就判正确。\n"
    "5. 计算错误但没编造事实:correct=false,但对应断言的 supported 仍可为 true。\n"
)


def _context(chunks: list[ChunkTrace], limit: int = 3, per_chunk: int = 700) -> str:
    if not chunks:
        return "(无检索资料)"
    parts = []
    for i, c in enumerate(chunks[:limit], 1):
        parts.append(f"[{i}] {c.title} · {c.section}\n{c.text[:per_chunk]}")
    return "\n\n".join(parts)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("评审输出不含 JSON 对象")
    data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("评审输出不是 JSON 对象")
    return data


def _normalize(data: dict, item: EvalItem) -> dict:
    claims = []
    raw_claims = data.get("claims")
    if isinstance(raw_claims, list):
        for c in raw_claims[:12]:
            if not isinstance(c, dict):
                continue
            text = str(c.get("text", "")).strip()
            if not text:
                continue
            claims.append({
                "text": text[:300],
                "supported": bool(c.get("supported", False)),
                "reason": str(c.get("reason", ""))[:200],
            })
    correct = data.get("correct")
    if not isinstance(correct, bool):
        correct = None
    if not item.answerable and isinstance(data.get("refused"), bool):
        # 不可答题:正确 = 明确拒答
        correct = bool(data["refused"])
    return {
        "correct": correct,
        "score": data.get("score") if data.get("score") in (0, 0.5, 1, 0.0, 1.0) else None,
        "refused": bool(data.get("refused")) if isinstance(data.get("refused"), bool) else None,
        "claims": claims,
        "rationale": str(data.get("rationale", ""))[:300],
    }


async def judge_answer(item: EvalItem, answer: str, chunks: list[ChunkTrace],
                       role: str = "backup") -> dict:
    """返回评审 JSON;失败时返回 {"error": ...},调用方需计入 judge_errors。"""
    if not llm.is_configured(role):
        return {"error": f"评审角色 {role} 未配置"}
    prompt = (
        f"题目:\n{item.question}\n\n"
        f"标准答案:\n{item.reference_answer or '(不可答题,无标准答案)'}\n\n"
        f"检索资料:\n{_context(chunks)}\n\n"
        f"待评答案:\n{answer[:3000]}"
    )
    parts: list[str] = []
    try:
        async for delta in llm.stream_chat(JUDGE_SYSTEM, prompt, role=role,
                                           fallback=False, thinking=False,
                                           max_tokens=1200):
            parts.append(delta)
    except Exception as exc:  # noqa: BLE001 评审失败不伪造结果
        return {"error": f"{type(exc).__name__}: {exc}"}
    try:
        return _normalize(_parse_json("".join(parts)), item)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"评审输出解析失败: {type(exc).__name__}: {exc}",
                "raw": "".join(parts)[:500]}
