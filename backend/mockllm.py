"""
本地模拟模型(MockLLM):后端骨架的回复引擎。

后端对接真实 LLM 前,先用关键词知识库生成双语回复,保证
「前端 ↔ SSE ↔ 后端」链路端到端可测。替换点集中在本文件:
build_reply(prompt, cmd) → 改为调用 LLM API 即可,chat.py 无需改动。

行为约定(与前端对齐):
- 板块与难度均由模型侧自动判定,绝不反问用户(judge_level);
- 中文提问 → 中文正文;英文提问 → 英文正文(命中无英文正文的主题时走英文兜底);
- 输出约定(与前端渲染器 MathText 对齐):行内公式 $...$,块级公式 $$...$$(KaTeX)、**加粗**。
"""
import re
from typing import Sequence

# 指令中文标识(与前端 utils/commands.ts 一致)
CMD_OPENERS: dict[str, str] = {
    "概念动画演示": "好的,下面把概念拆成「动画演示」式的可视化过程。",
    "例题精讲": "好的,先定位知识,再给一道经典例题。",
    "章节知识导航": "好的,先梳理该知识点的章节位置与前置依赖。",
    "错题归纳": "好的,按「错因归类 → 易错点 → 规避策略」来归纳。",
    "公式查询手册": "好的,下面是常用公式与使用条件速查。",
}

# (触发词(中英,统一小写), 中文标题, 英文标题, 中文正文, 英文正文)
# 正文遵循双轨解释:专业表述 + 形象理解;关键词需与 frontend/src/utils/classifier.ts 板块一致
KNOWN: list[dict] = [
    {
        "keywords": ["极限", "lim", "趋近", "收敛", "converge", "limit"],
        "title": "函数极限", "title_en": "Limits",
        "body_zh": "设 $f(x)$ 在 $x_0$ 的某去心邻域内有定义,若 $\\forall\\,\\varepsilon>0$,$\\exists\\,\\delta>0$,"
        "当 $0<|x-x_0|<\\delta$ 时恒有 $|f(x)-A|<\\varepsilon$,则称 $\\lim_{x\\to x_0}f(x)=A$。\n\n"
        "**形象理解:** 极限衡量的是「逼近的最终去向」——你不必到达那个点,只需让 $x$ 无限靠近 $x_0$ 时,"
        "$f(x)$ 与 $A$ 的距离小到任意指定。就像赛跑逼近终点线却永远允许差一口气,终点 $A$ 是过程锁定的目标。\n\n"
        "**关键结论:** $\\lim_{x\\to 0}\\frac{\\sin x}{x}=1$ 是一切等价无穷小替换的根基;"
        "判断极限存在需左右极限相等,这是分段函数题的常见陷阱。",
        "body_en": "For $f$ defined near $x_0$: $\\lim_{x\\to x_0}f(x)=A$ means that for every $\\varepsilon>0$ there is a "
        "$\\delta>0$ such that $0<|x-x_0|<\\delta$ forces $|f(x)-A|<\\varepsilon$.\n\n"
        "**Intuition:** a limit describes where the process is *heading* — you never need to arrive, "
        "only to get arbitrarily close. It is the target the values lock onto, like a runner approaching a finish line "
        "that is forever one breath away.\n\n"
        "**Key facts:** $\\lim_{x\\to 0}\\frac{\\sin x}{x}=1$ underpins all small-angle replacements; "
        "a limit exists only when the left- and right-hand limits agree — the classic trap in piecewise functions.",
    },
    {
        "keywords": ["导数", "求导", "切线", "derivative", "differentiat", "tangent"],
        "title": "导数", "title_en": "Derivatives",
        "body_zh": "函数 $f$ 在 $x_0$ 处的导数 $f'(x_0)=\\lim_{h\\to 0}\\dfrac{f(x_0+h)-f(x_0)}{h}$,"
        "刻画的是 $x_0$ 处变化率,几何上即曲线在 $(x_0,f(x_0))$ 处切线的斜率。\n\n"
        "**形象理解:** 导数 = 瞬间速度:汽车里程表读出的正是「此刻每秒走了多少米」。"
        "斜率大 = 陡,斜率 0 = 水平,斜率为负 = 在下坡。\n\n"
        "**关键结论:** $f'(x_0)>0$ 只说明 $x_0$ 邻域内单调上升的**趋势**,并不保证附近全区间单调;"
        "复合求导法则(链式法则)是考研必考的第一运算。",
        "body_en": "The derivative $f'(x_0)=\\lim_{h\\to 0}\\frac{f(x_0+h)-f(x_0)}{h}$ measures the rate of change at "
        "$x_0$ — geometrically, the slope of the tangent line at $(x_0,f(x_0))$.\n\n"
        "**Intuition:** the derivative is instantaneous speed — what the speedometer shows *right now*. "
        "Large slope = steep, zero slope = flat, negative slope = downhill.\n\n"
        "**Key facts:** $f'(x_0)>0$ only signals a local rising *trend*, not monotonicity on a whole interval; "
        "the chain rule is the single most used differentiation tool.",
    },
    {
        "keywords": ["微分方程", "ode", "解方程", "可分离", "differential equation", "separable", "initial value"],
        "title": "微分方程", "title_en": "Differential Equations",
        "body_zh": "含未知函数及其导数的方程称为微分方程;$n$ 阶方程通解含 $n$ 个独立任意常数。"
        "可分离变量方程 $y'=f(x)g(y)$ 通过 $\\int\\frac{dy}{g(y)}=\\int f(x)\\,dx$ 求解。\n\n"
        "**形象理解:** 微分方程给的不是答案本身,而是「变化规则」:告诉你每一步怎么走,却要你推出整条路。"
        "就像只知道「细菌每小时翻倍」,却能反推出任意时刻的总数——初值条件选定具体那一条轨道。\n\n"
        "**关键结论:** 一阶线性方程 $y'+P(x)y=Q(x)$ 用积分因子 $e^{\\int P\\,dx}$ 求解;"
        "通解中的常数最终由初始条件确定,两者缺一不可。",
        "body_en": "A differential equation relates an unknown function to its derivatives; the general solution of an "
        "$n$-th order equation carries $n$ arbitrary constants. Separable equations $y'=f(x)g(y)$ are solved by "
        "$\\int\\frac{dy}{g(y)}=\\int f(x)\\,dx$.\n\n"
        "**Intuition:** a differential equation hands you the *rule of change*, not the answer — it tells you how to step, "
        "and you reconstruct the whole path. Knowing only that bacteria double hourly, you can still recover the total at "
        "any time; the initial condition picks which orbit you are on.\n\n"
        "**Key facts:** first-order linear equations $y'+P(x)y=Q(x)$ are solved with the integrating factor "
        "$e^{\\int P\\,dx}$; the initial condition is what pins down the free constants.",
    },
    {
        "keywords": ["积分", "原函数", "微积分基本定理", "integral", "antiderivative", "fundamental theorem"],
        "title": "积分", "title_en": "Integrals",
        "body_zh": "定积分 $\\int_a^b f(x)\\,dx$ 定义为黎曼和极限;微积分基本定理把微分与积分统一:"
        "$\\int_a^b f(x)\\,dx=F(b)-F(a)$(其中 $F'=f$)。\n\n"
        "**形象理解:** 微分回答「每秒切多细」,积分回答「细条累加回总量」。"
        "把曲线下的面积切成无限条细矩形,积分就是这些矩形总面积的极限——"
        "先微分再积分,就像把绳子剪成小段再拼回原长,基本定理保证拼接无缝。\n\n"
        "**关键结论:** 换元法要同步换限;分部积分 $\\int u\\,dv=uv-\\int v\\,du$ 按「反对幂指三」选 $u$。",
        "body_en": "The definite integral $\\int_a^b f(x)\\,dx$ is defined as the limit of Riemann sums; the Fundamental "
        "Theorem unifies differentiation and integration: $\\int_a^b f(x)\\,dx=F(b)-F(a)$ where $F'=f$.\n\n"
        "**Intuition:** differentiation answers 'how finely do we slice each second', integration answers 'how do the "
        "slices add back to the total'. Cutting the area under a curve into infinitely many thin rectangles, the integral "
        "is the limit of their total area — differentiate then integrate, and the pieces reassemble seamlessly.\n\n"
        "**Key facts:** substitution must change the limits too; integration by parts "
        "$\\int u\\,dv=uv-\\int v\\,du$ chooses $u$ by the LIATE rule.",
    },
    {
        "keywords": ["级数", "无穷级数", "幂级数", "series", "power series", "infinite series", "summation"],
        "title": "级数", "title_en": "Series",
        "body_zh": "数项级数 $\\sum_{n=1}^{\\infty}a_n$ 收敛指部分和序列有极限;"
        "绝对收敛 ⇒ 收敛,反之不成立(如交错调和级数)。幂级数存在收敛半径 $R$:"
        "$|x|<R$ 内绝对收敛,$|x|>R$ 内发散。\n\n"
        "**形象理解:** 级数像无限接力跑:每一步贡献越来越小的「步幅」,总路程最终逼近一个确定值。"
        "收敛与否取决于「步幅衰减得够不够快」——$\\frac1n$ 跑不完(调和发散),$\\frac1{n^2}$ 跑得完。\n\n"
        "**关键结论:** $\\sum\\frac1{n^2}=\\frac{\\pi^2}{6}$;判别首选比值法/根值法,$a_n\\not\\to 0$ 直接判定发散。",
        "body_en": "A series $\\sum_{n=1}^{\\infty}a_n$ converges when its partial sums have a limit; absolute convergence "
        "implies convergence, but not conversely (e.g. the alternating harmonic series). A power series has a radius of "
        "convergence $R$: absolutely convergent for $|x|<R$, divergent for $|x|>R$.\n\n"
        "**Intuition:** a series is an infinite relay — every step contributes a smaller stride and the total distance "
        "settles toward a definite value. Convergence asks whether the strides shrink fast enough: $\\frac1n$ never "
        "finishes, $\\frac1{n^2}$ does.\n\n"
        "**Key facts:** $\\sum\\frac1{n^2}=\\frac{\\pi^2}{6}$; try the ratio/root test first, and if "
        "$a_n\\not\\to 0$ the series diverges immediately.",
    },
    {
        "keywords": ["泰勒", "麦克劳林", "taylor", "maclaurin", "泰勒公式", "泰勒展开", "taylor series", "taylor expansion"],
        "title": "泰勒展开", "title_en": "Taylor Expansion",
        "body_zh": "若 $f$ 在 $x_0$ 处 $n$ 阶可导,则 $f(x)=\\sum_{k=0}^{n}\\frac{f^{(k)}(x_0)}{k!}(x-x_0)^k+R_n(x)$,"
        "其中 $R_n(x)=o((x-x_0)^n)$(佩亚诺余项)或 $R_n(x)=\\frac{f^{(n+1)}(\\xi)}{(n+1)!}(x-x_0)^{n+1}$(拉格朗日余项);"
        "$x_0=0$ 时即麦克劳林公式。\n\n"
        "**形象理解:** 泰勒展开 = 用「多项式积木」在一点附近复刻函数:知道函数在 $x_0$ 的导数到 $n$ 阶,"
        "就等于掌握了它在 $x_0$ 的「位置、速度、加速度、加速度的变化率……」;阶数越高,"
        "多项式与函数的贴合范围越远。就像用前几帧画面预测下一帧,掌握的高阶变化信息越多,预测越准。\n\n"
        "**关键结论:** $e^x=\\sum_{k=0}^{\\infty}\\frac{x^k}{k!}$、$\\sin x=x-\\frac{x^3}{3!}+\\frac{x^5}{5!}-\\cdots$、"
        "$\\ln(1+x)=x-\\frac{x^2}{2}+\\frac{x^3}{3}-\\cdots$;$e^x$ 与 $\\sin x$ 的展开收敛于全实轴,"
        "$\\ln(1+x)$ 仅在 $|x|<1$ 收敛;求极限、近似计算、证明不等式是三大经典应用。",
        "body_en": "If $f$ is $n$ times differentiable at $x_0$, then "
        "$f(x)=\\sum_{k=0}^{n}\\frac{f^{(k)}(x_0)}{k!}(x-x_0)^k+R_n(x)$, with Peano remainder "
        "$R_n(x)=o((x-x_0)^n)$ or Lagrange remainder "
        "$R_n(x)=\\frac{f^{(n+1)}(\\xi)}{(n+1)!}(x-x_0)^{n+1}$; at $x_0=0$ this is the Maclaurin formula.\n\n"
        "**Intuition:** a Taylor expansion rebuilds a function near a point out of polynomial 'building blocks'. "
        "Knowing the derivatives up to order $n$ is like knowing the position, velocity, acceleration (and beyond) at one "
        "instant — the higher the order, the wider the region where the polynomial stays faithful.\n\n"
        "**Key facts:** $e^x=\\sum_{k=0}^{\\infty}x^k/k!$, $\\sin x=x-x^3/3!+x^5/5!-\\cdots$, "
        "$\\ln(1+x)=x-x^2/2+x^3/3-\\cdots$; the series for $e^x$ and $\\sin x$ converge on the whole real line, "
        "while $\\ln(1+x)$ needs $|x|<1$. Classic uses: computing limits, numerical approximation, proving inequalities.",
    },
    {
        "keywords": ["矩阵", "行列式", "线性相关", "特征值", "matrix", "determinant", "eigenvalue", "eigenvector", "linear algebra"],
        "title": "线性代数", "title_en": "Linear Algebra",
        "body_zh": "矩阵是线性映射的坐标表达:$A\\bm x=\\bm b$ 可解性等价于 $\\mathrm{rank}(A)=\\mathrm{rank}(A|\\bm b)$;"
        "特征方程 $\\det(A-\\lambda I)=0$ 的根为特征值。\n\n"
        "**形象理解:** 矩阵是「变形指令」——旋转、拉伸、压扁;特征向量是那些只被拉伸不改变方向的特殊向量,"
        "特征值告诉你拉伸了 $\\lambda$ 倍。对角化就是把复杂变形拆成一串独立的一维伸缩。\n\n"
        "**关键结论:** $n$ 个不同特征值 ⇒ 可对角化;实对称矩阵必可正交对角化,这是二次型与主成分分析的根基。",
        "body_en": "A matrix is the coordinate form of a linear map: $A\\bm x=\\bm b$ is solvable iff "
        "$\\mathrm{rank}(A)=\\mathrm{rank}(A|\\bm b)$; eigenvalues are the roots of $\\det(A-\\lambda I)=0$.\n\n"
        "**Intuition:** a matrix is a 'deformation instruction' — rotate, stretch, squash. Eigenvectors are the special "
        "directions that are only stretched, never turned; the eigenvalue tells you by how much ($\\lambda$). "
        "Diagonalization splits a complicated deformation into independent one-dimensional stretches.\n\n"
        "**Key facts:** $n$ distinct eigenvalues guarantee diagonalizability; real symmetric matrices are always "
        "orthogonally diagonalizable — the foundation of quadratic forms and PCA.",
    },
    {
        "keywords": ["概率", "期望", "正态", "分布", "probability", "expectation", "variance", "distribution", "normal"],
        "title": "概率统计", "title_en": "Probability & Statistics",
        "body_zh": "随机变量 $X$ 的期望 $E[X]=\\sum x_i p_i$ 是概率加权平均;"
        "正态分布 $N(\\mu,\\sigma^2)$ 密度 $f(x)=\\frac{1}{\\sqrt{2\\pi}\\sigma}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}$。\n\n"
        "**形象理解:** 期望 = 玩很多次后的「平均手感」;方差衡量手感的波动大小。"
        "中心极限定理说:大量独立随机因素叠加,无论各自什么分布,总和都趋向钟形——"
        "这解释了为什么「测量误差」「身高分布」都长成正态钟。\n\n"
        "**关键结论:** $P(\\mu-\\sigma<X<\\mu+\\sigma)\\approx 68\\%$;大数定律与中心极限定理是统计推断的两大支柱。",
        "body_en": "The expectation $E[X]=\\sum x_i p_i$ is the probability-weighted average; the normal density is "
        "$f(x)=\\frac{1}{\\sqrt{2\\pi}\\sigma}e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}}$.\n\n"
        "**Intuition:** expectation is your 'average feel' over many trials; variance measures how much that feel "
        "fluctuates. The central limit theorem says many independent random factors, whatever their individual shapes, "
        "produce a bell-shaped total — which is why measurement errors and heights all look normal.\n\n"
        "**Key facts:** $P(\\mu-\\sigma<X<\\mu+\\sigma)\\approx 68\\%$; the law of large numbers and the CLT are the two "
        "pillars of statistical inference.",
    },
    {
        "keywords": ["复变", "解析", "留数", "complex analysis", "residue", "analytic", "cauchy"],
        "title": "复变函数", "title_en": "Complex Analysis",
        "body_zh": "复函数 $f(z)$ 在区域内处处可导则称解析(全纯);Cauchy-Riemann 方程 $u_x=v_y,\\ u_y=-v_x$ 是解析的判别条件。\n\n"
        "**形象理解:** 解析函数像「保角的地图」——局部看只做旋转 + 均匀伸缩,不产生畸变。"
        "正因为这个刚性,知道边界值就能确定内部(这是调和函数与共形映射的魅力)。\n\n"
        "**关键结论:** 留数定理把围道积分化为奇点留数之和:$\\oint_C f(z)\\,dz=2\\pi i\\sum \\mathrm{Res}$,"
        "是实积分计算的「魔法桥梁」。",
        "body_en": "A complex function $f(z)$ is analytic (holomorphic) when it is differentiable everywhere in a region; "
        "the Cauchy-Riemann equations $u_x=v_y,\\ u_y=-v_x$ are the test.\n\n"
        "**Intuition:** analytic maps are 'conformal maps' — locally only rotation plus uniform scaling, no distortion. "
        "That rigidity is why boundary values determine the interior (the magic behind harmonic functions and conformal "
        "mapping).\n\n"
        "**Key facts:** the residue theorem turns contour integrals into sums of residues: "
        "$\\oint_C f(z)\\,dz=2\\pi i\\sum \\mathrm{Res}$ — the 'magic bridge' for computing real integrals.",
    },
    {
        "keywords": ["拓扑", "开集", "连通", "紧致", "topology", "open set", "compact", "connected", "homeomorph"],
        "title": "拓扑学", "title_en": "Topology",
        "body_zh": "拓扑空间由开集族定义:拓扑同胚(连续双射且逆连续)下不变的性质称拓扑性质。"
        "紧致性 = 任意开覆盖有有限子覆盖。\n\n"
        "**形象理解:** 拓扑学是「橡皮泥几何」——允许拉伸压缩,不允许撕裂粘贴。"
        "杯子与甜甜圈同胚(一个洞),眼镜框与它俩都不同胚(两个洞)。洞的个数即亏格,是拓扑不变量。\n\n"
        "**关键结论:** 连续函数把紧集映到紧集、连通集映到连通集,这两条把分析问题翻译成拓扑语言的通道。",
        "body_en": "A topological space is defined by its family of open sets; properties invariant under homeomorphisms "
        "(continuous bijections with continuous inverses) are topological properties. Compactness = every open cover has "
        "a finite subcover.\n\n"
        "**Intuition:** topology is 'play-doh geometry' — stretching is allowed, tearing or gluing is not. "
        "A cup and a donut are homeomorphic (one hole); eyeglass frames are not (two holes). The hole count — the genus "
        "— is a topological invariant.\n\n"
        "**Key facts:** continuous maps send compact sets to compact sets and connected sets to connected sets — "
        "two channels that translate analysis problems into topological language.",
    },
    {
        "keywords": ["曲率", "拐点", "中值定理", "拉格朗日", "curvature", "mean value theorem", "lagrange", "inflection"],
        "title": "微分学应用", "title_en": "Applications of Differentiation",
        "body_zh": "Lagrange 中值定理:$f$ 在 $[a,b]$ 连续、$(a,b)$ 可导,则 $\\exists\\,\\xi\\in(a,b)$ 使 "
        "$f(b)-f(a)=f'(\\xi)(b-a)$。曲率 $K=\\frac{|y''|}{(1+y'^2)^{3/2}}$。\n\n"
        "**形象理解:** 中值定理保证:两点间的平均速度,必然在途中某一瞬间被「即时速度」精确复现——"
        "超速摄像头原理:平均超速必有瞬时超速。曲率衡量曲线「弯得多急」,半径越小越急弯。\n\n"
        "**关键结论:** 证明不等式与等式恒等的标准套路:移项后对差值应用中值定理或单调性。",
        "body_en": "Lagrange's Mean Value Theorem: if $f$ is continuous on $[a,b]$ and differentiable on $(a,b)$, there is "
        "$\\xi\\in(a,b)$ with $f(b)-f(a)=f'(\\xi)(b-a)$. Curvature: $K=\\frac{|y''|}{(1+y'^2)^{3/2}}$.\n\n"
        "**Intuition:** the MVT guarantees that the average speed between two points is exactly reproduced by the "
        "instantaneous speed at some moment in between — the math behind average-speed cameras. Curvature measures how "
        "sharply a curve bends; smaller radius, sharper turn.\n\n"
        "**Key facts:** the standard move for proving inequalities is to rearrange terms and apply the MVT (or "
        "monotonicity) to the difference.",
    },
    {
        "keywords": ["傅里叶", "周期", "fourier", "periodic"],
        "title": "傅里叶分析", "title_en": "Fourier Analysis",
        "body_zh": "周期函数(满足 Dirichlet 条件)可展开为三角级数 $f(x)=\\frac{a_0}{2}+\\sum_{n=1}^{\\infty}"
        "(a_n\\cos nx+b_n\\sin nx)$,系数由正交性求出。\n\n"
        "**形象理解:** 任何复杂波形 = 若干「纯音」的叠加:傅里叶展开就是音频的频谱分析——"
        "把一段音乐拆成一个个基频与泛音,这就是 MP3 压缩与降噪的底层数学。\n\n"
        "**关键结论:** 间断点处级数收敛到左右极限平均值 $\\frac{f(x^+)+f(x^-)}{2}$;"
        "Gibbs 现象:间断点附近有约 9% 的过冲。",
        "body_en": "A periodic function (satisfying Dirichlet conditions) expands as "
        "$f(x)=\\frac{a_0}{2}+\\sum_{n=1}^{\\infty}(a_n\\cos nx+b_n\\sin nx)$; the coefficients come from orthogonality.\n\n"
        "**Intuition:** any complicated waveform is a stack of 'pure tones' — Fourier expansion is the spectral analysis "
        "of audio: one piece of music decomposed into fundamentals and overtones. This is the mathematics underneath MP3 "
        "compression and noise reduction.\n\n"
        "**Key facts:** at a jump discontinuity the series converges to the midpoint "
        "$\\frac{f(x^+)+f(x^-)}{2}$; the Gibbs phenomenon overshoots by about 9% near jumps.",
    },
]

WELCOME_ZH = (
    "**欢迎回到 MATHGUIDE · 学习辅助**\n\n"
    "我是 MG,你的高等数学学习与研究助手。直接提问即可,或用下方指令:"
    "概念动画演示 / 例题精讲 / 章节知识导航 / 错题归纳 / 公式查询手册。\n\n"
    "问题的**板块与难度我会自动识别**,先给严谨的专业表述,再给形象化理解,并带上公式推演;"
    "中文、英文提问都可以。\n\n"
    "(Welcome to MATHGUIDE · Learn. You can also ask in English, e.g. \"explain limits with intuition\".)"
)


def welcome_reply() -> str:
    """新会话欢迎语(前端以空 prompt 触发)"""
    return WELCOME_ZH


LEVEL_ZH = {"basic": "基础", "advance": "进阶", "competition": "竞赛"}
LEVEL_EN = {"basic": "basic", "advance": "advanced", "competition": "competition"}


def judge_level(text: str) -> str:
    """按问题措辞自动判断难度(中英文关键词),绝不反问用户。"""
    t = text.lower()
    if any(k in t for k in ("竞赛", "奥数", "imo", "cmo", "难题", "挑战", "压轴", "拔尖", "olympiad")):
        return "competition"
    if any(k in t for k in ("基础", "入门", "初学", "简单", "是什么", "定义", "概念", "为什么", "怎么理解",
                            "通俗", "新手", "what is", "definition", "concept", "beginner", "basic",
                            "introduction", "intuitively")):
        return "basic"
    return "advance"


FALLBACK_ZH = (
    "这个问题我已按措辞自动判定难度为**{level}**。\n\n"
    "**通用三步走(专业表述):** ① 明确对象与条件,把问题转化为标准型(极限式、方程、积分、模型);"
    "② 选择对应工具求解;③ **回代验算**——MG 的「自我验证工作流」会在解答发布前进行一致性检查与符号复验,"
    "低置信度时会主动标注「该解答需进行人工处理」。\n\n"
    "**形象理解:** 解数学题像侦探破案:先锁定案件类型,再盘点物证(条件),"
    "最后用匹配的手法收网;每一步结论都要经得起「代入原题」这关审讯。\n\n"
    "把题目原文(或拍照上传)发给我,我会按上面的框架给出带完整过程的解答。"
)

FALLBACK_EN = (
    "I've read your question and automatically rate its difficulty as **{level}**.\n\n"
    "**Approach (3 steps):** 1) Identify the objects and conditions, and rewrite the problem into a canonical form "
    "(a limit, an equation, an integral, or a model); 2) apply the matching tool; 3) **verify by substitution**. "
    "MG's self-verification workflow runs consistency checks and symbolic re-validation before publishing an answer, "
    "flagging low-confidence ones as \"manual review required\".\n\n"
    "**Intuition:** solving a math problem is like detective work — classify the case, collect the evidence, "
    "close the net with the right method, and cross-examine every conclusion by plugging it back in.\n\n"
    "Paste the full problem (or upload a photo) and I'll work through it step by step."
)

ATTACH_IMAGE_ZH = (
    "已收到你上传的图片 **{name}**。\n\n"
    "当前演示环境(mock)会保留图片于会话记录中;接入视觉模型后,MG 将直接识图作答:"
    "拍照的手写题目 → OCR + 版面解析 → 按板块与难度路由。\n\n"
    "**现在你可以:** ① 把题目文字打出来,我照常解答;② 先手动归入对应板块(题目类型判断已生效)。"
)
ATTACH_FILE_ZH = (
    "已收到文件 **{name}**(大小 {size} KB)。\n\n"
    "演示环境仅保存文件元信息;接入后端文件服务后支持 PDF / 讲义解析,"
    "可执行「章节知识导航」与「例题精讲」的整篇喂入。"
)
ATTACH_IMAGE_EN = (
    "Image **{name}** received and kept in this conversation.\n\n"
    "The mock backend stores the preview only; once the vision model is wired up, "
    "MathGuide will read handwritten problems directly from photos. "
    "Meanwhile, type the problem text and I will solve it as usual."
)
ATTACH_FILE_EN = (
    "File **{name}** received (metadata only, {size} KB).\n\n"
    "Document parsing (PDF / lecture notes) arrives with the real file service."
)


def _is_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _strip_meta(prompt: str, cmd: str | None) -> str:
    """剥离前端可能遗留的 [cmd] 与 [attach:...] 前缀,仅留原始问题"""
    text = re.sub(r"^\[[^\]]*\]\s*", "", prompt)
    if cmd and text.startswith(cmd):
        text = text[len(cmd):].lstrip(": ： ")
    return text.strip()


def _pick_knowledge(text: str, zh: bool) -> tuple[str, str] | None:
    """按关键词命中知识条目,返回 (标题, 对应语言的正文);英文命中无英文正文时返回 None(走兜底)"""
    t = text.lower()
    for entry in KNOWN:
        if any(k in t for k in entry["keywords"]):
            if zh:
                return entry["title"], entry["body_zh"]
            if entry.get("body_en"):
                return entry["title_en"], entry["body_en"]
            return None
    return None


def build_reply(prompt: str, cmd: str | None = None) -> str:
    """生成一条完整回复(同步返回;chat.py 负责切片流式下发)"""
    prompt = (prompt or "").strip()
    if not prompt:
        return FALLBACK_ZH.format(level="进阶") if not cmd else f"{CMD_OPENERS.get(cmd, '')}\n\n{FALLBACK_ZH.format(level='进阶')}"
    zh = _is_chinese(prompt)

    # 附件消息(前缀契约 [attach:image|file]文件名)
    m = re.match(r"^\[attach:(image|file)\](.+)$", prompt)
    if m:
        kind, name = m.group(1), m.group(2).strip()
        size_kb = ""
        if not zh:
            return ATTACH_IMAGE_EN if kind == "image" else ATTACH_FILE_EN
        return (ATTACH_IMAGE_ZH if kind == "image" else ATTACH_FILE_ZH).format(name=name, size=size_kb or "—")

    text = _strip_meta(prompt, cmd)
    level = judge_level(text)
    hit = _pick_knowledge(text, zh)

    if hit:
        title, body = hit
        if zh:
            section = f"**{title} · 概念讲解**\n\n**难度判定:** {LEVEL_ZH[level]}\n\n{body}"
            opener = CMD_OPENERS.get(cmd or "", "")
            return f"{opener}\n\n{section}" if opener else section
        return f"**{title} · Concept**\n\n**Level:** {LEVEL_EN[level]}\n\n{body}"

    # 未命中知识库:直接给方法论框架作答(难度仍由模型判定,不反问用户)
    if zh:
        fb = FALLBACK_ZH.format(level=LEVEL_ZH[level])
        opener = CMD_OPENERS.get(cmd or "", "")
        return f"{opener}\n\n{fb}" if opener else fb
    return FALLBACK_EN.format(level=LEVEL_EN[level])
