---
title: 函数的极限
title_en: Limits
keywords: ["极限", "夹逼", "lim"]
category: analysis
---
## 极限的四则运算法则

若 $\lim_{x\to a} f(x)=A$ 与 $\lim_{x\to a} g(x)=B$ 都存在,则和、差、积、商的极限
等于极限的和、差、积、商(商要求 $B\neq 0$)。该法则是求极限最基本的手段,使用前必须
先确认两个极限都存在。

## 夹逼定理

若在 $a$ 的某去心邻域内 $g(x)\le f(x)\le h(x)$,且 $\lim g(x)=\lim h(x)=A$,
则 $\lim f(x)=A$。常用于含 $\sin\frac{1}{x}$、取整函数或 $n$ 项和的极限。
