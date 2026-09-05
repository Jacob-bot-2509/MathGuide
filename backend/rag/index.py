"""
检索索引:关键词 + 标题 + 字符二元组重合度打分(纯标准库,零依赖)。

中文未分词场景下,字符 bigram 重合度是廉价且有效的相关性度量;
接入 embedding 服务后可在本文件替换/叠加向量打分,接口不变(search 签名保持)。
"""
import re

from .documents import Chunk

# 打分权重:关键词命中 > 标题重合 > 正文 bigram 重合
W_KEYWORD = 3.0
W_TITLE = 2.0
W_BODY = 1.0
# 低于该分数视为"没检索到相关知识",走兜底回复;
# 需 ≥2 个正文二元组重合(或 1 个标题重合/关键词命中)才算相关,避免「怎么」这类泛词误命中
MIN_SCORE = 1.5

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _bigrams(text: str) -> set[str]:
    """提取小写字符二元组(中英混排直接按相邻字符切)"""
    s = re.sub(r"\s+", "", text.lower())
    return {s[i:i + 2] for i in range(len(s) - 1)}


class KnowledgeIndex:
    def __init__(self, chunks: list[Chunk]):
        # 预计算每个 chunk 的标题/正文 bigram(检索时不再重复切分)
        self._entries = [
            (c, _bigrams(c.title + c.title_en), _bigrams(c.text)) for c in chunks
        ]

    def search(self, query: str, top_k: int = 3) -> list[tuple[Chunk, float]]:
        q = query.lower()
        q_grams = _bigrams(q)
        scored: list[tuple[Chunk, float]] = []
        for c, title_grams, body_grams in self._entries:
            score = 0.0
            # 关键词/英文词直接命中
            for kw in c.keywords:
                if kw and kw in q:
                    score += W_KEYWORD
            for tok in _TOKEN_RE.findall(q):
                if len(tok) >= 3 and tok in c.keywords:
                    score += W_KEYWORD * 0.5
            # 标题与正文的重合度
            score += W_TITLE * len(q_grams & title_grams)
            score += W_BODY * len(q_grams & body_grams)
            if score >= MIN_SCORE:
                scored.append((c, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]
