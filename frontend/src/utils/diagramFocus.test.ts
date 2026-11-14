/**
 * 图解放大几何(vitest):分栏比例、浮层夹取、手势阈值。
 *
 * 这些函数原本只被组件间接调用、没有任何断言,却决定「拖到边缘会不会跑出屏幕」
 * 「双指放大到多大变全屏」「全屏后还能不能拖」—— 重构组件前先钉住行为。
 */
import { describe, expect, it } from 'vitest'
import {
  DIAGRAM_MIN,
  DIAGRAM_SPLIT_DEFAULT,
  FOCUS_FULL_H,
  FOCUS_FULL_W,
  FOCUS_MIN_H,
  FOCUS_MIN_W,
  clampDiagramSplit,
  clampFocusPanel,
  isDoubleTap,
  moveFocusPanel,
  resizeFocusPanel,
  tapMoved,
  type FocusPanel,
} from '@/utils/diagramFocus'

const HIDDEN = { fullscreen: false } as const
const VIEW = { width: 1000, height: 800 }

function panel(over: Partial<FocusPanel> = {}): FocusPanel {
  return { x: 0, w: 90, h: 82, ...HIDDEN, ...over }
}

describe('clampDiagramSplit', () => {
  it('比例是脏值时回退默认值', () => {
    expect(clampDiagramSplit(Number.NaN, 1600)).toBe(DIAGRAM_SPLIT_DEFAULT)
  })

  it('宽度未知时只做 0..1 兜底', () => {
    expect(clampDiagramSplit(0.7, 0)).toBe(0.7)
    expect(clampDiagramSplit(1.4, 0)).toBe(1)
    expect(clampDiagramSplit(0.7, Number.NaN)).toBe(0.7)
  })

  it('窗口放不下两栏时收在 0.55~0.7', () => {
    // 360(对话) + 420(图解) = 780 是并排下限
    expect(clampDiagramSplit(0.5, 700)).toBe(0.55)
    expect(clampDiagramSplit(0.9, 700)).toBe(0.7)
    expect(clampDiagramSplit(0.62, 700)).toBe(0.62)
  })

  it('刚好达到并排下限时边界重合', () => {
    const width = 360 + DIAGRAM_MIN
    expect(clampDiagramSplit(0.1, width)).toBeCloseTo(DIAGRAM_MIN / width, 10)
    expect(clampDiagramSplit(0.9, width)).toBeCloseTo(1 - 360 / width, 10)
  })

  it('宽屏下保留图解最小宽度与对话最小宽度', () => {
    expect(clampDiagramSplit(0.1, 1600)).toBeCloseTo(420 / 1600, 10)
    expect(clampDiagramSplit(0.9, 1600)).toBeCloseTo(1240 / 1600, 10)
    expect(clampDiagramSplit(0.62, 1600)).toBe(0.62)
  })
})

describe('clampFocusPanel', () => {
  it('已全屏或尺寸过阈值直接吸附全屏', () => {
    const full = { x: 0, w: 100, h: 100, fullscreen: true }
    expect(clampFocusPanel(full, VIEW)).toEqual(full)
    expect(clampFocusPanel(panel({ w: FOCUS_FULL_W }), VIEW).fullscreen).toBe(true)
    expect(clampFocusPanel(panel({ h: FOCUS_FULL_H }), VIEW).fullscreen).toBe(true)
  })

  it('尺寸低于下限时放大到最小可用尺寸', () => {
    const result = clampFocusPanel(panel({ w: 10, h: 10 }), VIEW)
    expect(result.w).toBe(FOCUS_MIN_W)
    expect(result.h).toBe(FOCUS_MIN_H)
    expect(result.fullscreen).toBe(false)
  })

  it('水平位置夹在「不出屏」范围内', () => {
    // w=90 → 每侧最多 (100-90)*1000/200 = 50px
    expect(clampFocusPanel(panel({ x: 1000 }), VIEW).x).toBe(50)
    expect(clampFocusPanel(panel({ x: -1000 }), VIEW).x).toBe(-50)
    expect(clampFocusPanel(panel({ x: 20 }), VIEW).x).toBe(20)
  })
})

describe('moveFocusPanel', () => {
  it('全屏后不再移动(返回同一对象)', () => {
    const full = { x: 0, w: 100, h: 100, fullscreen: true }
    expect(moveFocusPanel(full, 120, VIEW)).toBe(full)
  })

  it('位移后立即夹回可视范围', () => {
    expect(moveFocusPanel(panel(), 10, VIEW).x).toBe(10)
    expect(moveFocusPanel(panel(), 500, VIEW).x).toBe(50)
    expect(moveFocusPanel(panel(), -500, VIEW).x).toBe(-50)
  })
})

describe('resizeFocusPanel', () => {
  it('全屏后不能缩回(返回同一对象)', () => {
    const full = { x: 0, w: 100, h: 100, fullscreen: true }
    expect(resizeFocusPanel(full, 0.5, VIEW)).toBe(full)
  })

  it('缩放系数非法时只做夹取,不改尺寸', () => {
    const start = panel()
    expect(resizeFocusPanel(start, 0, VIEW)).toEqual(clampFocusPanel(start, VIEW))
    expect(resizeFocusPanel(start, -1, VIEW)).toEqual(clampFocusPanel(start, VIEW))
    expect(resizeFocusPanel(start, Number.NaN, VIEW)).toEqual(clampFocusPanel(start, VIEW))
  })

  it('放大越过阈值即吸附全屏,没越过则按比例变大', () => {
    expect(resizeFocusPanel(panel(), 1.5, VIEW).fullscreen).toBe(true)
    const bigger = resizeFocusPanel(panel({ w: 80, h: 70 }), 1.1, VIEW)
    expect(bigger.w).toBeCloseTo(88, 6)
    expect(bigger.h).toBeCloseTo(77, 6)
    expect(bigger.fullscreen).toBe(false)
  })
})

describe('tapMoved', () => {
  it('阈值是 8px,严格大于才算拖动', () => {
    expect(tapMoved({ x: 0, y: 0 }, { x: 8, y: 0 })).toBe(false)
    expect(tapMoved({ x: 0, y: 0 }, { x: 0, y: 8 })).toBe(false)
    expect(tapMoved({ x: 0, y: 0 }, { x: 9, y: 0 })).toBe(true)
  })

  it('斜向位移按直线距离计算(不是取较大分量)', () => {
    expect(tapMoved({ x: 0, y: 0 }, { x: 6, y: 6 })).toBe(true)
    // 5,5 → 11,11 = 8.49px,刚过阈值
    expect(tapMoved({ x: 5, y: 5 }, { x: 11, y: 11 })).toBe(true)
    // 5,5 → 10,10 = 7.07px,只看分量会误判成拖动
    expect(tapMoved({ x: 5, y: 5 }, { x: 10, y: 10 })).toBe(false)
  })
})

describe('isDoubleTap', () => {
  const first = { time: 1000, x: 0, y: 0 }

  it('第一次点击永远不算双击', () => {
    expect(isDoubleTap(null, first)).toBe(false)
  })

  it('时间间隔超过 300ms 不算双击(含时间倒流)', () => {
    expect(isDoubleTap(first, { time: 1300, x: 0, y: 0 })).toBe(true)
    expect(isDoubleTap(first, { time: 1301, x: 0, y: 0 })).toBe(false)
    expect(isDoubleTap(first, { time: 999, x: 0, y: 0 })).toBe(false)
  })

  it('位移超过 10px 不算双击', () => {
    expect(isDoubleTap(first, { time: 1100, x: 10, y: 0 })).toBe(true)
    expect(isDoubleTap(first, { time: 1100, x: 11, y: 0 })).toBe(false)
    expect(isDoubleTap(first, { time: 1100, x: 8, y: 8 })).toBe(false)
  })

  it('阈值可覆盖(触控板/无障碍场景)', () => {
    const next = { time: 2000, x: 0, y: 0 }
    expect(isDoubleTap(first, next)).toBe(false)
    expect(isDoubleTap(first, next, 1200)).toBe(true)
  })
})
