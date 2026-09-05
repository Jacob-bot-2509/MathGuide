"""
检索索引:关键词 + 标题 + 字符二元组重合度打分(纯标准库,零依赖)。

可选 embedding 混合打分:配置 MG_EMBED_*(见 embed.py)后,
向量相似度与关键词打分混合排序,语义化提问召回率大幅提升;
未配置时行为与纯关键词模式完全一致。
"""
import re
from typing import Optional

from .documents import Chunk
from .embed import Embedder

# 打分权重:关键词命中 > 标题重合 > 正文 bigram 重合
W_KEYWORD = 3.0
W_TITLE = 2.0
W_BODY = 1.0
# 向量相似度权重(embedding 启用时生效)
W_VECTOR = 5.0
# 混合模式下:向量相似度低于此值且无关键词命中 → 视为无关
MIN_COSINE = 0.25
# 低于该分数视为"没检索到相关知识",走兜底回复;
# 需 ≥2 个正文二元组重合(或 1 个标题重合/关键词命中)才算相关,避免「怎么」这类泛词误命中
MIN_SCORE = 1.5

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _bigrams(text: str) -> set[str]:
    """提取小写字符二元组(中英混排直接按相邻字符切)"""
    s = re.sub(r"\s+", "", text.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


class KnowledgeIndex:
    def __init__(self, chunks: list[Chunk], embedder: Optional[Embedder] = None):
        # 预计算每个 chunk 的标题/正文 bigram(检索时不再重复切分)
        self._entries = [
            (c, _bigrams(c.title + c.title_en), _bigrams(c.text)) for c in chunks
        ]
        self._embedder = embedder
        self._vectors: list[Optional[list[float]]] = [None] * len(chunks)
        if embedder is not None:
            self._vectors = embedder.embed_chunks([(c.id, f"{c.title} {c.title_en} {c.text}") for c in chunks])

    def _keyword_score(self, chunk: Chunk, q: str) -> float:
        score = 0.0
        for kw in chunk.keywords:
            if kw and kw in q:
                score += W_KEYWORD
        for tok in _TOKEN_RE.findall(q):
            if len(tok) >= 3 and tok in chunk.keywords:
                score += W_KEYWORD * 0.5
        return score

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        q = query.lower()
        q_grams = _bigrams(q)
        q_vec = self._embedder.embed_query(query) if self._embedder is not None else None

        scored: list[tuple[Chunk, float]] = []
        for i, (c, title_grams, body_grams) in enumerate(self._entries):
            kw = self._keyword_score(c, q)
            score = kw
            score += W_TITLE * len(q_grams & title_grams)
            score += W_BODY * len(q_grams & body_grams)

            if self._embedder is not None and q_vec is not None and self._vectors[i] is not None:
                cosine = Embedder.cosine(q_vec, self._vectors[i])
                # 语义匹配门限:向量弱相关且无关键词命中 → 视为无关,防止低相似度抬分
                if cosine < MIN_COSINE and kw < W_KEYWORD:
                    continue
                score += W_VECTOR * cosine

            if score >= MIN_SCORE:
                scored.append((c, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]
