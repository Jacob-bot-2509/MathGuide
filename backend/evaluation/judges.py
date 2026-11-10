"""LLM 评审:判正确性 + 拆断言判是否有依据。

注意:评审模型必须与生成模型不同源(默认 backup/glm),否则是自评。
评审结果只是"模型判分",论文里必须再用人工盲标校准 kappa。
"""
from __future__ import annotations

import json
import re

import httpx

from rag import llm

from .types import ChunkTrace, EvalItem

JUDGE_SYSTEM = (
    "你是严格的数学评测员。给定题目、标准答案、检索资料和待评答案,只输出一个 JSON 对象,"
    "不要 Markdown、不要解释。字段:\n"
    "{\n"
    '  "correct": true/false,\n'
    '  "score": 0 | 0.5 | 1,\n'
    '  "refused": true/false,\n'
    '  "claims": [{"text": "关键断言", "supported": true/false/null, "reason": "依据"}],\n'
    '  "rationale": "一句话"\n'
    "}\n"
    "规则:\n"
    "1. correct 表示最终结论是否与标准答案一致;等价形式也算正确。\n"
    "2. refused 表示待评答案是否明确拒答或声明资料不足。\n"
    "3. claims 取最多 8 条关键断言。supported=true 表示被题目、标准解答或检索资料支持,"
    "或者可用明确的数学定义及推导验证;false 表示有明确矛盾或编造的依据;"
    "资料未提及、无法验证或不确定时必须为 null,不得仅因标准解答未逐字提及就判 false。"
    "reason 应说明依据或不确定原因。\n"
    "4. 标准答案为空(不可答题)时,correct 表示是否恰当处理:明确拒答、声明资料不足,"
    "或正确指出所请求的对象不存在、条件矛盾、题目超出可答范围,均判 true;"
    "编造一个不存在的对象、给出具体数值或构造,判 false。\n"
    "5. 单纯计算失误但没有编造事实时,correct=false;对应断言若无法归类为编造则 supported=null。\n"
    "6. 证明题必须给出足以推出结论的有效论证;仅复述结论或缺少关键证明步骤,correct=false。"
    "证明方法无需与标准解答相同,逻辑有效的其他方法也应认可。\n"
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
                "supported": c.get("supported") if isinstance(c.get("supported"), bool) else None,
                "reason": str(c.get("reason", ""))[:200],
            })
    correct = data.get("correct")
    if not isinstance(correct, bool):
        correct = None
    if not item.answerable and correct is None and isinstance(data.get("refused"), bool):
        # 兼容旧评审输出:只给了 refused 没给 correct 时,拒答视为恰当处理
        correct = bool(data["refused"])
    return {
        "correct": correct,
        "score": data.get("score") if data.get("score") in (0, 0.5, 1, 0.0, 1.0) else None,
        "refused": bool(data.get("refused")) if isinstance(data.get("refused"), bool) else None,
        "claims": claims,
        "claim_schema": "truth-v2",
        "rationale": str(data.get("rationale", ""))[:300],
    }


async def judge_answer(item: EvalItem, answer: str, chunks: list[ChunkTrace],
                       role: str = "backup", ground_truth_only: bool = False) -> dict:
    """返回评审 JSON;失败时返回 {"error": ...},调用方需计入 judge_errors。

    ground_truth_only=True 时不让检索片段参与判分:内部正确率集以标准解答为金标,
    无关片段不应给错误断言背书。"""
    if not any(llm.is_configured(r) for r in (role, "deep", "main")):
        return {"error": f"评审角色 {role} 未配置,且没有可回退的评审角色"}
    context = "(本次判分不使用检索资料)" if ground_truth_only else _context(chunks)
    solution = (
        f"\n标准解答:\n{item.reference_solution[:6000]}\n"
        if item.reference_solution else ""
    )
    prompt = (
        f"题目:\n{item.question}\n\n"
        f"标准答案:\n{item.reference_answer or '(不可答题,无标准答案)'}\n"
        f"{solution}"
        f"检索资料:\n{context}\n\n"
        f"待评答案:\n{answer[:8000]}"
    )
    last_error = "评审失败"
    last_raw = ""
    # 评审角色可能因平台未开通直接 401/403(实测 aliyun 备胎会这样);
    # 这种情况下换下一个已配置角色,不让整批评测因一个平台不可用而报废。
    roles = [role] + [alt for alt in ("deep", "main")
                      if alt != role and llm.is_configured(alt)]
    for candidate in roles:
        if not llm.is_configured(candidate):
            continue
        switch_role = False
        # 评审模型偶发超时或被 max_tokens 截断;重试一次,仍失败才换角色/计入 judge_errors
        for _ in range(2):
            parts: list[str] = []
            try:
                async for delta in llm.stream_chat(
                        JUDGE_SYSTEM, prompt, role=candidate,
                        fallback=False, thinking=False,
                        max_tokens=2000, temperature=0):
                    parts.append(delta)
            except Exception as exc:  # noqa: BLE001 评审失败不伪造结果
                last_error = f"{type(exc).__name__}: {exc}"
                if (isinstance(exc, httpx.HTTPStatusError)
                        and exc.response.status_code in (401, 403, 404)):
                    switch_role = True
                    break  # 该平台不可用,换下一个角色
                continue
            try:
                result = _normalize(_parse_json("".join(parts)), item)
                result["judge_role"] = candidate
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = f"评审输出解析失败: {type(exc).__name__}: {exc}"
                last_raw = "".join(parts)[:500]
        if not switch_role:
            break
    return {"error": last_error, "raw": last_raw}
