/**
 * 分栏比例换算(vitest):固定「像素下限 → 比例」的边界。
 *
 * 三个真实故障驱动了这些断言:
 *   1. 容器还没量到宽度时若也按像素夹,存下来的 0.68 会被悄悄改成 0.6;
 *   2. 宽度刚好等于两栏最小宽度之和(700px)是临界点,必须两栏都保底;
 *   3. localStorage 里的脏值(NaN / 0 / 负数)不能让分栏变成 0 宽。
 */
import { describe, expect, it } from 'vitest'
import {
  CHAT_MIN_PX,
  SPLIT_DEFAULT,
  SEARCH_MIN_PX,
  clampSplitRatio,
  parseStoredRatio,
} from '@/utils/splitPane'

describe('clampSplitRatio', () => {
  it('宽度未知时只做 0..1 兜底,不动用户存过的比例', () => {
    expect(clampSplitRatio(0.68, 0)).toBe(0.68)
    expect(clampSplitRatio(0.68, Number.NaN)).toBe(0.68)
    expect(clampSplitRatio(1.7, 0)).toBe(1)
    expect(clampSplitRatio(-0.5, 0)).toBe(0)
  })

  it('比例本身是脏值时回退默认值', () => {
    expect(clampSplitRatio(Number.NaN, 1200)).toBe(SPLIT_DEFAULT)
    expect(clampSplitRatio(Number.POSITIVE_INFINITY, 1200)).toBe(SPLIT_DEFAULT)
  })

  it('宽度刚好等于两栏最小值之和时,两栏都保底', () => {
    const width = SEARCH_MIN_PX + CHAT_MIN_PX
    // 此时上下界重合:任何输入都收敛到同一点
    expect(clampSplitRatio(0.1, width)).toBeCloseTo(SEARCH_MIN_PX / width, 10)
    expect(clampSplitRatio(0.9, width)).toBeCloseTo(1 - CHAT_MIN_PX / width, 10)
  })

  it('空间不足并排时收在 0.4~0.6', () => {
    expect(clampSplitRatio(0.9, 500)).toBe(0.6)
    expect(clampSplitRatio(0.1, 500)).toBe(0.4)
    expect(clampSplitRatio(0.5, 500)).toBe(0.5)
  })

  it('宽屏下按两栏最小宽度夹取', () => {
    // 1600px:左栏至少 320(0.2),聊天区至少 380(右栏最多 1220/1600)
    expect(clampSplitRatio(0.1, 1600)).toBeCloseTo(0.2, 10)
    expect(clampSplitRatio(0.9, 1600)).toBeCloseTo(1220 / 1600, 10)
    expect(clampSplitRatio(0.5, 1600)).toBe(0.5)
  })
})

describe('parseStoredRatio', () => {
  it('空值与脏值回退默认', () => {
    expect(parseStoredRatio(null, SPLIT_DEFAULT)).toBe(SPLIT_DEFAULT)
    expect(parseStoredRatio('', SPLIT_DEFAULT)).toBe(SPLIT_DEFAULT)
    expect(parseStoredRatio('0', SPLIT_DEFAULT)).toBe(SPLIT_DEFAULT)
    expect(parseStoredRatio('-0.3', SPLIT_DEFAULT)).toBe(SPLIT_DEFAULT)
    expect(parseStoredRatio('abc', SPLIT_DEFAULT)).toBe(SPLIT_DEFAULT)
  })

  it('正常数值原样取出(夹取交给 clampSplitRatio)', () => {
    expect(parseStoredRatio('0.68', SPLIT_DEFAULT)).toBe(0.68)
    expect(parseStoredRatio('1', SPLIT_DEFAULT)).toBe(1)
  })
})
