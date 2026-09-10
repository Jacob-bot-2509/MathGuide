---
title: 数论
title_en: Number Theory
keywords: ["数论", "素数", "质数", "整除", "约数", "同余", "费马小定理", "欧拉函数", "欧拉定理", "中国剩余定理", "二次剩余", "原根", "数论函数", "莫比乌斯", "丢番图", "不定方程", "勾股数", "算术基本定理", "素数定理", "哥德巴赫", "number theory", "prime", "divisor", "gcd", "congruence", "modulo", "fermat", "euler", "chinese remainder", "diophantine"]
category: numberTheory
---

## 专业表述
算术基本定理:每个大于 $1$ 的整数可唯一分解为素数乘积 $n=p_1^{a_1}p_2^{a_2}\cdots p_k^{a_k}$。
费马小定理:$p$ 为素数且 $p\nmid a$ 时,$a^{p-1}\equiv 1\pmod p$。
欧拉函数 $\varphi(n)$ 等于 $1\sim n$ 中与 $n$ 互素的整数个数,由此得欧拉定理 $a^{\varphi(n)}\equiv 1\pmod n$($\gcd(a,n)=1$)。
中国剩余定理:模两两互素的同余方程组必有解,且解在模 $M=m_1m_2\cdots m_k$ 意义下唯一。

## 形象理解
素数 = 整数的「原子」:任何整数都能唯一拆成素数的积,正如分子拆成原子。
同余 = 剩余类时钟:$\bmod 12$ 下 13 点就是 1 点,循环相加不相撞。
欧拉函数 $\varphi(n)$ = 数一数「与 $n$ 互素的哨兵」有多少个;费马-欧拉定理说:在模 $n$ 的世界里,$a$ 连乘 $\varphi(n)$ 次总能转回它自己。

## 关键结论
费马小定理:$p$ 素数 $\Rightarrow a^{p-1}\equiv 1\pmod p$——现代密码学(RSA)的数学根基。
二次互反律(高斯称为「黄金定理」)给出二次剩余判定的普适法则。
素数定理:不超过 $x$ 的素数个数 $\pi(x)\sim\dfrac{x}{\ln x}$。
黎曼猜想若成立,素数分布的误差估计将大幅改进(解析数论的皇冠问题)。
