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


MAX_CANDIDATES = 8   # 只精排规则分最高的前若干条,候选越多模型越慢、收益越低


def _build_prompt(question: str, candidates: list[SearchHit]) -> str:
    """紧凑形态:只回编号→分数,不要理由——理由字段会把输出拉长数倍,
    实测同一批候选从 20s 降到数秒,而排序结论几乎不变"""
    lines = [f"问题:{question}", "", "候选资料(编号 | 标题 | 摘要):"]
    for i, h in enumerate(candidates, 1):
        lines.append(f"[{i}] {h.title} | {h.snippet[:200]}")
    lines.append("")
    lines.append('给每条候选与问题的相关性打 0~100 的整数分,只输出 JSON 对象,'
                 '形如 {"1": 88, "2": 12};不要解释、不要换行。只依据给出的信息判断,不要猜测。')
    return "\n".join(lines)


def _parse(text: str, n: int) -> list[float]:
    """解析模型返回的打分(对象 {"1": 88} 或数组 [{"id":1,"score":88}]);失败抛错"""
    m = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
    if not m:
        raise ValueError("no json")
    data = json.loads(m.group(0))
    scores = [50.0] * n
    if isinstance(data, dict):
        for k, v in data.items():
            idx = int(str(k).strip()) - 1
            if 0 <= idx < n:
                scores[idx] = float(v)
        return scores
    if isinstance(data, list):
        for pos, item in enumerate(data, 1):
            if isinstance(item, dict):
                idx = int(item.get("id", pos)) - 1
                if 0 <= idx < n:
                    scores[idx] = float(item.get("score", 50))
            else:
                if pos <= n:
                    scores[pos - 1] = float(item)
    return scores


async def rerank(question: str, candidates: list[SearchHit],
                 role: str = "main", timeout: float = 10.0) -> list[SearchHit]:
    """返回混合打分后的候选(顺序可能变化;失败时原样返回)。
    只精排前 MAX_CANDIDATES 条:候选越少越快,尾部候选本来也不会进 top_k"""
    if len(candidates) < 2 or not llm.is_configured(role):
        return candidates
    head, tail = candidates[:MAX_CANDIDATES], candidates[MAX_CANDIDATES:]
    candidates = head
    try:
        # 注意:stream_chat 是异步生成器,必须包成协程再交给 wait_for
        # (直接 wait_for(生成器) 会抛 TypeError,精排静默失效)
        async def _collect() -> str:
            parts: list[str] = []
            async for delta in llm.stream_chat(
                    "你是检索结果的相关性评审。只输出要求的 JSON,不要其他内容。",
                    _build_prompt(question, candidates), role=role, fallback=False):
                parts.append(delta)
            return "".join(parts)

        raw = await asyncio.wait_for(_collect(), timeout=timeout)
        llm_scores = _parse(raw, len(candidates))
    except Exception as exc:  # noqa: BLE001 精排失败退化为纯规则排序
        print(f"[rerank] 精排失败,回退规则排序: {type(exc).__name__} {exc}")
        return head + tail
    for h, s in zip(head, llm_scores):
        h.score = round(h.score * 0.5 + s * 0.05, 2)  # 规则分×0.5 + LLM分(0~100→0~5)×0.5
    head.sort(key=lambda h: -h.score)
    return head + tail
