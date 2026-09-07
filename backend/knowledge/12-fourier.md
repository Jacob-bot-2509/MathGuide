---
title: 傅里叶分析
title_en: Fourier Analysis
keywords: ["傅里叶", "周期", "fourier", "periodic"]
category: analysis
---

## 专业表述
周期函数(满足 Dirichlet 条件)可展开为三角级数 $f(x)=\frac{a_0}{2}+\sum_{n=1}^{\infty}(a_n\cos nx+b_n\sin nx)$,
系数由正交性求出。

## 形象理解
任何复杂波形 = 若干「纯音」的叠加:傅里叶展开就是音频的频谱分析——
把一段音乐拆成一个个基频与泛音,这就是 MP3 压缩与降噪的底层数学。

## 关键结论
间断点处级数收敛到左右极限平均值 $\frac{f(x^+)+f(x^-)}{2}$;
Gibbs 现象:间断点附近有约 9% 的过冲。
