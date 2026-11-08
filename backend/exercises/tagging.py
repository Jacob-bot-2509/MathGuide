"""交叉知识点规则标注:复用前端 34 条登记表的词面。"""
from __future__ import annotations

import re
from dataclasses import replace

from .schema import Exercise
from .taxonomy import CROSS_TOPIC_IDS

_PATTERNS: dict[str, re.Pattern[str]] = {
    "least-squares": re.compile(r"最小二乘|least squares?", re.I),
    "eigen": re.compile(r"特征值|特征向量|eigenvalue|eigenvector", re.I),
    "quadratic-form": re.compile(r"二次型|quadratic form", re.I),
    "orthogonal-transform": re.compile(r"正交变换|orthogonal transformation", re.I),
    "vector-space": re.compile(r"向量空间|线性空间|vector space", re.I),
    "inner-product": re.compile(r"内积|inner product", re.I),
    "fourier-series": re.compile(r"傅里叶级数|fourier series", re.I),
    "fourier-transform": re.compile(r"傅里叶变换|fourier transform", re.I),
    "laplace-transform": re.compile(r"拉普拉斯变换|laplace transform", re.I),
    "taylor": re.compile(r"泰勒展开|泰勒级数|taylor (expansion|series)", re.I),
    "residue": re.compile(r"留数|residue theorem|residue", re.I),
    "power-series": re.compile(r"幂级数|power series", re.I),
    "euler-formula": re.compile(r"欧拉公式|euler'?s formula", re.I),
    "cauchy-riemann": re.compile(r"柯西.?黎曼|cauchy.?riemann", re.I),
    "green-theorem": re.compile(r"格林公式|green'?s theorem", re.I),
    "divergence-theorem": re.compile(r"高斯定理|散度定理|divergence theorem", re.I),
    "stokes-theorem": re.compile(r"斯托克斯|stokes'? theorem", re.I),
    "vector-calculus": re.compile(r"梯度|散度|旋度|gradient|divergence|curl", re.I),
    "line-surface-integral": re.compile(r"曲线积分|曲面积分|line integral|surface integral", re.I),
    "jacobian": re.compile(r"雅可比|jacobian", re.I),
    "implicit-function": re.compile(r"隐函数定理|implicit function theorem", re.I),
    "quadric-surface": re.compile(r"二次曲面|quadric surface", re.I),
    "norm": re.compile(r"范数|(^|[^a-z])norms?([^a-z]|$)", re.I),
    "convolution": re.compile(r"卷积|convolution", re.I),
    "generating-function": re.compile(r"生成函数|母函数|generating function", re.I),
    "markov-chain": re.compile(r"马尔可夫链|markov chain", re.I),
    "matrix-exponential": re.compile(r"矩阵指数|matrix exponential", re.I),
    "ode-system": re.compile(r"常微分方程组|微分方程组|system of (linear )?odes", re.I),
    "prime-number-theorem": re.compile(r"素数定理|prime number theorem", re.I),
    "riemann-zeta": re.compile(r"黎曼.?ζ|黎曼zeta|riemann zeta", re.I),
    "analytic-number-theory": re.compile(r"解析数论|analytic number theory", re.I),
    "variational": re.compile(r"变分法|calculus of variations", re.I),
    "green-function": re.compile(r"格林函数|green'?s function", re.I),
    "parseval": re.compile(r"帕塞瓦尔|parseval", re.I),
}

assert set(_PATTERNS) == set(CROSS_TOPIC_IDS)


def tag_cross_topics(*texts: str) -> tuple[str, ...]:
    content = "\n".join(text for text in texts if text)
    return tuple(topic for topic in CROSS_TOPIC_IDS if _PATTERNS[topic].search(content))


def apply_tags(exercise: Exercise) -> Exercise:
    """给原语种题干+过程打交叉标签;已有标签保留,不覆盖人工结果。"""
    source = exercise.content[exercise.original_language]
    detected = tag_cross_topics(source.question, source.solution)
    merged = tuple(dict.fromkeys((*exercise.cross_topics, *detected)))
    if merged == exercise.cross_topics:
        return exercise
    return replace(
        exercise,
        cross_topics=merged,
        tag_source=exercise.tag_source if exercise.cross_topics else "rule",
    )
