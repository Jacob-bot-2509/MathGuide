---
title: 泰勒展开
title_en: Taylor Expansion
keywords: ["泰勒", "麦克劳林", "taylor", "maclaurin", "泰勒公式", "泰勒展开", "taylor series", "taylor expansion"]
category: analysis
---

## 专业表述
若 $f$ 在 $x_0$ 处 $n$ 阶可导,则 $f(x)=\sum_{k=0}^{n}\frac{f^{(k)}(x_0)}{k!}(x-x_0)^k+R_n(x)$,
其中 $R_n(x)=o((x-x_0)^n)$(佩亚诺余项)或 $R_n(x)=\frac{f^{(n+1)}(\xi)}{(n+1)!}(x-x_0)^{n+1}$(拉格朗日余项);
$x_0=0$ 时即麦克劳林公式。

## 形象理解
泰勒展开 = 用「多项式积木」在一点附近复刻函数:知道函数在 $x_0$ 的导数到 $n$ 阶,
就等于掌握了它在 $x_0$ 的「位置、速度、加速度、加速度的变化率……」;阶数越高,
多项式与函数的贴合范围越远。就像用前几帧画面预测下一帧,掌握的高阶变化信息越多,预测越准。

## 关键结论
$e^x=\sum_{k=0}^{\infty}\frac{x^k}{k!}$、$\sin x=x-\frac{x^3}{3!}+\frac{x^5}{5!}-\cdots$、
$\ln(1+x)=x-\frac{x^2}{2}+\frac{x^3}{3}-\cdots$;$e^x$ 与 $\sin x$ 的展开收敛于全实轴,
$\ln(1+x)$ 仅在 $|x|<1$ 收敛;求极限、近似计算、证明不等式是三大经典应用。
