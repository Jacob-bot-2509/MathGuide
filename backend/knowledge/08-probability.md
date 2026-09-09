---
title: 概率论与数理统计
title_en: Probability & Mathematical Statistics
keywords: ["概率", "概率论", "数理统计", "统计", "期望", "方差", "正态", "分布", "随机变量", "假设检验", "置信区间", "大数定律", "中心极限", "贝叶斯", "极大似然", "probability", "statistics", "expectation", "variance", "distribution", "normal", "hypothesis test", "confidence interval"]
category: probability
---

## 专业表述
随机变量 $X$ 的期望 $E[X]=\sum x_i p_i$ 是概率加权平均;方差 $D[X]=E[(X-E[X])^2]$。
正态分布 $N(\mu,\sigma^2)$ 密度 $f(x)=\frac{1}{\sqrt{2\pi}\sigma}e^{-\frac{(x-\mu)^2}{2\sigma^2}}$。
贝叶斯公式 $P(A|B)=\frac{P(B|A)P(A)}{P(B)}$ 把先验概率更新为后验概率。

## 形象理解
期望 = 玩很多次后的「平均手感」;方差衡量手感的波动大小。
中心极限定理说:大量独立随机因素叠加,无论各自什么分布,总和都趋向钟形——
这解释了为什么「测量误差」「身高分布」都长成正态钟。
大数定律说:次数足够多,频率稳定在概率附近——赌场靠它稳赚不赔。

## 数理统计
参数估计:用样本推断总体——极大似然估计选「最可能产生这组样本」的参数;
区间估计给出置信区间 $(\bar{x}-z_{\alpha/2}\frac{\sigma}{\sqrt{n}},\ \bar{x}+z_{\alpha/2}\frac{\sigma}{\sqrt{n}})$。
假设检验:先假定原假设成立,再算数据落在当前结果或更极端情况的概率(p 值),
p 小于显著性水平 $\alpha$(常取 0.05)就拒绝原假设——「小概率事件实际不发生」。

## 关键结论
$P(\mu-\sigma<X<\mu+\sigma)\approx 68\%$,$P(\mu-2\sigma<X<\mu+2\sigma)\approx 95\%$。
大数定律与中心极限定理是统计推断的两大支柱。
