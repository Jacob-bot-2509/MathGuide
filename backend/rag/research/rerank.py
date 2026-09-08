"""
LLM 精排(执行表 P2b):对粗排候选做语义相关性打分,与规则分混合。

- 列表式单次调用(8 条候选一次问完,输出严格 JSON),控制成本与延迟;
- 混合分 = 规则分 × 0.5 + LLM 分 × 0.5,保留规则信号的稳定性;
- LLM 不可用/超时/解析失败 → 返回原列表(纯规则排序,行为与 P1 一致)。
"""
import asyncio
import json
import re

from rag import llm

from .types import SearchHit


def _build_prompt(question: str, candidates: list[SearchHit]) -> str:
    lines = [f"题目:{question}", "", "以下是检索到的候选资料,请逐条判断与题目的相关性,"
             "输出严格 JSON 数组,每项 {\"id\": 编号, \"score\": 0~100 的整数, \"reason\": 一句话理由}。"
             "只依据给出的信息判断,不要猜测。", ""]
    for i, h in enumerate(candidates, 1):
        lines.append(f"[{i}] {h.title} | {h.snippet[:300]}")
    lines.append("")
    lines.append("JSON:")
    return "\n".join(lines)


def _parse(text: str, n: int) -> list[float]:
    """解析模型返回的 JSON 数组;失败返回全 50(中性分)"""
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        raise ValueError("no json array")
    data = json.loads(m.group(0))
    scores: list[float] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("bad item")
        scores.append(float(item.get("score", 50)))
    while len(scores) < n:
        scores.append(50.0)
    return scores[:n]


async def rerank(question: str, candidates: list[SearchHit],
                 role: str = "main", timeout: float = 8.0) -> list[SearchHit]:
    """返回混合打分后的候选(顺序可能变化,数量不变;失败时原样返回)"""
    if len(candidates) < 2 or not llm.is_configured(role):
        return candidates
    try:
        raw = ""
        async for delta in asyncio.wait_for(
            llm.stream_chat(
                "你是检索结果的相关性评审。只输出要求的 JSON,不要其他内容。",
                _build_prompt(question, candidates), role=role, fallback=False),
            timeout=timeout):
            raw += delta
        llm_scores = _parse(raw, len(candidates))
    except Exception as exc:  # noqa: BLE001 精排失败退化为纯规则排序
        print(f"[rerank] 精排失败,回退规则排序: {exc}")
        return candidates
    for h, s in zip(candidates, llm_scores):
        h.score = round(h.score * 0.5 + s * 0.05, 2)  # 规则分×0.5 + LLM分(0~100→0~5)×0.5
    candidates.sort(key=lambda h: -h.score)
    return candidates
