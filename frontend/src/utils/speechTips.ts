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
    title: ['式子结构(念法决定写法)', 'Structure (how you say it matters)'],
    items: [
      { zh: '“a 分之 b”→ b/a;“b 除以 a”→ b÷a', en: '“b over a” → b/a; “b divided by a” → b÷a', formula: 'b/a' },
      { zh: '“根号下 x 加一”→ 整体开方', en: '“square root of x plus one” → whole thing under the root', formula: '√(x+1)' },
      { zh: '“x 下标 n”', en: '“x sub n”', formula: 'xₙ' },
      { zh: '“e 的 x 次方”', en: '“e to the x”', formula: 'eˣ' },
      { zh: '“从 a 到 b 对 f x 积分”', en: '“integral from a to b of f of x”', formula: '∫ₐᵇ f(x)dx' },
      { zh: '“f x 对 x 求导”', en: '“f prime of x”', formula: 'f′(x)' },
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
