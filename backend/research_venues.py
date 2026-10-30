"""场所权威 registry:ISSN 优先匹配,返回学科内的 T0/T1/T2/T3。

registry 是人工维护的种子表,不是 JCR/中科院分区的复制品;
没有匹配到的场所不猜级别,由调用方按来源类型降级为 T3/P/U。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "registry" / "venues.json"

TIER_RANK = {"T0": 5, "T1": 4, "T2": 3, "T3": 2, "P": 1, "U": 0}


def normalize_issn(value: object) -> str:
    text = re.sub(r"[^0-9Xx]", "", str(value or "")).upper()
    return text if len(text) == 8 else ""


def normalize_name(value: object) -> str:
    text = str(value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"^the\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _registry() -> tuple[dict[str, dict], dict[str, dict], str]:
    payload = json.loads(_DATA.read_text(encoding="utf-8"))
    by_issn: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for venue in payload.get("venues", []):
        if not isinstance(venue, dict):
            continue
        for raw in venue.get("issn", []):
            issn = normalize_issn(raw)
            if issn:
                by_issn[issn] = venue
        names = [venue.get("name"), *(venue.get("aliases") or [])]
        for name in names:
            key = normalize_name(name)
            if key:
                by_name[key] = venue
    return by_issn, by_name, str(payload.get("version") or "")


def registry_version() -> str:
    return _registry()[2]


def lookup(issns: list[str] | tuple[str, ...] | None = None,
           name: str = "") -> dict | None:
    by_issn, by_name, _ = _registry()
    for raw in issns or []:
        hit = by_issn.get(normalize_issn(raw))
        if hit:
            return hit
    return by_name.get(normalize_name(name)) if name else None


def tier_for(venue: dict | None, field: str) -> str:
    if not venue:
        return ""
    tiers = venue.get("tiers") if isinstance(venue.get("tiers"), dict) else {}
    if field in tiers:
        return str(tiers[field])
    if "general" in tiers:
        return str(tiers["general"])
    return ""


def peer_reviewed(venue: dict | None) -> bool:
    return bool(venue.get("peer_reviewed")) if venue else False


def label(venue: dict | None) -> str:
    if not venue:
        return ""
    publisher = str(venue.get("publisher") or "")
    return str(venue.get("name") or "") + (f" · {publisher}" if publisher else "")


def rank(tier: str) -> int:
    return TIER_RANK.get(tier, 0)
