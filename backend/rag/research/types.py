"""深度搜索数据结构(执行表 P1)"""
from dataclasses import dataclass, field


@dataclass
class SearchHit:
    """一条搜索命中(来源元数据全部为 API 真实返回,绝不伪造)"""
    source: str              # arXiv / Semantic Scholar / StackExchange / 知识库
    title: str
    snippet: str = ""
    authors: str = ""
    year: int = 0
    url: str = ""
    citations: int = 0
    score: float = 0.0       # 排序后回填


@dataclass
class SearchOutcome:
    """一次深度搜索的完整结果(含来源统计与失败信息,便于如实呈现)"""
    question: str
    terms: list[str] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)   # 来源名 → 命中数
    errors: list[str] = field(default_factory=list)         # 失败来源说明
    elapsed: float = 0.0

    @property
    def any_hit(self) -> bool:
        return bool(self.hits)
