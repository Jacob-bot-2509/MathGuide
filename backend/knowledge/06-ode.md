---
title: 微分方程
title_en: Differential Equations
keywords: ["微分方程", "ode", "解方程", "可分离", "differential equation", "separable", "initial value"]
category: ode
---

## 专业表述
含未知函数及其导数的方程称为微分方程;$n$ 阶方程通解含 $n$ 个独立任意常数。
可分离变量方程 $y'=f(x)g(y)$ 通过 $\int\frac{dy}{g(y)}=\int f(x)\,dx$ 求解。

## 形象理解
微分方程给的不是答案本身,而是「变化规则」:告诉你每一步怎么走,却要你推出整条路。
就像只知道「细菌每小时翻倍」,却能反推出任意时刻的总数——初值条件选定具体那一条轨道。

## 关键结论
一阶线性方程 $y'+P(x)y=Q(x)$ 用积分因子 $e^{\int P\,dx}$ 求解;
通解中的常数最终由初始条件确定,两者缺一不可。
