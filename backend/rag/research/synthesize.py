"""
LLM 综合(执行表 P2c):基于检索到的来源生成带编号引用的解答。

幻觉防线:
- 引用编号 [1][2][3] 仅映射到后端注入的真实来源,系统提示词禁止编造;
- 引用区(参考来源)由后端用 SearchHit 真实元数据拼装,不经过模型输出,
  标题/作者/链接绝不可能是模型编的。
"""
from typing import AsyncIterator

from rag import llm

from .types import SearchHit

SYSTEM_ZH = (
    "你是 MathGuide 的研究助理,负责基于文献资料回答研究型问题。\n"
    "规则:\n"
    "1. 仅依据下方【资料】回答,每条关键结论在句末标注来源编号,如[1]、[2][3];\n"
    "2. 资料不足以回答时,如实说明\"现有资料不足以回答\",不得编造内容或引用;\n"
    "3. 数学公式使用 LaTeX(行内 $...$,块级 $$...$$);\n"
    "4. 回答用简体中文,结构:先给结论,再分点展开,最后一段为小结;\n"
    "5. 不要输出\"参考来源\"列表,引用区由系统自动附加。"
)
SYSTEM_EN = (
    "You are MathGuide's research assistant. Answer based ONLY on the provided sources.\n"
    "Rules:\n"
    "1. Cite every key claim with source numbers like [1] or [2][3];\n"
    "2. If the sources are insufficient, say so honestly — never fabricate;\n"
    "3. Use LaTeX for formulas (inline $...$, display $$...$$);\n"
    "4. Reply in English; structure: conclusion first, then points, then a short summary;\n"
    "5. Do NOT print a reference list — the system appends it automatically."
)


def _user_prompt(question: str, hits: list[SearchHit]) -> str:
    lines = [f"问题:{question}", "", "【资料】"]
    for i, h in enumerate(hits, 1):
        meta = f"{h.authors} · {h.year}" if h.authors else str(h.year or "")
        lines.append(f"[{i}] 标题:{h.title}({h.source}{' · ' + meta if meta else ''})")
        lines.append(f"    摘要:{h.snippet[:400]}")
    return "\n".join(lines)


async def synthesize_stream(question: str, hits: list[SearchHit], zh: bool,
                            role: str = "main", fallback: bool = True) -> AsyncIterator[str]:
    """流式生成综合解答(正文);引用区由 citations_block 单独拼装"""
    system = SYSTEM_ZH if zh else SYSTEM_EN
    async for delta in llm.stream_chat(system, _user_prompt(question, hits), role=role, fallback=fallback):
        yield delta


def citations_block(hits: list[SearchHit], zh: bool) -> str:
    """引用区:后端用真实元数据拼装(不经模型,杜绝编造链接)。
    格式约定(前端 MathText 渲染):--- 分隔线 + > 引用块(小字醒目)+ [文字](链接)"""
    head = "参考来源:" if zh else "References:"
    lines = ["", "---", f"**{head}**"]
    for i, h in enumerate(hits, 1):
        meta = " · ".join(x for x in [h.authors, str(h.year) if h.year else "", h.source] if x)
        lines.append(f"> [{i}] {h.title} — {meta}")
        if h.url:
            lines.append(f"> [{h.url}]({h.url})")
    return "\n".join(lines)
