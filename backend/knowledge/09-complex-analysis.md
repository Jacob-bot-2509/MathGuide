---
title: 复变函数
title_en: Complex Analysis
keywords: ["复变", "解析", "留数", "柯西", "柯西-黎曼", "柯西黎曼", "complex analysis", "residue", "analytic", "cauchy", "cauchy-riemann"]
category: complex
---

## 专业表述
复函数 $f(z)$ 在区域内处处可导则称解析(全纯);Cauchy-Riemann 方程 $u_x=v_y,\ u_y=-v_x$ 是解析的判别条件。

## 形象理解
解析函数像「保角的地图」——局部看只做旋转 + 均匀伸缩,不产生畸变。
正因为这个刚性,知道边界值就能确定内部(这是调和函数与共形映射的魅力)。

## 关键结论
留数定理把围道积分化为奇点留数之和:$\oint_C f(z)\,dz=2\pi i\sum \mathrm{Res}$,
是实积分计算的「魔法桥梁」。
