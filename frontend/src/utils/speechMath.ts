/**
 * 语音数学本地编译器(P0):口语数学 → 数学符号,毫秒级纯本地,零成本零网络。
 * 覆盖标准念法(贴士约 90 条为测试集);自由发挥/口误由 LLM 后台精修兜底。
 *
 * 流水线:同音纠错 → 中文数字归一 → 词典(希腊字母/函数名/符号)→
 *         结构规则(幂/分数/根号/上下标/括号/积分/求和/导数…)→ 清理。
 * 结果缓存(LRU,localStorage):同句转写秒出,精修后的结果也入缓存。
 */
const SUP: Record<string, string> = {
  '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
  a: 'ᵃ', b: 'ᵇ', c: 'ᶜ', d: 'ᵈ', e: 'ᵉ', f: 'ᶠ', g: 'ᵍ', h: 'ʰ', i: 'ⁱ', j: 'ʲ', k: 'ᵏ', l: 'ˡ',
  m: 'ᵐ', n: 'ⁿ', o: 'ᵒ', p: 'ᵖ', r: 'ʳ', s: 'ˢ', t: 'ᵗ', u: 'ᵘ', v: 'ᵛ', w: 'ʷ', x: 'ˣ', y: 'ʸ', z: 'ᶻ',
}
const SUB: Record<string, string> = {
  '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
  a: 'ₐ', e: 'ₑ', h: 'ₕ', i: 'ᵢ', j: 'ⱼ', k: 'ₖ', l: 'ₗ', m: 'ₘ', n: 'ₙ', o: 'ₒ', p: 'ₚ', r: 'ᵣ',
  s: 'ₛ', t: 'ₜ', u: 'ᵤ', v: 'ᵥ', x: 'ₓ',
}

function sup(s: string): string {
  if (s.length === 1 && SUP[s]) return SUP[s]
  return `^${s}`
}
function sub(s: string): string {
  if (s.length === 1 && SUB[s]) return SUB[s]
  return `_${s}`
}

/* ---------- 1) 预替换(同音纠错 + 会被中文数字归一误伤的数学词,须在归一之前) ---------- */
const HOMOPHONES: [string, string][] = [
  ['屏方', '平方'], ['平房', '平方'], ['平放', '平方'],
  ['振兴', '正弦'], ['振贤', '正弦'], ['正玄', '正弦'],
  ['于弦', '余弦'], ['玉弦', '余弦'], ['鱼玄', '余弦'],
  ['郑切', '正切'], ['鱼切', '余切'], ['只数', '指数'], ['植树', '指数'],
  ['对述', '对数'], ['兑数', '对数'],
  ['转制', '转置'], ['专职', '转置'],
  ['举证', '矩阵'], ['正太分布', '正态分布'],
  ['鸡分', '积分'], ['七望', '期望'], ['防差', '方差'],
  ['行列士', '行列式'], ['航列式', '行列式'],
  ['迈克劳林', '麦克劳林'], ['泰乐', '泰勒'], ['洛比达', '洛必达'], ['罗比达', '洛必达'],
  ['中直定理', '中值定理'],
  ['两撇', '″'], ['三撇', '‴'], ['撇', '′'],
  ['二重积分', '∬'], ['三重积分', '∭'],
  ['二阶', '2阶'], ['三阶', '3阶'],
]

/* ---------- 2) 中文数字 → 阿拉伯 ---------- */
const CN_D: Record<string, number> = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 }

function cnInt(s: string): number {
  let total = 0
  let sec = 0
  let num = 0
  for (const ch of s) {
    if (CN_D[ch] !== undefined) { num = CN_D[ch]; continue }
    if (ch === '十') { sec += (num || 1) * 10; num = 0; continue }
    if (ch === '百') { sec += (num || 1) * 100; num = 0; continue }
    if (ch === '千') { sec += (num || 1) * 1000; num = 0; continue }
    if (ch === '万') { total = (total + sec + num) * 10000; sec = 0; num = 0; continue }
  }
  return total + sec + num
}

function cnToArabic(m: string): string {
  const [intPart, decPart] = m.split('点')
  const n = cnInt(intPart)
  if (decPart === undefined) return String(n)
  let frac = ''
  for (const ch of decPart) frac += String(CN_D[ch] ?? '')
  return `${n}.${frac}`
}

/* ---------- 3) 词典(长键优先,含函数名/希腊字母/符号) ---------- */
const DICT: [string, string][] = [
  ['大写伽马', 'Γ'], ['大写欧米伽', 'Ω'], ['伽马函数', 'Γ'], ['拉普拉斯算子', '∇²'],
  ['伊普西龙', 'ε'], ['阿尔法', 'α'], ['贝塔', 'β'], ['伽马', 'γ'], ['德尔塔', 'δ'],
  ['西塔', 'θ'], ['兰布达', 'λ'], ['缪', 'μ'], ['纽', 'ν'], ['克西', 'ξ'],
  ['柔', 'ρ'], ['西格玛', 'σ'], ['套', 'τ'], ['斐', 'φ'], ['普西', 'ψ'], ['欧米伽', 'ω'],
  ['自然对数', 'ln'], ['对数', 'log'], ['正弦', 'sin'], ['余弦', 'cos'], ['正切', 'tan'],
  ['余切', 'cot'], ['正割', 'sec'], ['余割', 'csc'],
  ['大于等于', '≥'], ['小于等于', '≤'], ['不等于', '≠'], ['约等于', '≈'],
  ['闭合路径积分', '∮'],
  ['张量积', '⊗'], ['直和', '⊕'], ['空集', '∅'], ['真子集', '⊂'], ['子集', '⊆'],
  ['并集', '∪'], ['交集', '∩'], ['推出', '⇒'], ['等价于', '⇔'], ['属于', '∈'], ['不属于', '∉'],
  ['对任意', '∀'], ['对任意的', '∀'], ['存在一个', '∃'], ['存在', '∃'], ['点乘', '·'], ['叉乘', '×'],
  ['除以', '÷'], ['乘以', '×'], ['减去', '−'],
  ['行列式', 'det'], ['阶乘', '!'],
  ['趋于', '→'], ['梯度', '∇'], ['nabla', '∇'],
  ['派', 'π'], ['无穷', '∞'], ['正无穷', '+∞'], ['负无穷', '−∞'],
  ['等于', '='], ['加', '+'], ['减', '−'], ['乘', '×'], ['除', '÷'],
]

/* ---------- 4) 结构规则(顺序敏感) ---------- */
const FN = `[fghFuvwφψ]`

export function normalizeSpeechCase(s: string): string {
  const caps: string[] = []
  let out = s
    .replace(/大写\s*([a-zA-Z])/g, (_, c: string) => {
      caps.push(c.toUpperCase())
      return `\u0000${caps.length - 1}\u0000`
    })
    .replace(/大\s*([a-zA-Z])(?![a-zA-Z])/g, (_, c: string) => {
      caps.push(c.toUpperCase())
      return `\u0000${caps.length - 1}\u0000`
    })
  // 只小写 ASCII 大写字母(不动希腊字母 Γ/Ω 等,toLowerCase 会把它们也变小写)
  out = out.replace(/[A-Z]/g, (c) => c.toLowerCase())
  return out.replace(/\u0000(\d+)\u0000/g, (_, i: string) => caps[Number(i)])
}

const STRUCT: ((s: string) => string)[] = [
  // 大小写归一(最先执行):不刻意念"大"的字母一律小写(占位保护大/大写标记);
  // 发 LLM 精修的文本同样先过此归一,惯例大小写由模型自动判别
  normalizeSpeechCase,  // 幂:平方/立方/n 次方/任意次方(先转换,后续函数/分数规则才能拿到完整项)
  (s) => s.replace(/的?\s*平方/g, '²'),
  (s) => s.replace(/的?\s*立方/g, '³'),
  (s) => s.replace(/的?\s*([a-zA-Z0-9])\s*次方/g, (_, x: string) => sup(x)),
  // 分数:"a 分之 b" → b/a(嵌套交给 LLM 精修)
  (s) => s.replace(/([a-zA-Z0-9α-ω²³ⁿ′″ˣ]+)\s*分之\s*([a-zA-Z0-9α-ω²³ⁿ′″ˣ]+)/g, '$2/$1'),
  // 根号:"根号 x" → √x;"根号下 …" → √(整体,含空格,到分句边界为止)
  (s) => s.replace(/根号下\s*(.+?)(?=[、。;]|$)/g, '√($1)'),
  (s) => s.replace(/根号/g, '√'),
  (s) => s.replace(/√\s+/g, '√'),
  (s) => s.replace(/∇\s+/g, '∇'),
  // 绝对值 / 模 / 范数
  (s) => s.replace(/([a-zA-Z0-9α-ω])\s*的绝对值/g, '|$1|'),
  (s) => s.replace(/([a-zA-Z0-9α-ω])\s*的模/g, '|$1|'),
  (s) => s.replace(/([a-zA-Z0-9α-ω])\s*的范数/g, '‖$1‖'),
  // 下标:"x 下标 n" → xₙ
  (s) => s.replace(/([a-zA-Z0-9α-ω])\s*下标\s*([a-zA-Z0-9α-ω])/g, (_, a: string, b: string) => a + sub(b)),
  // 括号:"括号 … 括号" → (…)(交替计数)
  (s) => {
    let depth = 0
    return s.replace(/括号/g, () => (depth++ % 2 === 0 ? '(' : ')'))
  },
  // 反函数 / 转置 / 逆:"f 逆 x" → f⁻¹(x);"A 的转置" → Aᵀ;"A 的逆" → A⁻¹
  (s) => s.replace(new RegExp(`(${FN})\\s*逆`, 'g'), '$1⁻¹'),
  (s) => s.replace(/([a-zA-Z])\s*的转置/g, '$1ᵀ'),
  (s) => s.replace(/([a-zA-Z])\s*的逆/g, '$1⁻¹'),
  (s) => s.replace(/([a-zA-Zα-ω]\s*(?:⁻¹|′|″|‴))\s+([a-zA-Zα-ω])(?![a-zA-Zα-ω])/g, '$1($2)'),
  // 高阶导:"f 的 n 阶导"、"y 对 x 的2阶导"(撇系列已在预替换阶段处理)
  (s) => s.replace(/([a-zA-Zα-ω])\s*的\s*n\s*阶导/g, '$1⁽ⁿ⁾(x)'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*对\s*([a-zA-Zα-ω])\s*的\s*([23])\s*阶导/g,
    (_, y: string, x: string, ord: string) => `d${sup(ord)}${y}/d${x}${sup(ord)}`),
  // 偏导(含二阶/混合)
  (s) => s.replace(/([a-zA-Zα-ω])\s*对\s*([a-zA-Zα-ω])\s*的\s*偏导/g, '∂$1/∂$2'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*对\s*([a-zA-Zα-ω])\s*的\s*([23])\s*阶\s*偏导/g,
    (_, f: string, x: string, ord: string) => `∂${sup(ord)}${f}/∂${x}${sup(ord)}`),
  (s) => s.replace(/([a-zA-Zα-ω])\s*先对\s*([a-zA-Zα-ω])\s*再对\s*([a-zA-Zα-ω])\s*的\s*混合偏导/g,
    '∂²$1/∂$2∂$3'),
  // 一阶导:"f x 对 x 求导" / "f 对 x 求导" → f′(x)
  (s) => s.replace(new RegExp(`(${FN})\\s*${'([a-zA-Zα-ω])'}?\\s*对\\s*([a-zA-Zα-ω])\\s*求导`, 'g'),
    (_, f: string, _arg: string | undefined, x: string) => `${f}′(${x})`),
  // 积分:带限 / 不带限(自动补 dx)
  (s) => s.replace(/从\s*([a-zA-Z0-9α-ω])\s*到\s*([a-zA-Z0-9α-ω])\s*[、,]?\s*对\s*([\s\S]+?)\s*积分/g,
    (_, lo: string, hi: string, body: string) =>
      `∫${sub(lo)}${sup(hi)} ${body}${/\sdx$/.test(body) ? '' : ' dx'}`),
  (s) => s.replace(/对\s*([\s\S]+?)\s*积分/g,
    (_, body: string) => `∫ ${body}${/\sdx$/.test(body) ? '' : ' dx'}`),
  // 求和:"求和 i 从一到 n" → ∑ᵢ₌₁ⁿ
  (s) => s.replace(/求和\s*([a-zA-Zα-ω])\s*从\s*([a-zA-Z0-9])\s*到\s*([a-zA-Z0-9α-ω])/g,
    (_, i: string, lo: string, hi: string) => `∑${sub(i)}₌${sub(lo)}${sup(hi)}`),
  // 极限:"极限 x 趋于 a" → limₓ→ₐ
  (s) => s.replace(/极限\s*([a-zA-Zα-ω])\s*→\s*([a-zA-Z0-9α-ω])/g,
    (_, x: string, a: string) => `lim${sub(x)}→${sub(a)}`),
  // 增量:德尔塔 x → Δx(在希腊词典之后,把 δx 纠正为 Δx)
  (s) => s.replace(/δ\s*([a-zA-Z0-9])/g, 'Δ$1'),
  // 期望 / 条件概率 / 正态分布
  (s) => s.replace(/([a-zA-Zα-ω])\s*的期望/g, 'E[$1]'),
  (s) => s.replace(/([a-zA-Z])\s*在\s*([a-zA-Z])\s*发生条件下的概率/g, 'P($1|$2)'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*服从均值为\s*([a-zA-Zα-ω])\s*[、,]\s*方差为\s*([a-zA-Zα-ω])\s*²\s*的正态分布/g,
    (_, X: string, mu: string, sg: string) => `${X}~N(${mu},${sg}²)`),
  // 迹 / 秩 / 内积 / 组合数 / 大 O / 拉普拉斯
  (s) => s.replace(/([a-zA-Z])\s*的迹/g, 'tr($1)'),
  (s) => s.replace(/([a-zA-Z])\s*的秩/g, 'rank($1)'),
  (s) => s.replace(/([a-zA-Z])\s*与\s*([a-zA-Z])\s*的内积/g, '⟨$1,$2⟩'),
  (s) => s.replace(/([a-zA-Z0-9])\s*取\s*([a-zA-Z0-9])/g, 'C($1,$2)'),
  (s) => s.replace(/O\s*([a-zA-Z0-9])\s*方/g, 'O($1²)'),
  (s) => s.replace(/∇²\s*([a-zA-Zα-ω])/g, '∇²$1'),
  // 共轭 / 均值拔 / bar
  (s) => s.replace(/([a-zA-Zα-ω])\s*的共轭/g, '$1̄'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*拔/g, '$1̄'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*bar/g, '$1̄'),
  // 实部 / 虚部
  (s) => s.replace(/([a-zA-Zα-ω])\s*的实部/g, 'Re($1)'),
  (s) => s.replace(/([a-zA-Zα-ω])\s*的虚部/g, 'Im($1)'),
  // 阶乘(词典已给 "阶乘"→"!" 之外再兜一遍:"n 的阶乘" → n!)
  (s) => s.replace(/([a-zA-Z0-9])\s*的\s*!/g, '$1!'),
  // 行列式:"行列式 A" → det(A)
  (s) => s.replace(/det\s+([a-zA-Zα-ω])/g, 'det($1)'),
  // 函数调用:f x → f(x)、φ x → φ(x)(运算词已转换,剩下的"单字母 单字母"即函数式)
  (s) => s.replace(new RegExp(`(${FN})\\s+([a-zA-Zα-ω])(?![a-zA-Zα-ω])`, 'g'), '$1($2)'),
  // 伽马函数(Γ 后跟字母):Γ n → Γ(n)
  (s) => s.replace(/Γ\s+([a-zA-Zα-ω0-9])/g, 'Γ($1)'),
]

/* ---------- 流水线 ---------- */
const CN_NUM_RE = /[零一二两三四五六七八九十百千万]+(?:点[零一二三四五六七八九]+)?/g

export function speechMathConvert(raw: string): string {
  let s = raw.trim()
  for (const [wrong, right] of HOMOPHONES) s = s.split(wrong).join(right)
  s = s.replace(CN_NUM_RE, (m) => cnToArabic(m))
  for (const [k, v] of DICT) s = s.split(k).join(v)
  for (const rule of STRUCT) s = rule(s)
  // 清理:上标前空格、运算符两侧空格、全角标点、多余空白
  return s
    .replace(/ ([²³ⁿ′″‴ˣ⁽⁾⁰¹⁴⁵⁶⁷⁸⁹ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐᵒᵖʳˢᵗᵘᵛʷʸᶻ])/g, '$1')
    .replace(/\s*([+−×÷=≥≤≠≈→⇒⇔∈∉⊆⊂∀∃·⊗⊕])\s*/g, '$1')
    .replace(/[、。]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/* ---------- 转换缓存(LRU;精修结果也入库,重复句式零请求) ---------- */
const CACHE_KEY = 'mg-speechmath-cache'
const CACHE_MAX = 60
type CacheEntry = { text: string; source: 'local' | 'llm' }

function loadCache(): Record<string, CacheEntry> {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (raw) return JSON.parse(raw) as Record<string, CacheEntry>
  } catch {
    /* 损坏即重置 */
  }
  return {}
}

export function cachedConvert(raw: string): CacheEntry | null {
  return loadCache()[raw.trim()] ?? null
}

export function saveConvert(raw: string, text: string, source: 'local' | 'llm'): void {
  try {
    const cache = loadCache()
    cache[raw.trim()] = { text, source }
    const keys = Object.keys(cache)
    if (keys.length > CACHE_MAX) {
      for (const k of keys.slice(0, keys.length - CACHE_MAX)) delete cache[k]
    }
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache))
  } catch {
    /* 配额不足忽略 */
  }
}

/* ---------- 自测集(取自念法贴士,新增规则须在此补用例) ---------- */
export const SELF_TESTS: [string, string][] = [
  ['x 的平方加 y 的平方等于 z 的平方', 'x²+y²=z²'],
  ['从零到一,对 x 平方积分', '∫₀¹ x² dx'],
  ['根号下 x 加一', '√(x+1)'],
  ['根号 x', '√x'],
  ['a 分之 b', 'b/a'],
  ['a 分之 b 加 c 分之 d', 'b/a+d/c'],
  ['f x', 'f(x)'],
  ['斐 x', 'φ(x)'],
  ['大 F x', 'F(x)'],
  ['u t', 'u(t)'],
  ['f 逆 x', 'f⁻¹(x)'],
  ['f 两撇 x', 'f″(x)'],
  ['f 的 n 阶导', 'f⁽ⁿ⁾(x)'],
  ['y 对 x 的二阶导', 'd²y/dx²'],
  ['f 对 x 的偏导', '∂f/∂x'],
  ['f 先对 x 再对 y 的混合偏导', '∂²f/∂x∂y'],
  ['求和 i 从一到 n', '∑ᵢ₌₁ⁿ'],
  ['极限 x 趋于 a', 'limₓ→ₐ'],
  ['梯度 f', '∇f'],
  ['二重积分', '∬'],
  ['x 属于 大 A', 'x∈A'],
  ['对任意 x', '∀x'],
  ['存在 x', '∃x'],
  ['并集 交集', '∪ ∩'],
  ['x 的范数', '‖x‖'],
  ['大 A 的转置', 'Aᵀ'],
  ['大 A 的逆', 'A⁻¹'],
  ['行列式 大 A', 'det(A)'],
  ['x 拔', 'x̄'],
  ['n 的阶乘', 'n!'],
  ['大 A 在 大 B 发生条件下的概率', 'P(A|B)'],
  ['大 X 的期望', 'E[X]'],
  ['伽马函数 n', 'Γ(n)'],
  ['大 O n 方', 'O(n²)'],
  ['拉普拉斯算子 f', '∇²f'],
  ['德尔塔 x', 'Δx'],
  ['空集', '∅'],
  ['子集', '⊆'],
  ['a 与 b 的内积', '⟨a,b⟩'],
  ['a 点乘 b', 'a·b'],
  ['a 叉乘 b', 'a×b'],
  ['大 A 的迹', 'tr(A)'],
  ['大 A 的秩', 'rank(A)'],
  ['大 A 张量积 大 B', 'A⊗B'],
  ['大 A 直和 大 B', 'A⊕B'],
  ['z 的共轭', 'z̄'],
  ['z 的实部', 'Re(z)'],
  ['z 的虚部', 'Im(z)'],
  ['z 的模', '|z|'],
  ['大 X 服从均值为缪、方差为西格玛平方的正态分布', 'X~N(μ,σ²)'],
  ['n 取 k', 'C(n,k)'],
  ['x 的绝对值', '|x|'],
  ['派', 'π'],
  ['三百六十五', '365'],
  ['x 加一点五', 'x+1.5'],
  ['x 的 n 次方', 'xⁿ'],
  ['e 的 x 次方', 'eˣ'],
  ['x 下标 n', 'xₙ'],
  ['屏方', '²'],
  ['a 的转制', 'aᵀ'],
  ['正玄 x', 'sin x'],
  ['鸡分', '积分'],
  ['正太分布', '正态分布'],
  ['X 的平方', 'x²'],
  ['大 x 的平方', 'X²'],
  ['大 F x', 'F(x)'],
  ['你好呀', '你好呀'],
]
