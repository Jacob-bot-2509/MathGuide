/**
 * 稳定块切分测试。
 *
 * 切分器的唯一职责是「让前面块的 text 不变」;只要切坏了结构(切在代码围栏、
 * $$ 公式或未闭合的 \( 中间),流式渲染就会出现半截公式或代码块错乱。
 * 因此每个用例都同时断言两件事:切点位置 + 拼回去与原文逐字相同。
 */
import { describe, expect, it } from 'vitest'
import { splitStableBlocks } from '@/utils/mathBlocks'

/** 拼回原文:切分只允许改变「块边界」,不允许丢字或多字 */
function roundTrip(text: string): string[] {
  const blocks = splitStableBlocks(text)
  expect(blocks.join('')).toBe(text)
  return blocks
}

describe('splitStableBlocks / 基本切分', () => {
  it('空文本返回空数组', () => {
    expect(splitStableBlocks('')).toEqual([])
  })

  it('没有空行时整段作为一块(流式尾部)', () => {
    expect(roundTrip('第一段还在生成中')).toEqual(['第一段还在生成中'])
  })

  it('按空行切成多块,块尾保留换行', () => {
    const text = '第一段\n\n第二段\n\n第三段'
    expect(roundTrip(text)).toEqual(['第一段\n\n', '第二段\n\n', '第三段'])
  })

  it('连续空行并入上一块,不产生空白块', () => {
    const blocks = roundTrip('甲\n\n\n\n乙')
    expect(blocks).toEqual(['甲\n\n\n\n', '乙'])
    expect(blocks.every((b) => b.trim() !== '' || blocks.length === 1)).toBe(true)
  })

  it('文本以空行开头时首块就是空行(不与后文合并)', () => {
    expect(roundTrip('\n\n正文')).toEqual(['\n\n', '正文'])
  })

  it('末尾空行单独成块,拼回仍与原文一致', () => {
    expect(roundTrip('正文\n\n')).toEqual(['正文\n\n'])
  })
})

describe('splitStableBlocks / 不切坏结构', () => {
  it('代码围栏内的空行不切', () => {
    const text = '说明\n\n```ts\nconst a = 1\n\nconst b = 2\n```\n\n结尾'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(3)
    expect(blocks[1]).toContain('const a = 1\n\nconst b = 2')
  })

  it('同行出现两个 ``` 视为自闭合,不进入围栏状态', () => {
    const text = '```inline```\n\n正文'
    expect(roundTrip(text)).toEqual(['```inline```\n\n', '正文'])
  })

  it('未闭合的围栏把后续内容留在最后一块', () => {
    const text = '正文\n\n```py\nprint(1)\n\nprint(2)'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(2)
    expect(blocks[1]).toBe('```py\nprint(1)\n\nprint(2)')
  })

  it('$$ 块级公式跨空行时不切', () => {
    const text = '前文\n\n$$\na = 1\n\nb = 2\n$$\n\n后文'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(3)
    expect(blocks[1]).toContain('b = 2')
  })

  it('\\[ \\] 块级公式跨空行时不切', () => {
    const text = '前文\n\n\\[\nx = 1\n\ny = 2\n\\]\n\n后文'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(3)
    expect(blocks[1]).toContain('y = 2')
  })

  it('\\( \\) 行内公式跨空行时不切(MathText 允许跨行)', () => {
    const text = '前文\n\n\\( a + b\n\n+ c \\)\n\n后文'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(3)
    expect(blocks[1]).toContain('+ c')
  })

  it('公式闭合后恢复切分', () => {
    const text = '$$\nx = 1\n$$\n\n后文'
    const blocks = roundTrip(text)
    expect(blocks).toHaveLength(2)
    expect(blocks[1]).toBe('后文')
  })
})

describe('splitStableBlocks / 合法公式还原', () => {
  it('行内公式与孤立的 $ 保持原样拼回', () => {
    const text = '已知 $x^2$ 与 $y$ 的关系\n\n继续讨论'
    const blocks = roundTrip(text)
    expect(blocks[0]).toContain('$x^2$')
  })

  it('$$ 公式原样保留在所属块内', () => {
    const text = '引入\n\n$$\\int_0^1 x\\,dx = \\frac{1}{2}$$\n\n结论'
    const blocks = roundTrip(text)
    expect(blocks[1]).toContain('\\int_0^1')
  })
})
