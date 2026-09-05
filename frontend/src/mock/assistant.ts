/**
 * 学习辅助模块的 Mock 助手(中英双语)。
 *
 * 讲解风格:每个数学概念都走"双轨讲解"——
 * 【专业表述】教科书式的精确定义与公式(严谨);
 * 【形象理解】生活化类比与几何画面(直觉)。
 *
 * 回复语言跟随 设置 → 语言;中英文关键词都参与匹配(用户可混用语言提问)。
 * 后端接入前:按「指令 / 难度 / 关键词」返回预设回答,
 * 并模拟真实的逐字流式输出。
 * 后端接入后:仅需替换 streamMockReply 的实现,上层组件无需改动。
 */
import { settingsState } from '@/stores/settings'

export interface StreamCallbacks {
  onDelta: (text: string) => void
  onDone: (full: string) => void
}

export interface MockStream {
  cancel(): void
}

/* ---------- 指令回复 ---------- */

const COMMAND_REPLIES_ZH: Record<string, string> = {
  概念动画演示: String.raw`已启动【概念动画演示】模式。以「函数极限」为例:

**专业表述** $\lim_{x \to a} f(x) = L$:

$$\forall \varepsilon > 0,\ \exists \delta > 0,\ 0 < |x - a| < \delta \Rightarrow |f(x) - L| < \varepsilon$$

**形象理解** 想象曲线上的一个小点在滑动:不管别人画出多窄的水平误差带,只要 $x$ 足够靠近 $a$,函数值就永远落在带内 —— "你划多小的圈,我都能保证函数值跑进圈里"。

**动画演示面板将在下一版本接入**,届时此处会渲染可交互的曲线动画。你可以先告诉我具体想看哪个概念(极限、导数、泰勒展开、定积分……),我会准备对应的演示脚本。`,

  例题精讲: String.raw`【例题精讲】求极限:

$$\lim_{x \to 0} \frac{\sin x}{x}$$

**专业表述(解)** 这是重要极限。由夹逼准则,当 $0 < |x| < \frac{\pi}{2}$ 时,

$$\cos x < \frac{\sin x}{x} < 1$$

两边取极限,由 $\lim_{x\to 0}\cos x = 1$ 得:

$$\lim_{x \to 0} \frac{\sin x}{x} = 1$$

**形象理解** 在单位圆里,扇形面积恰好被两侧三角形夹住($\sin x < x < \tan x$),像三明治一样把 $\frac{\sin x}{x}$ 挤向 1。

**举一反三**:求 $\lim_{x\to 0}\frac{\tan x}{x}$。提示:写成 $\frac{\sin x}{x}\cdot\frac{1}{\cos x}$。`,

  章节知识导航: String.raw`【章节知识导航】高等数学(上册)知识结构:

**第一章 函数与极限** — 函数概念、数列极限、函数极限、无穷小与无穷大、连续与间断
**第二章 导数与微分** — 导数定义、求导法则、高阶导数、微分
**第三章 微分中值定理** — 罗尔 / 拉格朗日 / 柯西中值定理、洛必达法则、泰勒公式
**第四章 不定积分** — 换元积分法、分部积分法
**第五章 定积分** — 黎曼和、微积分基本定理、广义积分

输入章节名(如「第二章」)可展开该章节的详细知识点。`,

  错题归纳: String.raw`【错题归纳】请把错题发给我,我会帮你整理成结构化错题卡:

**错题卡模板**
- 题目 / 来源
- 错误答案与错误原因(概念不清 / 计算失误 / 方法选错)
- 正确解法与关键步骤
- 关联知识点与易错点提醒

典型易错点示例:「求 $\lim_{x\to 0} x\cdot\ln x$ 时直接代入得到 $0\cdot(-\infty)$,忽略了 $0\cdot\infty$ 型需要先变形」——先化为 $\frac{\ln x}{1/x}$,再用洛必达法则。

现在你可以粘贴一道错题试试。`,

  公式查询手册: String.raw`【公式查询手册】常用公式速查:

**重要极限**
$$\lim_{x\to 0}\frac{\sin x}{x}=1,\qquad \lim_{x\to\infty}\left(1+\frac{1}{x}\right)^x=e$$

**泰勒展开**
$$f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^n$$

**牛顿-莱布尼茨公式**
$$\int_a^b f(x)\,\mathrm{d}x = F(b)-F(a)$$

**分部积分**
$$\int u\,\mathrm{d}v = uv - \int v\,\mathrm{d}u$$

输入具体公式名称(如「泰勒」「格林公式」「傅里叶」)可查询更多 —— 每个公式我都会同时给出专业表述与形象理解。`,
}

/* ---------- 指令回复(英文) ---------- */

const COMMAND_REPLIES_EN: Record<string, string> = {
  概念动画演示: String.raw`【Concept Animation】mode started. Taking "the limit of a function" as an example:

**Rigorous statement** $\lim_{x \to a} f(x) = L$:

$$\forall \varepsilon > 0,\ \exists \delta > 0,\ 0 < |x - a| < \delta \Rightarrow |f(x) - L| < \varepsilon$$

**Intuition** Imagine a point sliding along the curve: no matter how thin a horizontal strip anyone draws, once $x$ gets close enough to $a$, the function value always stays inside the strip — "draw the circle as small as you want; the function value is guaranteed to fall inside."

**The animation panel ships in the next version** — an interactive curve animation will render right here. Tell me which concept you want to see (limits, derivatives, Taylor expansions, definite integrals…), and I'll prepare the script.`,

  例题精讲: String.raw`【Worked Example】Evaluate:

$$\lim_{x \to 0} \frac{\sin x}{x}$$

**Rigorous solution** This is a fundamental limit. By the squeeze theorem, for $0 < |x| < \frac{\pi}{2}$,

$$\cos x < \frac{\sin x}{x} < 1$$

Taking limits on all sides and using $\lim_{x\to 0}\cos x = 1$:

$$\lim_{x \to 0} \frac{\sin x}{x} = 1$$

**Intuition** In the unit circle the sector area is sandwiched between two triangles ($\sin x < x < \tan x$), squeezing $\frac{\sin x}{x}$ toward 1 like a sandwich.

**Extend it**: evaluate $\lim_{x\to 0}\frac{\tan x}{x}$. Hint: write it as $\frac{\sin x}{x}\cdot\frac{1}{\cos x}$.`,

  章节知识导航: String.raw`【Chapter Navigator】Higher mathematics (vol. 1) structure:

**Ch.1 Functions & Limits** — functions, sequence limits, function limits, infinitesimals, continuity
**Ch.2 Derivatives & Differentials** — definition, differentiation rules, higher derivatives, differentials
**Ch.3 Mean Value Theorems** — Rolle / Lagrange / Cauchy, L'Hôpital's rule, Taylor's formula
**Ch.4 Indefinite Integrals** — substitution, integration by parts
**Ch.5 Definite Integrals** — Riemann sums, the fundamental theorem of calculus, improper integrals

Enter a chapter name (e.g. "Chapter 2") to expand its details.`,

  错题归纳: String.raw`【Mistake Review】Paste the problem you got wrong and I'll organize it into a structured card:

**Mistake card template**
- Problem / source
- Your answer and the cause (concept confusion / arithmetic slip / wrong method)
- Correct solution with key steps
- Related concepts and traps to remember

A typical trap: "plugging in directly in $\lim_{x\to 0} x\cdot\ln x$ gives $0\cdot(-\infty)$" — but $0\cdot\infty$ forms must be reshaped first: write it as $\frac{\ln x}{1/x}$ and apply L'Hôpital.

Paste a mistake and try it now.`,

  公式查询手册: String.raw`【Formula Handbook】Common formulas at a glance:

**Fundamental limits**
$$\lim_{x\to 0}\frac{\sin x}{x}=1,\qquad \lim_{x\to\infty}\left(1+\frac{1}{x}\right)^x=e$$

**Taylor expansion**
$$f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^n$$

**Newton–Leibniz formula**
$$\int_a^b f(x)\,\mathrm{d}x = F(b)-F(a)$$

**Integration by parts**
$$\int u\,\mathrm{d}v = uv - \int v\,\mathrm{d}u$$

Enter a formula name (e.g. "Taylor", "Green", "Fourier") for more — each comes with both a rigorous statement and intuition.`,
}

/* ---------- 附件回复 ---------- */

const ATTACH_IMAGE_ZH = `【收到图片】已收到你上传的图片。当前为演示环境,图像识别与"拍照搜题"将在接入后端后开放 —— 届时上传题目照片,MG 会自动识别并给出解答。`

const ATTACH_FILE_ZH = `【收到文件】已收到文件,当前为演示环境,文件内容解析将在接入后端后开放(支持从本地、微信、QQ、WPS Office 等位置传输的文件)。`

const ATTACH_IMAGE_EN = `【Image received】I got your image. In this demo, image recognition and photo-based problem solving will open once the backend is connected — then you can upload a problem photo and MG will read and solve it.`

const ATTACH_FILE_EN = `【File received】I got the file. In this demo, file content parsing will open once the backend is connected (files can come from local storage, WeChat, QQ, WPS Office and more).`

/* ---------- 难度回复 ---------- */

const COMPETITION_REPLY = String.raw`【竞赛拔尖】示例(经典竞赛题):

证明:对任意 $n\in\mathbb{N}^{+}$,

$$1+\frac{1}{2}+\frac{1}{3}+\cdots+\frac{1}{n} > \ln(n+1)$$

**专业表述(积分比较法)** 当 $k \le x \le k+1$ 时 $\frac{1}{x}\le\frac{1}{k}$,于是

$$\int_{1}^{n+1}\frac{\mathrm{d}x}{x} = \ln(n+1) < \sum_{k=1}^{n}\frac{1}{k}$$

**形象理解** 把 $\frac{1}{k}$ 看成宽 1、高 $\frac{1}{k}$ 的一排砖块;曲线 $y=\frac{1}{x}$ 始终贴着砖块的下沿,所以"曲线下面积"必然小于"砖块总面积"。这是离散求和与连续积分的经典对垒。

**竞赛工具箱**:夹逼准则、Cauchy 不等式、Abel 求和、构造辅助函数、放缩与归纳。把你遇到的竞赛题发给我,我来拆解思路。`

const BASIC_REPLY = String.raw`【基础入门】讲解数学概念时,我会用两条轨道帮助你:

**专业表述** — 教科书式的精确定义与公式,保证严谨;
**形象理解** — 生活化类比与几何画面,建立直觉。

比如「极限」:专业语言是 $\varepsilon$-$\delta$ 定义;形象地说,就是"你划多小的圈,我都能保证函数值跑进圈里"。

告诉我你正在学的概念(例如「什么是导数」「极限是什么」),我按这两条轨道为你讲解。`

/* ---------- 难度回复(英文) ---------- */

const COMPETITION_EN = String.raw`【Competition level】Example (a classic):

Prove that for every $n\in\mathbb{N}^{+}$,

$$1+\frac{1}{2}+\frac{1}{3}+\cdots+\frac{1}{n} > \ln(n+1)$$

**Rigorous (integral comparison)** Since $\frac{1}{x}\le\frac{1}{k}$ for $k \le x \le k+1$,

$$\int_{1}^{n+1}\frac{\mathrm{d}x}{x} = \ln(n+1) < \sum_{k=1}^{n}\frac{1}{k}$$

**Intuition** View each $\frac{1}{k}$ as a brick of width 1 and height $\frac{1}{k}$; the curve $y=\frac{1}{x}$ always runs below the bricks' bottom edge, so the area under the curve must be smaller than the total brick area. A classic duel between a discrete sum and a continuous integral.

**Competition toolbox**: squeeze theorem, Cauchy's inequality, Abel summation, auxiliary functions, scaling and induction. Send me the competition problem you are facing — I'll unpack the strategy.`

const BASIC_EN = String.raw`【Beginner friendly】I explain every concept along two tracks:

**Rigorous statement** — the textbook-precise definition and formulas;
**Intuition** — everyday analogies and geometric pictures.

For "limits": the rigorous language is the $\varepsilon$-$\delta$ definition; intuitively, "draw the circle as small as you want — the function value is guaranteed to fall inside."

Tell me the concept you're learning (e.g. "what is a derivative?"), and I'll walk both tracks.`

/* ---------- 关键词回复(双轨讲解:专业表述 + 形象理解) ---------- */

const KEYWORD_ZH: Array<[string, string]> = [
  [
    '斯托克斯',
    String.raw`**斯托克斯公式**

**专业表述** 设 $\Sigma$ 为分片光滑曲面,$\mathbf{F}$ 连续可微:

$$\oint_{\partial\Sigma} \mathbf{F}\cdot\mathrm{d}\mathbf{r} = \iint_{\Sigma} (\nabla\times\mathbf{F})\cdot\mathrm{d}\mathbf{S}$$

**形象理解** 想象一片水面上的漩涡:小船沿边界划一整圈,感受到的总旋转力,恰好等于水面内部所有小漩涡的叠加。边界上的"环量" = 内部"旋度"的总和 —— 把绕圈的功换算成圈里的旋转。`,
  ],
  [
    '格林',
    String.raw`**格林公式**

**专业表述**

$$\oint_{\partial D} P\,\mathrm{d}x + Q\,\mathrm{d}y = \iint_D \left(\frac{\partial Q}{\partial x} - \frac{\partial P}{\partial y}\right)\mathrm{d}x\,\mathrm{d}y$$

**形象理解** 沿区域边界逆时针走一圈所做的"功",等于把区域内部每一点的微小旋转(涡量)全部加起来。就像用体温计测出皮肤温度,可以反推出体内总热量。`,
  ],
  [
    '柯西-黎曼',
    String.raw`**柯西-黎曼方程**(复变函数可导的充要条件)

**专业表述** 设 $f(z)=u(x,y)+i\,v(x,y)$:

$$\frac{\partial u}{\partial x} = \frac{\partial v}{\partial y},\qquad \frac{\partial u}{\partial y} = -\frac{\partial v}{\partial x}$$

**形象理解** 解析函数是"保角映射":局部的小图形经过它只会被旋转和缩放,形状不变 —— 柯西-黎曼方程就是"映射不撕扯、不翻转图形"的数学条件。`,
  ],
  [
    '拉格朗日乘子',
    String.raw`**拉格朗日乘子法**(条件极值)

**专业表述** 求 $f(x,y)$ 在约束 $g(x,y)=0$ 下的极值,构造

$$L(x,y,\lambda) = f(x,y) + \lambda\, g(x,y)$$

令 $\nabla L = 0$,即 $\frac{\partial L}{\partial x}=0,\ \frac{\partial L}{\partial y}=0,\ g(x,y)=0$,解出候选点再判断极值。

**形象理解** 在等高线地形图上沿着一条山路走:最高点出现在"目标函数的等高线恰好与山路相切"的位置 —— 两条曲线相切,意味着两个梯度方向平行,这就是乘子法的几何本质。`,
  ],
  [
    '正态分布',
    String.raw`**正态分布**

**专业表述** 概率密度函数:

$$f(x)=\frac{1}{\sigma\sqrt{2\pi}}\,e^{-\frac{(x-\mu)^2}{2\sigma^2}}$$

$\mu$ 为均值,$\sigma$ 为标准差;$\sigma$ 越小曲线越集中。标准正态分布 $\mu=0,\ \sigma=1$。

**形象理解** 大量微小独立随机因素叠加的结果就是"钟形曲线":身高、测量误差都聚集在平均值附近,离得越远越稀少,且左右对称。`,
  ],
  [
    '特征值',
    String.raw`**特征值与特征向量**

**专业表述**

$$A\mathbf{v} = \lambda \mathbf{v},\quad \mathbf{v}\neq 0$$

求法:解特征方程 $\det(A-\lambda I)=0$ 得特征值,再对每个 $\lambda$ 解 $(A-\lambda I)\mathbf{v}=0$ 得特征向量。

**形象理解** 把线性变换想象成一台拉伸机:大多数方向会被扭歪,但某些特殊方向上的向量只被拉长或缩短、方向保持不变 —— 拉伸的倍数就是特征值。`,
  ],
  [
    '行列式',
    String.raw`**行列式**

**专业表述**

$$\det A = \sum_{\sigma\in S_n} \mathrm{sgn}(\sigma)\prod_{i=1}^{n} a_{i,\sigma(i)}$$

常用性质:两行互换变号、某行乘 $k$ 行列式乘 $k$、某行加到另一行不变。二阶:$\begin{vmatrix} a & b \\ c & d \end{vmatrix} = ad - bc$。

**形象理解** 行列式是线性变换的"体积缩放因子":绝对值表示面积/体积被放大的倍数,负号表示发生了翻转。行列式为 0,意味着图形被压扁了一维。`,
  ],
  [
    '泰勒',
    String.raw`**泰勒公式**

**专业表述** 在 $x=a$ 处展开:

$$f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^n$$

当 $a=0$ 时为麦克劳林公式。例如:

$$e^x = 1 + x + \frac{x^2}{2!} + \frac{x^3}{3!} + \cdots$$

**形象理解** 用多项式"临摹"复杂函数:在一点附近,先对齐高度(常数项),再对齐坡度(一阶项),再对齐弯曲程度(二阶项)…… 对齐得越细,临摹得越像。`,
  ],
  [
    '级数',
    String.raw`**数项级数**的收敛判别

**专业表述** 正项级数 $\sum a_n$ 的常用判别法:
- 比值判别法:$\lim\frac{a_{n+1}}{a_n} = \rho$,$\rho<1$ 收敛,$\rho>1$ 发散
- p-级数:$\sum\frac{1}{n^p}$ 在 $p>1$ 时收敛,$p\le 1$ 时发散

交错级数用莱布尼茨判别法。

**形象理解** 无穷多项相加是否有意义,就像"无限分期往银行存钱,总和是否有上限"。p-级数是最常用的标尺:每项衰减得比 $\frac{1}{n}$ 更快,总和才有限。`,
  ],
  [
    '柯西',
    String.raw`**柯西-施瓦茨不等式**

**专业表述**

$$\left(\sum_{i=1}^{n} a_i b_i\right)^2 \le \left(\sum_{i=1}^{n} a_i^2\right)\left(\sum_{i=1}^{n} b_i^2\right)$$

积分形式:$\left(\int fg\right)^2 \le \int f^2 \int g^2$。

**形象理解** 本质是"夹角的余弦不超过 1":向量的内积等于模长乘积乘余弦,余弦至多为 1;几何上就是"投影长度不会超过原长"。`,
  ],
  [
    '梯度',
    String.raw`**梯度**

**专业表述**

$$\nabla f = \left(\frac{\partial f}{\partial x}, \frac{\partial f}{\partial y}, \frac{\partial f}{\partial z}\right)$$

沿单位向量 $\mathbf{u}$ 的方向导数:$\frac{\partial f}{\partial \mathbf{u}} = \nabla f \cdot \mathbf{u}$。

**形象理解** 爬山时"最陡上坡方向"就是梯度:哪边坡最陡,向量就指向哪边,坡越陡向量越长。沿等高线横着走,梯度分量为零。`,
  ],
  [
    '不等式',
    COMPETITION_REPLY,
  ],
  [
    '证明',
    String.raw`**证明题的常用方法**

**专业表述**
1. **直接法**:从条件出发逐步推导结论
2. **反证法**:假设结论不成立,推出矛盾
3. **数学归纳法**:适合与自然数 $n$ 有关的命题
4. **构造法**:构造辅助函数 / 辅助数列 / 反例

**形象理解** 证明像下棋:开局是已知条件,终局是待证结论,方法是棋路。反证法就是"假设对手赢了,却发现必须吃掉自己",矛盾暴露,原命题成立。`,
  ],
  [
    '中值定理',
    String.raw`**微分中值定理**

**专业表述** 设 $f$ 在 $[a,b]$ 连续、$(a,b)$ 可导:
- 罗尔定理:若 $f(a)=f(b)$,则存在 $\xi\in(a,b)$ 使 $f'(\xi)=0$
- 拉格朗日中值定理:存在 $\xi\in(a,b)$ 使 $f'(\xi)=\frac{f(b)-f(a)}{b-a}$

**形象理解** 开车两小时走了 160 公里,平均速度 80:途中必有某一瞬间,仪表盘恰好显示 80 —— 拉格朗日中值定理说的就是这个"瞬间速度等于平均速度"。`,
  ],
  [
    '极限',
    String.raw`**函数极限的定义($\varepsilon$-$\delta$ 语言)**

**专业表述**

$$\lim_{x\to a} f(x)=L \iff \forall\varepsilon>0,\ \exists\delta>0,\ 0<|x-a|<\delta \Rightarrow |f(x)-L|<\varepsilon$$

**形象理解** "任意逼近"的攻防游戏:对手(任意的 $\varepsilon$)画出多小的误差带,我们(存在 $\delta$)都能找到一个足够靠近 $a$ 的邻域,让所有函数值稳稳落进带里 —— 你划多小的圈,我都能保证函数值跑进圈里。

想看得更直观?点击指令栏【概念动画演示】。`,
  ],
  [
    '导数',
    String.raw`**导数的定义**

**专业表述**

$$f'(x)=\lim_{h\to 0}\frac{f(x+h)-f(x)}{h}$$

几何意义:曲线在该点切线的斜率。

**形象理解** 导数就是"瞬时变化率":先算两点的平均速度(割线斜率),再让两点无限靠近,割线变成切线,平均速度变成瞬时速度 —— 汽车仪表盘显示的速度,就是路程函数的导数。`,
  ],
  [
    '积分',
    String.raw`**定积分与微积分基本定理**

**专业表述** 黎曼和定义:

$$\int_a^b f(x)\,\mathrm{d}x=\lim_{\max\Delta x_i\to 0}\sum_{i=1}^{n}f(x_i^{*})\Delta x_i$$

牛顿-莱布尼茨公式:若 $F'(x)=f(x)$,则 $\int_a^b f(x)\,\mathrm{d}x=F(b)-F(a)$。

**形象理解** 定积分 = 曲线下的面积:把区域切成无数细条,再累加(黎曼和)。而牛顿-莱布尼茨公式提供了捷径:不用一条条累加,只要找到"导数等于被积函数"的原函数,代入两个端点相减即可 —— 把体力活变成查表。`,
  ],
  [
    '傅里叶',
    String.raw`**傅里叶变换**

**专业表述**

$$\hat{f}(\xi)=\int_{-\infty}^{\infty}f(x)\,e^{-2\pi i x\xi}\,\mathrm{d}x$$

**形象理解** 傅里叶变换是"音乐的色谱仪":一段复杂的声音,本质是不同音高纯音的叠加;变换的结果告诉你每个频率成分占多大分量。信号处理、图像压缩、解偏微分方程都靠它。`,
  ],
  [
    '微分方程',
    String.raw`**一阶线性微分方程**

**专业表述**

$$y'+P(x)\,y=Q(x)$$

通解公式:

$$y=e^{-\int P(x)\,\mathrm{d}x}\left[\int Q(x)\,e^{\int P(x)\,\mathrm{d}x}\,\mathrm{d}x+C\right]$$

**形象理解** 微分方程描述的是"变化规律"而非状态本身:已知当前位置和速度如何随时间改变,就能预言未来的轨迹。它就是物理定律的数学写法 —— 牛顿第二定律 $F=ma$ 就是一个二阶微分方程。`,
  ],
]

/* ---------- 关键词回复(英文,与中文列表一一对应) ---------- */

const KEYWORD_EN: Array<[string, string]> = [
  [
    'stokes',
    String.raw`**Stokes' Theorem**

**Rigorous statement** For a piecewise-smooth surface $\Sigma$ and a continuously differentiable field $\mathbf{F}$:

$$\oint_{\partial\Sigma} \mathbf{F}\cdot\mathrm{d}\mathbf{r} = \iint_{\Sigma} (\nabla\times\mathbf{F})\cdot\mathrm{d}\mathbf{S}$$

**Intuition** Picture whirlpools on a pond: the total rotational force felt by a boat going once around the boundary equals the sum of all the tiny whirlpools inside. Circulation on the boundary = total curl inside — the work along the loop is traded for the spin inside.`,
  ],
  [
    'green',
    String.raw`**Green's Theorem**

**Rigorous statement**

$$\oint_{\partial D} P\,\mathrm{d}x + Q\,\mathrm{d}y = \iint_D \left(\frac{\partial Q}{\partial x} - \frac{\partial P}{\partial y}\right)\mathrm{d}x\,\mathrm{d}y$$

**Intuition** Going counterclockwise once around the boundary "earns" work equal to summing the tiny rotation (vorticity) at every point inside — like inferring total body heat from skin temperature.`,
  ],
  [
    'cauchy-riemann',
    String.raw`**The Cauchy–Riemann Equations** (the condition for complex differentiability)

**Rigorous statement** Writing $f(z)=u(x,y)+i\,v(x,y)$:

$$\frac{\partial u}{\partial x} = \frac{\partial v}{\partial y},\qquad \frac{\partial u}{\partial y} = -\frac{\partial v}{\partial x}$$

**Intuition** Analytic functions are "conformal maps": locally they only rotate and scale small shapes, never tearing them — the C–R equations are exactly the "no tearing, no flipping" condition.`,
  ],
  [
    'lagrange',
    String.raw`**Lagrange Multipliers** (constrained extrema)

**Rigorous statement** To extremize $f(x,y)$ subject to $g(x,y)=0$, build

$$L(x,y,\lambda) = f(x,y) + \lambda\, g(x,y)$$

and solve $\nabla L = 0$: $\frac{\partial L}{\partial x}=0,\ \frac{\partial L}{\partial y}=0,\ g(x,y)=0$. Check the candidates for extrema.

**Intuition** On a contour map, hiking along a trail, the extreme point lies where your target contour line is tangent to the trail — tangency means the two gradients are parallel. That is the whole trick.`,
  ],
  [
    'normal distribution',
    String.raw`**The Normal Distribution**

**Rigorous statement** Its probability density function:

$$f(x)=\frac{1}{\sigma\sqrt{2\pi}}\,e^{-\frac{(x-\mu)^2}{2\sigma^2}}$$

$\mu$ is the mean and $\sigma$ the standard deviation; smaller $\sigma$ means a tighter curve. The standard normal has $\mu=0,\ \sigma=1$.

**Intuition** Many small independent random effects add up to a "bell curve": heights and measurement errors cluster around the mean, symmetric, thinning toward the tails.`,
  ],
  [
    'eigenvalue',
    String.raw`**Eigenvalues and Eigenvectors**

**Rigorous statement**

$$A\mathbf{v} = \lambda \mathbf{v},\quad \mathbf{v}\neq 0$$

Solve $\det(A-\lambda I)=0$ for the eigenvalues, then $(A-\lambda I)\mathbf{v}=0$ for each eigenvector.

**Intuition** Think of the linear map as a stretching machine: most directions get twisted, but a few special directions are only stretched — their line stays put. The stretch factor is the eigenvalue.`,
  ],
  [
    'determinant',
    String.raw`**The Determinant**

**Rigorous statement**

$$\det A = \sum_{\sigma\in S_n} \mathrm{sgn}(\sigma)\prod_{i=1}^{n} a_{i,\sigma(i)}$$

Key properties: swapping rows flips the sign; multiplying a row by $k$ multiplies the determinant by $k$; adding one row to another changes nothing. In 2D: $\begin{vmatrix} a & b \\ c & d \end{vmatrix} = ad - bc$.

**Intuition** The determinant is the "volume scaling factor" of the map: its absolute value is how much area/volume gets multiplied, and the sign tells whether orientation flipped. Zero means a dimension got flattened.`,
  ],
  [
    'taylor',
    String.raw`**Taylor's Formula**

**Rigorous statement** Expanding around $x=a$:

$$f(x)=\sum_{n=0}^{\infty}\frac{f^{(n)}(a)}{n!}(x-a)^n$$

At $a=0$ it is the Maclaurin series. For example:

$$e^x = 1 + x + \frac{x^2}{2!} + \frac{x^3}{3!} + \cdots$$

**Intuition** Trace a complicated function with polynomials: at one point, first match the height (constant term), then the slope (linear term), then the curvature (quadratic term)… the more you match, the closer the tracing.`,
  ],
  [
    'series',
    String.raw`**Convergence Tests for Series**

**Rigorous statement** For a positive-term series $\sum a_n$:
- Ratio test: $\lim\frac{a_{n+1}}{a_n} = \rho$; $\rho<1$ converges, $\rho>1$ diverges
- p-series: $\sum\frac{1}{n^p}$ converges for $p>1$, diverges for $p\le 1$

Alternating series use Leibniz's test.

**Intuition** Whether infinitely many terms can add to something finite is like asking if infinite installments into a bank account stay bounded. The p-series is the yardstick: terms must decay faster than $\frac{1}{n}$.`,
  ],
  [
    'cauchy',
    String.raw`**The Cauchy–Schwarz Inequality**

**Rigorous statement**

$$\left(\sum_{i=1}^{n} a_i b_i\right)^2 \le \left(\sum_{i=1}^{n} a_i^2\right)\left(\sum_{i=1}^{n} b_i^2\right)$$

Integral form: $\left(\int fg\right)^2 \le \int f^2 \int g^2$.

**Intuition** It simply says the cosine of an angle is at most 1: the dot product is the product of lengths times the cosine — geometrically, a projection never exceeds the original length.`,
  ],
  [
    'gradient',
    String.raw`**The Gradient**

**Rigorous statement**

$$\nabla f = \left(\frac{\partial f}{\partial x}, \frac{\partial f}{\partial y}, \frac{\partial f}{\partial z}\right)$$

Directional derivative along a unit vector $\mathbf{u}$: $\frac{\partial f}{\partial \mathbf{u}} = \nabla f \cdot \mathbf{u}$.

**Intuition** Hiking uphill, the steepest ascent direction is the gradient — the steeper the slope, the longer the vector. Walking along a contour line, the gradient component vanishes.`,
  ],
  [
    'inequality',
    COMPETITION_EN,
  ],
  [
    'proof',
    String.raw`**Common Proof Techniques**

**Rigorous methods**
1. **Direct proof**: derive the conclusion step by step from the assumptions
2. **Contradiction**: assume the conclusion fails, derive a contradiction
3. **Induction**: for statements depending on a natural number $n$
4. **Construction**: build an auxiliary function / sequence / counterexample

**Intuition** A proof is a chess game: the opening is your assumptions, the endgame is the conclusion, and the methods are your moves. Contradiction is "assume your opponent wins — then they must capture themselves."`,
  ],
  [
    'mean value',
    String.raw`**The Mean Value Theorem**

**Rigorous statement** Let $f$ be continuous on $[a,b]$ and differentiable on $(a,b)$:
- Rolle's theorem: if $f(a)=f(b)$, some $\xi\in(a,b)$ has $f'(\xi)=0$
- Lagrange's MVT: some $\xi\in(a,b)$ satisfies $f'(\xi)=\frac{f(b)-f(a)}{b-a}$

**Intuition** Drive 160 km in two hours — average speed 80. At some instant the speedometer must read exactly 80: "the instantaneous speed equals the average speed" somewhere along the way.`,
  ],
  [
    'limit',
    String.raw`**The $\varepsilon$-$\delta$ Definition of a Limit**

**Rigorous statement**

$$\lim_{x\to a} f(x)=L \iff \forall\varepsilon>0,\ \exists\delta>0,\ 0<|x-a|<\delta \Rightarrow |f(x)-L|<\varepsilon$$

**Intuition** A game of "arbitrary closeness": no matter how thin a strip (the challenger's $\varepsilon$) is drawn, we can find a neighborhood (our $\delta$) near $a$ where every function value lands inside — "you draw the circle as small as you want; the function value is guaranteed to fall inside."

Want to see it move? Tap the 【Concept Animation】 command.`,
  ],
  [
    'derivative',
    String.raw`**The Definition of the Derivative**

**Rigorous statement**

$$f'(x)=\lim_{h\to 0}\frac{f(x+h)-f(x)}{h}$$

Geometrically: the slope of the tangent line at that point.

**Intuition** The derivative is the "instantaneous rate of change": average speed over an interval (a secant slope) becomes instantaneous speed as the interval shrinks to zero (the tangent). A car's speedometer reads the derivative of distance.`,
  ],
  [
    'integral',
    String.raw`**Definite Integrals and the Fundamental Theorem**

**Rigorous statement** The Riemann sum definition:

$$\int_a^b f(x)\,\mathrm{d}x=\lim_{\max\Delta x_i\to 0}\sum_{i=1}^{n}f(x_i^{*})\Delta x_i$$

Newton–Leibniz: if $F'(x)=f(x)$, then $\int_a^b f(x)\,\mathrm{d}x=F(b)-F(a)$.

**Intuition** The definite integral is the area under the curve: slice it into thin strips and add them up. Newton–Leibniz is the shortcut — instead of summing strips, find the antiderivative and subtract at the endpoints: brute force becomes a table lookup.`,
  ],
  [
    'fourier',
    String.raw`**The Fourier Transform**

**Rigorous statement**

$$\hat{f}(\xi)=\int_{-\infty}^{\infty}f(x)\,e^{-2\pi i x\xi}\,\mathrm{d}x$$

**Intuition** Fourier is the "spectrometer of music": a complex sound is a superposition of pure tones, and the transform tells you how much of each frequency is present. Signal processing, image compression and PDEs all rely on it.`,
  ],
  [
    'differential equation',
    String.raw`**First-Order Linear Differential Equations**

**Rigorous statement**

$$y'+P(x)\,y=Q(x)$$

General solution:

$$y=e^{-\int P(x)\,\mathrm{d}x}\left[\int Q(x)\,e^{\int P(x)\,\mathrm{d}x}\,\mathrm{d}x+C\right]$$

**Intuition** A differential equation describes the "law of change" rather than a state: given where you are and how the velocity changes, you can predict the whole path. Newton's second law $F=ma$ is a second-order ODE — physics is written in differential equations.`,
  ],
]

const DEFAULT_ZH = `你好,我是 MG 学习助手,专注高等数学 —— 从基础入门、进阶提高到竞赛拔尖,都可以问我。

讲解概念时,我会同时给出两条轨道:**专业表述**(严谨定义与公式)和**形象理解**(生活化类比与几何画面)。

你可以直接输入问题,例如:「求 sinx/x 在 0 处的极限」;也可以点击上方指令栏快速执行专项功能:

▶ 概念动画演示 —— 让数学概念动起来
✎ 例题精讲 —— 经典例题与举一反三
◈ 章节知识导航 —— 高数知识结构
✖ 错题归纳 —— 错题结构化整理
∫ 公式查询手册 —— 常用公式速查

现在,请提出你的第一个问题。`

const DEFAULT_EN = `Hello, I'm MG, your higher mathematics assistant — from beginner basics to competition-level challenges.

For every concept, you get two tracks: a **rigorous statement** (precise definitions and formulas) and an **intuition** (everyday analogies and geometric pictures).

Ask directly, e.g. "What is the limit of sinx/x at 0?" — or tap a command below:

▶ Concept Animation — make math concepts move
✎ Worked Examples — classic problems and extensions
◈ Chapter Navigator — the map of higher mathematics
✖ Mistake Review — structured error analysis
∫ Formula Handbook — formulas at a glance

Ask me your first question.`

/* ---------- 路由与流式输出 ---------- */

function pickReply(prompt: string): string {
  const en = settingsState.language === 'en'
  const commands = en ? COMMAND_REPLIES_EN : COMMAND_REPLIES_ZH
  const competition = en ? COMPETITION_EN : COMPETITION_REPLY
  const basic = en ? BASIC_EN : BASIC_REPLY
  const primary = en ? KEYWORD_EN : KEYWORD_ZH
  const secondary = en ? KEYWORD_ZH : KEYWORD_EN

  const m = prompt.match(/^\[(.+?)\]/)
  if (m) {
    const reply = commands[m[1]]
    if (reply) return reply
  }
  // 附件消息
  if (prompt.startsWith('[attach:image]')) return en ? ATTACH_IMAGE_EN : ATTACH_IMAGE_ZH
  if (prompt.startsWith('[attach:file]')) return en ? ATTACH_FILE_EN : ATTACH_FILE_ZH
  // 竞赛/拔尖难度优先匹配(中英文)
  if (/(竞赛|奥数|IMO|CMO|难题|挑战|压轴|拔尖|competition|olympiad|hard problem|challenging)/i.test(prompt)) {
    return competition
  }
  const lower = prompt.toLowerCase()
  // 主语言关键词优先,次语言兜底(允许混用语言提问);两种列表一一对应
  for (let i = 0; i < primary.length; i++) {
    if (primary[i][0].split('|').some((kw) => lower.includes(kw))) return primary[i][1]
  }
  for (let i = 0; i < secondary.length; i++) {
    if (secondary[i][0].split('|').some((kw) => lower.includes(kw))) return primary[i]?.[1] ?? secondary[i][1]
  }
  // 基础入门风格的问题(中英文)
  if (/(基础|入门|初学|是什么|定义|概念|怎么理解|通俗|新手|what is|definition|beginner|basic|intuitive)/i.test(prompt)) {
    return basic
  }
  return en ? DEFAULT_EN : DEFAULT_ZH
}

/** 模拟逐字流式输出(2~3 字符/步,约 26ms/步) */
export function streamMockReply(prompt: string, cb: StreamCallbacks): MockStream {
  const reply = pickReply(prompt)
  let cancelled = false
  let i = 0
  const timer = setInterval(() => {
    if (cancelled) return
    const step = 2 + Math.floor(Math.random() * 2)
    const chunk = reply.slice(i, i + step)
    i += step
    if (chunk) cb.onDelta(chunk)
    if (i >= reply.length) {
      clearInterval(timer)
      cb.onDone(reply)
    }
  }, 26)
  return {
    cancel() {
      cancelled = true
      clearInterval(timer)
    },
  }
}
