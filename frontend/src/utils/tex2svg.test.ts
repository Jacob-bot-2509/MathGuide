/**
 * LaTeX → SVG 测试。
 *
 * 只跑真实 MathJax(liteAdaptor 在 node 下可用),不 mock:这条链路一旦坏掉,
 * 开场动画会白屏,而回退语义必须是「返回空串」而不是抛错。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { texToSvg } from '@/utils/tex2svg'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('texToSvg', () => {
  it('把公式转成带字形 path 的 SVG(第 2 次复用已建好的文档)', () => {
    const first = texToSvg('x^2 + y^2 = r^2')
    const second = texToSvg('\\frac{1}{2}')
    for (const svg of [first, second]) {
      expect(svg.startsWith('<svg')).toBe(true)
      expect(svg).toContain('<path')
    }
  })

  it('display=false 时输出行内样式 SVG', () => {
    const inline = texToSvg('a+b', false)
    expect(inline.startsWith('<svg')).toBe(true)
    expect(inline).toContain('width=')
  })

  it('display 与 inline 的尺寸不同(块级公式更大)', () => {
    const display = texToSvg('\\int_0^1 f(x)\\,dx')
    const inline = texToSvg('\\int_0^1 f(x)\\,dx', false)
    expect(display).not.toBe(inline)
  })

  it('转换失败时返回空串并记一条错误日志(不抛给调用方)', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    // 非字符串输入会让 MathJax 内部抛错,走 catch 分支
    const result = texToSvg(null as unknown as string)
    expect(result).toBe('')
    expect(error).toHaveBeenCalled()
    expect(String(error.mock.calls[0][0])).toContain('LaTeX')
  })

  it('失败之后仍能继续正常转换(缓存文档未被污染)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(texToSvg(undefined as unknown as string)).toBe('')
    expect(texToSvg('x').startsWith('<svg')).toBe(true)
  })

  it('未知命令不抛错(返回 SVG 或空串都算可用)', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const out = texToSvg('\\notacommand{1}')
    expect(typeof out).toBe('string')
  })
})
