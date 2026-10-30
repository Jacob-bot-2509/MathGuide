"""文献来源注册表与学科路由。

只登记允许进入检索的来源;未登记来源不得出现在结果里。
每个来源声明:适用学科、权威层级、是否同行评审、是否需要 key、全文策略。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceSpec:
    id: str
    name: str
    domains: tuple[str, ...]
    tier: str                 # authority | discovery | preprint | repository
    peer_reviewed: bool
    requires_key: str = ""    # 可选/必需 key 的环境变量名
    key_required: bool = False
    fulltext: str = "landing"  # pdf | oa | landing | metadata


SPECS: dict[str, SourceSpec] = {
    "crossref": SourceSpec(
        "crossref", "Crossref",
        ("general", "math", "physics", "chemistry", "biology"),
        "authority", True),
    "arxiv": SourceSpec(
        "arxiv", "arXiv",
        ("general", "math", "physics", "chemistry", "biology"),
        "preprint", False, fulltext="pdf"),
    "europepmc": SourceSpec(
        "europepmc", "Europe PMC",
        ("general", "biology", "chemistry"),
        "authority", True, fulltext="oa"),
    "pubmed": SourceSpec(
        "pubmed", "PubMed",
        ("biology",),
        "authority", True, requires_key="MG_NCBI_API_KEY"),
    "inspire": SourceSpec(
        "inspire", "INSPIRE-HEP",
        ("physics",),
        "authority", True, fulltext="oa"),
    "ads": SourceSpec(
        "ads", "NASA ADS",
        ("physics",),
        "authority", True, requires_key="MG_ADS_API_KEY",
        key_required=True, fulltext="oa"),
    "zbmath": SourceSpec(
        "zbmath", "zbMATH Open",
        ("math",),
        "authority", True),
    "openalex": SourceSpec(
        "openalex", "OpenAlex",
        ("general", "math", "physics", "chemistry", "biology"),
        "discovery", False, requires_key="MG_OPENALEX_API_KEY",
        key_required=True, fulltext="oa"),
    "semanticscholar": SourceSpec(
        "semanticscholar", "Semantic Scholar",
        ("general", "math", "physics", "chemistry", "biology"),
        "discovery", False, requires_key="MG_S2_API_KEY", fulltext="oa"),
    "biorxiv": SourceSpec(
        "biorxiv", "bioRxiv / medRxiv",
        ("biology",),
        "preprint", False, fulltext="pdf"),
    "chemrxiv": SourceSpec(
        "chemrxiv", "ChemRxiv",
        ("chemistry",),
        "preprint", False, fulltext="landing"),
    "doaj": SourceSpec(
        "doaj", "DOAJ",
        ("general", "math", "physics", "chemistry", "biology"),
        "authority", True, fulltext="landing"),
}

ALL_FIELDS = ("general", "math", "physics", "chemistry", "biology")


def specs_for(field: str, include_preprints: bool) -> list[SourceSpec]:
    """按学科选来源;general 只取声明了 general 的跨学科来源。"""
    field = field if field in ALL_FIELDS else "general"
    out: list[SourceSpec] = []
    for spec in SPECS.values():
        if field == "general":
            if "general" not in spec.domains:
                continue
        elif field not in spec.domains:
            continue
        if spec.tier == "preprint" and not include_preprints:
            continue
        out.append(spec)
    return out


def source_tier(name: str) -> str:
    spec = SPECS.get(name)
    return spec.tier if spec else "unknown"


SOURCE_PRIORITY = {
    "zbmath": 3, "inspire": 3, "pubmed": 3, "ads": 2,
    "europepmc": 2, "crossref": 2,
    "arxiv": 1, "biorxiv": 1, "chemrxiv": 1,
    "openalex": 0, "semanticscholar": 0, "doaj": 0,
}


def source_priority(result: dict) -> int:
    return max((SOURCE_PRIORITY.get(str(s), 0) for s in result.get("sources") or []),
               default=0)
