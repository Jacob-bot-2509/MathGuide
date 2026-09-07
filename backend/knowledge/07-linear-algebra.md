---
title: 线性代数
title_en: Linear Algebra
keywords: ["矩阵", "行列式", "线性相关", "特征值", "matrix", "determinant", "eigenvalue", "eigenvector", "linear algebra"]
category: algebra
---

## 专业表述
矩阵是线性映射的坐标表达:$A\bm x=\bm b$ 可解性等价于 $\mathrm{rank}(A)=\mathrm{rank}(A|\bm b)$;
特征方程 $\det(A-\lambda I)=0$ 的根为特征值。

## 形象理解
矩阵是「变形指令」——旋转、拉伸、压扁;特征向量是那些只被拉伸不改变方向的特殊向量,
特征值告诉你拉伸了 $\lambda$ 倍。对角化就是把复杂变形拆成一串独立的一维伸缩。

## 关键结论
$n$ 个不同特征值 ⇒ 可对角化;实对称矩阵必可正交对角化,这是二次型与主成分分析的根基。
