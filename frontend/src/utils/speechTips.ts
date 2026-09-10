/**
 * 念法速查贴士(语音输入配套):数学符号/式子的标准口语念法,中英双语。
 * 静态文案零模型成本;「照着念」是保证语音转写准确率的关键约定。
 */

export interface SpeechTip {
  zh: string
  en: string
  formula: string
}

export interface TipGroup {
  title: [string, string]
  items: SpeechTip[]
}

export const TIP_GROUPS: TipGroup[] = [
  {
    title: ['函数与符号', 'Functions & Symbols'],
    items: [
      { zh: '“f x”或“f 括号 x”', en: '“f of x”', formula: 'f(x)' },
      { zh: '“g x”——任意字母都能当函数名', en: '“g of x” — any letter can name a function', formula: 'g(x)' },
      { zh: '“斐 x”(希腊字母 φ 当函数名)', en: '“phi of x”', formula: 'φ(x)' },
      { zh: '“普西 x”(ψ 当函数名)', en: '“psi of x”', formula: 'ψ(x)' },
      { zh: '“u t”“v t”——自变量也可以是任意字母', en: '“u of t”, “v of t” — the variable can be any letter too', formula: 'u(t), v(t)' },
      { zh: '“大 F x”——大小写要念出来,小写 f 和大写 F 是两个函数', en: '“capital F of x” — say the case, f and F are different functions', formula: 'F(x)' },
      { zh: '“f 逆 x”', en: '“f inverse of x”', formula: 'f⁻¹(x)' },
      { zh: '“正弦 x”', en: '“sine x”', formula: 'sin x' },
      { zh: '“余弦 x”', en: '“cosine x”', formula: 'cos x' },
      { zh: '“自然对数 x”', en: '“natural log x”', formula: 'ln x' },
      { zh: '“x 的平方”', en: '“x squared”', formula: 'x²' },
      { zh: '“x 的立方”', en: '“x cubed”', formula: 'x³' },
      { zh: '“x 的 n 次方”', en: '“x to the n-th”', formula: 'xⁿ' },
      { zh: '“根号 x”', en: '“square root of x”', formula: '√x' },
      { zh: '“三次根号 x”', en: '“cube root of x”', formula: '∛x' },
      { zh: '“x 的绝对值”', en: '“absolute value of x”', formula: '|x|' },
      { zh: '“派”', en: '“pi”', formula: 'π' },
      { zh: '“无穷”', en: '“infinity”', formula: '∞' },
    ],
  },
  {
    title: ['希腊字母(常用命名)', 'Greek Letters (naming things)'],
    items: [
      { zh: '“阿尔法”', en: '“alpha”', formula: 'α' },
      { zh: '“贝塔”', en: '“beta”', formula: 'β' },
      { zh: '“伽马”', en: '“gamma”', formula: 'γ' },
      { zh: '“德尔塔”', en: '“delta”', formula: 'δ' },
      { zh: '“伊普西龙”', en: '“epsilon”', formula: 'ε' },
      { zh: '“西塔”', en: '“theta”', formula: 'θ' },
      { zh: '“兰布达”', en: '“lambda”', formula: 'λ' },
      { zh: '“缪”', en: '“mu”', formula: 'μ' },
      { zh: '“纽”', en: '“nu”', formula: 'ν' },
      { zh: '“克西”', en: '“xi”', formula: 'ξ' },
      { zh: '“柔”', en: '“rho”', formula: 'ρ' },
      { zh: '“西格玛”', en: '“sigma”', formula: 'σ' },
      { zh: '“套”', en: '“tau”', formula: 'τ' },
      { zh: '“斐”', en: '“phi”', formula: 'φ' },
      { zh: '“普西”', en: '“psi”', formula: 'ψ' },
      { zh: '“欧米伽”', en: '“omega”', formula: 'ω' },
      { zh: '“大写伽马”', en: '“capital gamma”', formula: 'Γ' },
      { zh: '“大写欧米伽”', en: '“capital omega”', formula: 'Ω' },
    ],
  },
  {
    title: ['高等数学符号', 'Higher-Math Symbols'],
    items: [
      { zh: '“求和,i 从一到 n”', en: '“sum from i equals one to n”', formula: '∑ᵢ₌₁ⁿ' },
      { zh: '“极限,x 趋于 a”', en: '“limit as x approaches a”', formula: 'limₓ→ₐ' },
      { zh: '“f 对 x 的偏导”', en: '“partial f over partial x”', formula: '∂f/∂x' },
      { zh: '“梯度 f”或“nabla f”', en: '“gradient of f” / “nabla f”', formula: '∇f' },
      { zh: '“积分 f x dx”', en: '“integral of f of x dx”', formula: '∫ f(x)dx' },
      { zh: '“二重积分”', en: '“double integral”', formula: '∬' },
      { zh: '“闭合路径积分”', en: '“closed line integral”', formula: '∮' },
      { zh: '“伊普西龙、德尔塔”', en: '“epsilon, delta”', formula: 'ε, δ' },
      { zh: '“推出 / 蕴含”', en: '“implies”', formula: '⇒' },
      { zh: '“等价于”', en: '“if and only if”', formula: '⇔' },
      { zh: '“x 属于 A”', en: '“x belongs to A”', formula: 'x ∈ A' },
      { zh: '“对任意 x”', en: '“for all x”', formula: '∀x' },
      { zh: '“存在 x”', en: '“there exists x”', formula: '∃x' },
      { zh: '“并集 / 交集”', en: '“union / intersection”', formula: '∪ / ∩' },
      { zh: '“x 的范数”', en: '“norm of x”', formula: '‖x‖' },
      { zh: '“A 的转置”', en: '“A transpose”', formula: 'Aᵀ' },
      { zh: '“A 的逆”', en: '“A inverse”', formula: 'A⁻¹' },
      { zh: '“行列式”', en: '“determinant”', formula: 'det(A)' },
      { zh: '“x 拔”或“x bar”', en: '“x bar”', formula: 'x̄' },
      { zh: '“n 的阶乘”', en: '“n factorial”', formula: 'n!' },
      { zh: '“A 在 B 发生条件下的概率”', en: '“probability of A given B”', formula: 'P(A|B)' },
      { zh: '“X 的期望”', en: '“expectation of X”', formula: 'E[X]' },
    ],
  },
  {
    title: ['更高阶符号', 'Advanced Symbols'],
    items: [
      { zh: '“伽马函数 n”', en: '“gamma function of n”', formula: 'Γ(n)' },
      { zh: '“大 O,n 方”', en: '“big O of n squared”', formula: 'O(n²)' },
      { zh: '“小 o”', en: '“little o”', formula: 'o(1)' },
      { zh: '“拉普拉斯算子 f”或“nabla 平方 f”', en: '“Laplacian of f” / “nabla squared f”', formula: '∇²f' },
      { zh: '“德尔塔 x”——增量', en: '“delta x” — an increment', formula: 'Δx' },
      { zh: '“空集”', en: '“empty set”', formula: '∅' },
      { zh: '“子集 / 真子集”', en: '“subset / proper subset”', formula: '⊆ / ⊂' },
      { zh: '“且 / 或 / 非”', en: '“and / or / not”', formula: '∧ / ∨ / ¬' },
      { zh: '“a 与 b 的内积”', en: '“inner product of a and b”', formula: '⟨a,b⟩' },
      { zh: '“a 点乘 b”', en: '“a dot b”', formula: 'a·b' },
      { zh: '“a 叉乘 b”', en: '“a cross b”', formula: 'a×b' },
      { zh: '“A 的迹”', en: '“trace of A”', formula: 'tr(A)' },
      { zh: '“矩阵的秩”', en: '“rank of the matrix”', formula: 'rank(A)' },
      { zh: '“A 张量积 B”', en: '“A tensor product B”', formula: 'A⊗B' },
      { zh: '“A 直和 B”', en: '“A direct sum B”', formula: 'A⊕B' },
      { zh: '“z 的共轭”', en: '“conjugate of z”', formula: 'z̄' },
      { zh: '“z 的实部 / 虚部”', en: '“real / imaginary part of z”', formula: 'Re(z), Im(z)' },
      { zh: '“z 的模”', en: '“modulus of z”', formula: '|z|' },
      { zh: '“X 服从均值为缪、方差为西格玛平方的正态分布”', en: '“X follows a normal distribution with mean mu and variance sigma squared”', formula: 'X~N(μ,σ²)' },
      { zh: '“n 取 k”(组合数)', en: '“n choose k”', formula: 'C(n,k)' },
    ],
  },
  {
    title: ['式子结构(念法决定写法)', 'Structure (how you say it matters)'],
    items: [
      { zh: '“a 分之 b”→ b/a;“b 除以 a”→ b÷a', en: '“b over a” → b/a; “b divided by a” → b÷a', formula: 'b/a' },
      { zh: '“根号下 x 加一”→ 整体开方', en: '“square root of x plus one” → whole thing under the root', formula: '√(x+1)' },
      { zh: '“x 下标 n”', en: '“x sub n”', formula: 'xₙ' },
      { zh: '“e 的 x 次方”', en: '“e to the x”', formula: 'eˣ' },
      { zh: '“从 a 到 b 对 f x 积分”', en: '“integral from a to b of f of x”', formula: '∫ₐᵇ f(x)dx' },
      { zh: '“f x 对 x 求导”', en: '“f prime of x”', formula: 'f′(x)' },
      { zh: '“f 两撇 x”——二阶导', en: '“f double prime of x”', formula: 'f″(x)' },
      { zh: '“f 三撇 x”——三阶导', en: '“f triple prime of x”', formula: 'f‴(x)' },
      { zh: '“f 的 n 阶导”——更高阶导', en: '“n-th derivative of f”', formula: 'f⁽ⁿ⁾(x)' },
      { zh: '“y 对 x 的二阶导”', en: '“d two y over d x squared”', formula: 'd²y/dx²' },
      { zh: '“f 对 x 的二阶偏导”', en: '“second partial derivative of f with respect to x”', formula: '∂²f/∂x²' },
      { zh: '“f 先对 x 再对 y 的混合偏导”', en: '“mixed partial of f, with respect to x then y”', formula: '∂²f/∂x∂y' },
      { zh: '“x 趋于 0”', en: '“x approaches zero”', formula: 'x→0' },
    ],
  },
  {
    title: ['完整示例', 'Full Examples'],
    items: [
      { zh: '“x 平方加 y 平方等于 z 平方”', en: '“x squared plus y squared equals z squared”', formula: 'x²+y²=z²' },
      { zh: '“从零到一,对 x 平方积分”', en: '“integral from zero to one of x squared”', formula: '∫₀¹ x² dx' },
      { zh: '“x 趋于无穷时,x 分之一趋于零”', en: '“as x approaches infinity, one over x approaches zero”', formula: 'limₓ→∞ 1/x = 0' },
    ],
  },
]
