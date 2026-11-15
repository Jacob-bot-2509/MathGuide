/**
 * speechMath:口语数学 → 符号的本地编译器 + 转换缓存。
 *
 * 为什么值得测:这是“说一句话就出公式”的主链路,错了用户立刻看得见 ——
 * 少一个空格是小事,把“x 的平方”编译成“x²+...”丢项就废了整句。
 * 缓存部分同样要测:缓存里是用户原话,必须能清、不能越攒越多、
 * 存储损坏时还得能自愈。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  BEAUTY_TESTS,
  SELF_TESTS,
  beautifyMath,
  cachedConvert,
  clearConvertCache,
  normalizeSpeechCase,
  saveConvert,
  speechMathConvert,
} from '@/utils/speechMath'

describe('normalizeSpeechCase:大小写归一', () => {
  it('显式念“大写/大”的字母保留大写', () => {
    expect(normalizeSpeechCase('大写 A 的转置')).toBe('A 的转置')
    expect(normalizeSpeechCase('大 A 的逆')).toBe('A 的逆')
  })

  it('没念“大”的 ASCII 字母一律小写(语音识别大小写不可信)', () => {
    expect(normalizeSpeechCase('X 的平方')).toBe('x 的平方')
    expect(normalizeSpeechCase('ABCD')).toBe('abcd')
  })

  it('希腊字母不跟着变小写(Γ/Ω 有自己的含义)', () => {
    expect(normalizeSpeechCase('Γ Ω')).toBe('Γ Ω')
  })

  it('多个大写标记各自还原,不会串位', () => {
    expect(normalizeSpeechCase('大写 A 与 大写 B')).toBe('A 与 B')
  })

  it('“大”后面还跟着字母时不当大写标记(是普通词)', () => {
    expect(normalizeSpeechCase('大xY')).toBe('大xy')
  })
})

describe('speechMathConvert:官方自测集(念法贴士逐条)', () => {
  it.each(SELF_TESTS)('「%s」→「%s」', (spoken, expected) => {
    expect(speechMathConvert(spoken)).toBe(expected)
  })
})

describe('speechMathConvert:边界与清理', () => {
  it('空串和纯空白返回空串', () => {
    expect(speechMathConvert('')).toBe('')
    expect(speechMathConvert('   ')).toBe('')
  })

  it('没有数学词的口语原样返回(不硬翻译)', () => {
    expect(speechMathConvert('你好呀')).toBe('你好呀')
    expect(speechMathConvert('为什么是这样')).toBe('为什么是这样')
  })

  it('运算符两侧空格被收紧(读起来才连贯)', () => {
    expect(speechMathConvert('a  等于   b')).toBe('a=b')
  })

  it('句号/顿号当成断句空格,不留在公式里', () => {
    expect(speechMathConvert('先算 x 的平方。再算 y')).toBe('先算 x² 再算 y')
  })

  it('多余空白压缩成一个空格', () => {
    expect(speechMathConvert('x   加    y')).toBe('x+y')
  })

  it('中文数字归一(含小数与百千万)', () => {
    expect(speechMathConvert('三百六十五')).toBe('365')
    expect(speechMathConvert('x 加一点五')).toBe('x+1.5')
    expect(speechMathConvert('十二万')).toBe('120000')
  })

  it('结果里不留全角括号与中文数字', () => {
    const out = speechMathConvert('括号 x 加一 括号 的平方')
    expect(out).not.toMatch(/[零一二三四五六七八九十百千万]/)
    expect(out).toContain('(')
  })
})

describe('beautifyMath:模型精修输出的减法', () => {
  it.each(BEAUTY_TESTS)('「%s」→「%s」', (latex, expected) => {
    expect(beautifyMath(latex)).toBe(expected)
  })

  it('没有 Unicode 上标形式的字母回退成 ^X(不丢信息)', () => {
    expect(beautifyMath('A^{Q}')).toBe('A^Q')
  })

  it('没有 Unicode 下标形式的字母回退成 _x', () => {
    expect(beautifyMath('A_{b}')).toBe('A_b')
  })

  it('\\sum 下限不是 i=1 形式时直接给下标', () => {
    expect(beautifyMath('\\sum_{i}^{n}')).toBe('∑ᵢⁿ')
  })

  it('去掉 $ 定界符(输入框不渲染 KaTeX)', () => {
    expect(beautifyMath('$a+b$')).toBe('a+b')
  })

  it('常见 LaTeX 命令换成 Unicode 符号', () => {
    expect(beautifyMath('a\\to b \\cdot c \\leq d \\geq e \\approx f'))
      .toBe('a→b·c≤d≥e≈f')
    expect(beautifyMath('\\nabla f')).toBe('∇ f')
    expect(beautifyMath('\\infty \\pi')).toBe('∞ π')
    expect(beautifyMath('\\partial \\prime \\neq')).toBe('∂ ′≠')
    expect(beautifyMath('\\sqrt{2}')).toBe('√(2)')
    expect(beautifyMath('\\int_a^b \\sum')).toBe('∫ₐᵇ ∑')
  })

  it('空串安全返回空串', () => {
    expect(beautifyMath('')).toBe('')
  })
})

class MemoryStorage {
  private store = new Map<string, string>()

  failWrite = false

  getItem(key: string): string | null {
    return this.store.has(key) ? this.store.get(key)! : null
  }

  setItem(key: string, value: string): void {
    if (this.failWrite) throw new Error('QuotaExceededError')
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  keys(): string[] {
    return [...this.store.keys()]
  }
}

describe('转换缓存:读写、淘汰与自愈', () => {
  let storage: MemoryStorage

  beforeEach(() => {
    storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('没缓存过时返回 null', () => {
    expect(cachedConvert('x 的平方')).toBeNull()
  })

  it('存进去能立刻读出来,并带上来源(本地/模型)', () => {
    saveConvert('x 的平方', 'x²', 'local')
    expect(cachedConvert('x 的平方')).toEqual({ text: 'x²', source: 'local' })
    saveConvert('x 的平方', 'x^2', 'llm')
    expect(cachedConvert('x 的平方')).toEqual({ text: 'x^2', source: 'llm' })
  })

  it('读写都先 trim(多一个空格不该多一次请求)', () => {
    saveConvert('  e 的 x 次方  ', 'eˣ', 'local')
    expect(cachedConvert('e 的 x 次方')).toEqual({ text: 'eˣ', source: 'local' })
    expect(cachedConvert('   e 的 x 次方')).not.toBeNull()
  })

  it('超过 60 条时淘汰最旧的,存储不会无限膨胀', () => {
    for (let i = 0; i < 62; i += 1) saveConvert(`句子${i}`, `公式${i}`, 'local')
    const keys = storage.keys()
    expect(keys).toHaveLength(1)
    const stored = JSON.parse(storage.getItem(keys[0])!) as Record<string, unknown>
    expect(Object.keys(stored)).toHaveLength(60)
    expect(stored['句子0']).toBeUndefined()
    expect(stored['句子61']).toBeDefined()
  })

  it('存储里是坏 JSON 时当作空缓存(不抛错、不影响转写)', () => {
    storage.setItem('mg-speechmath-cache', '{not json')
    expect(cachedConvert('任意')).toBeNull()
    saveConvert('新句子', '新公式', 'local')
    expect(cachedConvert('新句子')?.text).toBe('新公式')
  })

  it('写入配额不足时静默失败,不影响调用方', () => {
    storage.failWrite = true
    expect(() => saveConvert('x', 'y', 'local')).not.toThrow()
    expect(cachedConvert('x')).toBeNull()
  })

  it('clearConvertCache 抹掉整份缓存(隐私页一键清除)', () => {
    saveConvert('x 的平方', 'x²', 'local')
    clearConvertCache()
    expect(cachedConvert('x 的平方')).toBeNull()
  })

  it('没有 localStorage 时(隐私模式/单测环境)读写都不抛错', () => {
    vi.unstubAllGlobals()
    expect(cachedConvert('x')).toBeNull()
    expect(() => saveConvert('x', 'y', 'local')).not.toThrow()
    expect(() => clearConvertCache()).not.toThrow()
  })
})
