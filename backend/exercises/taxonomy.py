"""习题板块与交叉知识点词表。

板块 key 与前端分类器保持一致;交叉项沿用 34 条登记表 id。
本模块只放常量与校验,不依赖 schema,避免循环引用。
"""
from __future__ import annotations

from collections.abc import Iterable

CATEGORY_KEYS: tuple[str, ...] = (
    "analysis",
    "algebra",
    "geometry",
    "ode",
    "probability",
    "complex",
    "numberTheory",
    "topology",
)

CROSS_TOPIC_IDS: tuple[str, ...] = (
    "least-squares",
    "eigen",
    "quadratic-form",
    "orthogonal-transform",
    "vector-space",
    "inner-product",
    "fourier-series",
    "fourier-transform",
    "laplace-transform",
    "taylor",
    "residue",
    "power-series",
    "euler-formula",
    "cauchy-riemann",
    "green-theorem",
    "divergence-theorem",
    "stokes-theorem",
    "vector-calculus",
    "line-surface-integral",
    "jacobian",
    "implicit-function",
    "quadric-surface",
    "norm",
    "convolution",
    "generating-function",
    "markov-chain",
    "matrix-exponential",
    "ode-system",
    "prime-number-theorem",
    "riemann-zeta",
    "analytic-number-theory",
    "variational",
    "green-function",
    "parseval",
)

_CATEGORY_SET = frozenset(CATEGORY_KEYS)
_CROSS_SET = frozenset(CROSS_TOPIC_IDS)


class TaxonomyError(ValueError):
    """板块或交叉知识点不合法。"""


def unique(values: Iterable[str]) -> tuple[str, ...]:
    """按首次出现顺序去重,保持导入结果稳定。"""
    return tuple(dict.fromkeys(values))


def validate_topics(
    primary: str,
    topics: Iterable[str],
    cross_topics: Iterable[str] = (),
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """校验并返回去重后的 (topics, cross_topics)。"""
    normalized = unique(topics)
    if not normalized:
        raise TaxonomyError("topics 不能为空")
    unknown = [item for item in normalized if item not in _CATEGORY_SET]
    if unknown:
        raise TaxonomyError(f"未知 topic: {unknown[0]}")
    if primary not in _CATEGORY_SET:
        raise TaxonomyError(f"未知 primary topic: {primary}")
    if primary not in normalized:
        raise TaxonomyError(f"primary topic {primary} 不在 topics 中")

    cross = unique(cross_topics)
    unknown_cross = [item for item in cross if item not in _CROSS_SET]
    if unknown_cross:
        raise TaxonomyError(f"未知 cross topic: {unknown_cross[0]}")
    return normalized, cross
