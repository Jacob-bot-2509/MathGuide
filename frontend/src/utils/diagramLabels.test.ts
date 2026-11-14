/**
 * diagramLabels:图解里的纯几何排版(量字、找位、避让)。
 *
 * 为什么值得测:这里没有 DOM,全靠字宽估算 + 打分函数决定文字落点。
 * 打分权重一旦被打错,后果是标签压在图线上、文字被推出画布、
 * 或者一堆标签叠成一坨。所以既测“算得对”,也测“挤得开”。
 */
import { describe, expect, it } from 'vitest'
import {
  charWidth,
  figureRectOfShapes,
  measureLabel,
  measureTextWidth,
  outwardSides,
  overlapArea,
  plainLabel,
  placeLabels,
  placeScreenLabels,
  pointRectDistance,
  screenCandidates,
  shapeObstacleRects,
  type LabelRequest,
  type Rect,
  type ScreenLabelRequest,
} from '@/utils/diagramLabels'

const bounds: Rect = { x: 0, y: 0, w: 400, h: 300 }

describe('plainLabel:LaTeX 降级成可读文本', () => {
  it('去掉数学定界符 $ 并还原希腊字母', () => {
    expect(plainLabel('$\\lambda$ 存在,$\\alpha$ 不在白名单里'))
      .toBe('λ 存在,\\alpha 不在白名单里')
    expect(plainLabel('\\pi r^2')).toBe('π r²')
    expect(plainLabel('\\theta \\sigma \\mu \\Delta')).toBe('θ σ μ Δ')
    expect(plainLabel('\\nabla f')).toBe('∇ f')
  })

  it('运算符与关系符还原', () => {
    expect(plainLabel('a \\pm b \\mp c')).toBe('a ± b ∓ c')
    expect(plainLabel('a \\times b \\cdot c')).toBe('a × b · c')
    expect(plainLabel('\\sqrt{x}')).toBe('√{x}')
    expect(plainLabel('\\infty')).toBe('∞')
    expect(plainLabel('x \\in A \\subset B')).toBe('x ∈ A ⊂ B')
    expect(plainLabel('A \\to B \\mapsto C')).toBe('A → B ↦ C')
  })

  it('\\left \\right 这类纯排版命令直接删除', () => {
    expect(plainLabel('\\left( x \\right)')).toBe('( x )')
  })

  it('转置与 dagger 保留成上标符号', () => {
    expect(plainLabel('A^\\top')).toBe('Aᵀ')
    expect(plainLabel('A^T')).toBe('Aᵀ')
    expect(plainLabel('A^\\dagger')).toBe('A†')
  })

  it('下标数字/ijknm 转成 Unicode 下标,其他字符原样保留', () => {
    expect(plainLabel('x_0 x_9')).toBe('x₀ x₉')
    expect(plainLabel('a_i a_j a_k a_n a_m')).toBe('aᵢ aⱼ aₖ aₙ aₘ')
    expect(plainLabel('x_y')).toBe('x_y')
  })

  it('上标 2/3 与省略号被清理(SVG 里没有上下标排版)', () => {
    expect(plainLabel('x^2 + y^3')).toBe('x² + y³')
    expect(plainLabel('等等…')).toBe('等等')
    expect(plainLabel('等等...')).toBe('等等')
  })

  it('null/undefined/数字都安全转成字符串', () => {
    expect(plainLabel(null)).toBe('')
    expect(plainLabel(undefined)).toBe('')
    expect(plainLabel(42)).toBe('42')
    expect(plainLabel('  A  ')).toBe('A')
  })
})

describe('charWidth / measureTextWidth:字宽估算', () => {
  it('中文按一个字号宽,空格与标点更窄,运算符居中', () => {
    expect(charWidth('中', 10)).toBe(10)
    expect(charWidth(' ', 10)).toBeCloseTo(3.4)
    expect(charWidth(',', 10)).toBeCloseTo(3.2)
    expect(charWidth('(', 10)).toBeCloseTo(4.8)
    expect(charWidth('a', 10)).toBeCloseTo(6)
  })

  it('整串宽度是逐字累加(不是字数 × 平均宽)', () => {
    const mixed = 'a中 '
    const expected = charWidth('a', 12) + charWidth('中', 12) + charWidth(' ', 12)
    expect(measureTextWidth(mixed, 12)).toBeCloseTo(expected)
    expect(measureTextWidth('', 12)).toBe(0)
  })
})

describe('measureLabel:折行与截断', () => {
  const request = (over: Partial<LabelRequest>): LabelRequest => ({
    id: 'a', text: '示例', anchorX: 0, anchorY: 0, ...over,
  })

  it('短文本单行,宽度带 4px 内边距、高度带 2px', () => {
    const label = measureLabel(request({ text: '顶点', fontSize: 10 }))
    expect(label.lines).toEqual(['顶点'])
    expect(label.fontSize).toBe(10)
    expect(label.lineHeight).toBe(13)
    expect(label.w).toBeCloseTo(20 + 4)
    expect(label.h).toBe(13 + 2)
  })

  it('字号下限 8,避免小到看不清', () => {
    expect(measureLabel(request({ fontSize: 2 })).fontSize).toBe(8)
  })

  it('超宽文本按 maxWidth 折行', () => {
    const label = measureLabel(request({ text: '一二三四五六七八', maxWidth: 20 }))
    expect(label.lines.length).toBeGreaterThan(1)
    expect(label.lines.every((line) => measureTextWidth(line, 10) <= 20)).toBe(true)
  })

  it('超过 maxLines 时非标注省略号收尾,标注不加省略号(允许完整文字溢出)', () => {
    const long = '一二三四五六七八九十一二三四五六七八九十'
    const shape = measureLabel(request({ text: long, maxWidth: 20, maxLines: 2 }))
    expect(shape.lines).toHaveLength(2)
    expect(shape.lines[1].endsWith('…')).toBe(true)
    const annotation = measureLabel(request({
      text: long, maxWidth: 20, maxLines: 2, role: 'annotation',
    }))
    expect(annotation.lines).toHaveLength(2)
    expect(annotation.lines[1].endsWith('…')).toBe(false)
  })

  it('空文本也返回一行空串,调用方不必判空', () => {
    const label = measureLabel(request({ text: '   ' }))
    expect(label.lines).toEqual([''])
    expect(label.h).toBe(2 + Math.round(10 * 1.28))
  })
})

describe('overlapArea / pointRectDistance:基础几何', () => {
  it('相交矩形返回真实重叠面积', () => {
    expect(overlapArea({ x: 0, y: 0, w: 10, h: 10 }, { x: 5, y: 5, w: 10, h: 10 }))
      .toBe(25)
  })

  it('相离或仅相切时重叠为 0(不会出现负数)', () => {
    expect(overlapArea({ x: 0, y: 0, w: 10, h: 10 }, { x: 20, y: 20, w: 5, h: 5 }))
      .toBe(0)
    expect(overlapArea({ x: 0, y: 0, w: 10, h: 10 }, { x: 10, y: 0, w: 10, h: 10 }))
      .toBe(0)
  })

  it('点在矩形内距离为 0,在外按最近边算欧氏距离', () => {
    const rect = { x: 0, y: 0, w: 10, h: 10 }
    expect(pointRectDistance(rect, 5, 5)).toBe(0)
    expect(pointRectDistance(rect, 13, 14)).toBe(5)
  })
})

const label = (over: Partial<LabelRequest>): LabelRequest => ({
  id: 'a', text: '标签', anchorX: 200, anchorY: 150, ...over,
})

const inside = (rect: Rect, area: Rect): boolean =>
  rect.x >= area.x - 1e-6 && rect.y >= area.y - 1e-6
  && rect.x + rect.w <= area.x + area.w + 1e-6
  && rect.y + rect.h <= area.y + area.h + 1e-6

describe('placeLabels:落点选择', () => {
  it('空输入返回空数组(没有标签就没有排布)', () => {
    expect(placeLabels([], [], bounds)).toEqual([])
  })

  it('单个标签落在锚点附近且完全在画布内', () => {
    const [placed] = placeLabels([label({ id: 'a' })], [], bounds)
    expect(inside(placed, bounds)).toBe(true)
    expect(placed.side).toBe('top')
    expect(placed.leader).toBe(true)
    expect(placed.lines).toEqual(['标签'])
  })

  it('夹在左上角的锚点不会把文字顶出画布', () => {
    const [placed] = placeLabels([label({ anchorX: 0, anchorY: 0 })], [], bounds)
    expect(inside(placed, bounds)).toBe(true)
    expect(placed.x).toBeGreaterThanOrEqual(0)
    expect(placed.y).toBeGreaterThanOrEqual(0)
  })

  it('右下角同理(边界夹取另一侧)', () => {
    const [placed] = placeLabels([label({ anchorX: 400, anchorY: 300 })], [], bounds)
    expect(inside(placed, bounds)).toBe(true)
  })

  it('fixed 标签不移动,居中在锚点上且不画引线', () => {
    const [placed] = placeLabels([
      label({ anchorX: 50, anchorY: 40, fixed: true, role: 'axis' }),
    ], [], bounds)
    expect(placed.side).toBe('center')
    expect(placed.leader).toBe(false)
    expect(placed.x + placed.w / 2).toBeCloseTo(50)
    expect(placed.y + placed.h / 2).toBeCloseTo(40)
    expect(placed.role).toBe('axis')
  })

  it('同锚点的第二个标签换边,不与第一个重叠', () => {
    const placed = placeLabels([label({ id: 'a' }), label({ id: 'b' })], [], bounds)
    const [first, second] = placed
    expect(overlapArea(first, second)).toBe(0)
    expect(first.side).not.toBe(second.side)
  })

  it('优先级高的先挑位置(同锚点时它拿到首选侧)', () => {
    const placed = placeLabels([
      label({ id: 'low', priority: 1 }),
      label({ id: 'high', priority: 9 }),
    ], [], bounds)
    expect(placed.map((item) => item.id)).toEqual(['low', 'high'])
    expect(placed[1].side).toBe('top')
  })

  it('大块障碍物(多边形/填充)会挤开标签', () => {
    const obstacle: Rect = { x: 180, y: 130, w: 60, h: 60 }
    const [placed] = placeLabels([label({})], [obstacle], bounds)
    expect(overlapArea(placed, obstacle)).toBe(0)
  })

  it('曲线采样出的小方块不参与候选生成,但仍在打分里被躲开', () => {
    const tiny: Rect = { x: 198, y: 148, w: 4, h: 4 }
    const [placed] = placeLabels([label({})], [tiny], bounds)
    expect(overlapArea(placed, tiny)).toBe(0)
  })

  it('给 figure 时标签优先排到主体外面', () => {
    const figure: Rect = { x: 150, y: 100, w: 100, h: 100 }
    const [placed] = placeLabels(
      [label({ anchorX: 200, anchorY: 150, figure, figureWeight: 200 })],
      [],
      bounds,
    )
    expect(overlapArea(placed, figure)).toBe(0)
  })

  it('figureWeight 为 0 时不关心压住主体(轴名这类装饰标签)', () => {
    const figure: Rect = { x: 150, y: 100, w: 100, h: 100 }
    const [placed] = placeLabels(
      [label({ anchorX: 200, anchorY: 150, figure, figureWeight: 0 })],
      [],
      bounds,
    )
    // 没有惩罚项时,最近的候选就在锚点边上 —— 允许压在主体上
    expect(placed.side).toBe('top')
  })

  it('preferred 指定的方向会被优先采用', () => {
    const [placed] = placeLabels(
      [label({ preferred: ['right', 'top'] })], [], bounds,
    )
    expect(placed.side).toBe('right')
  })

  it('preferred 只列一个方向时其他方向都排在后面', () => {
    const [placed] = placeLabels([label({ preferred: ['bottom'] })], [], bounds)
    expect(placed.side).toBe('bottom')
  })

  it('返回顺序与入参一致,不因内部排序而串位', () => {
    const requests = [
      label({ id: 'z', priority: 1 }),
      label({ id: 'a', priority: 5, anchorX: 60, anchorY: 60 }),
    ]
    expect(placeLabels(requests, [], bounds).map((item) => item.id)).toEqual(['z', 'a'])
  })
})


describe('placeScreenLabels:屏幕坐标版', () => {
  const screen = (over: Partial<ScreenLabelRequest>): ScreenLabelRequest => ({
    id: 's', anchorX: 200, anchorY: 150, width: 40, height: 16, ...over,
  })

  it('候选数量随 gap 数线性增长;给了避让矩形会补一整套贴边候选', () => {
    expect(screenCandidates(screen({}), [6, 12])).toHaveLength(16)
    const withAvoid = screenCandidates(
      screen({ avoidRect: { x: 100, y: 100, w: 80, h: 80 } }),
      [6],
    )
    expect(withAvoid).toHaveLength(8 + 5 * 4)
  })

  it('空输入返回空数组', () => {
    expect(placeScreenLabels([], { width: 800, height: 600 })).toEqual([])
  })

  it('普通标签落在视口内并带引线', () => {
    const [placed] = placeScreenLabels([screen({})], { width: 800, height: 600 })
    expect(placed.x).toBeGreaterThanOrEqual(4)
    expect(placed.leader).toBe(true)
    expect(placed.overlapsAvoid).toBe(false)
    expect(placed.overlapsLabel).toBe(false)
    expect(placed.centerX).toBeCloseTo(placed.x + placed.w / 2)
  })

  it('fixed 标签居中于锚点,不参与避让评分', () => {
    const [placed] = placeScreenLabels(
      [screen({ fixed: true, anchorX: 10, anchorY: 10 })],
      { width: 800, height: 600 },
    )
    expect(placed.side).toBe('center')
    expect(placed.centerX).toBeCloseTo(10)
    expect(placed.overlapsLabel).toBe(false)
  })

  it('锚点贴边时被视口夹取,不会跑到负坐标', () => {
    const [placed] = placeScreenLabels(
      [screen({ anchorX: 0, anchorY: 0 })], { width: 800, height: 600 },
    )
    expect(placed.x).toBeGreaterThanOrEqual(4)
    expect(placed.y).toBeGreaterThanOrEqual(4)
  })

  it('视口小到极限时仍返回有限坐标(不退化成 NaN)', () => {
    const [placed] = placeScreenLabels([screen({})], { width: 1, height: 1 })
    expect(Number.isFinite(placed.x)).toBe(true)
    expect(Number.isFinite(placed.y)).toBe(true)
  })

  it('固定矩形挡住全部候选时如实标记 overlapsLabel', () => {
    const [placed] = placeScreenLabels(
      [screen({})],
      { width: 800, height: 600 },
      [{ x: 0, y: 0, w: 800, h: 600 }],
    )
    expect(placed.overlapsLabel).toBe(true)
  })

  it('避让矩形无法绕开时标记 overlapsAvoid(调用方据此降透明)', () => {
    const [placed] = placeScreenLabels(
      [screen({ avoidRect: { x: 0, y: 0, w: 800, h: 600 } })],
      { width: 800, height: 600 },
    )
    expect(placed.overlapsAvoid).toBe(true)
  })

  it('avoidWeight 够大时坚决绕开小避让框', () => {
    const avoidRect: Rect = { x: 190, y: 140, w: 20, h: 20 }
    const [placed] = placeScreenLabels(
      [screen({ avoidRect, avoidWeight: 5000 })],
      { width: 800, height: 600 },
    )
    expect(overlapArea(placed, avoidRect)).toBe(0)
  })

  it('preferred 方向决定最终侧边', () => {
    const [placed] = placeScreenLabels(
      [screen({ preferred: ['left'] })], { width: 800, height: 600 },
    )
    expect(placed.side).toBe('left')
  })

  it('零宽高的标签不会算出 NaN 中心点', () => {
    const [placed] = placeScreenLabels(
      [screen({ width: 0, height: 0 })], { width: 800, height: 600 },
    )
    expect(Number.isFinite(placed.centerX)).toBe(true)
    expect(Number.isFinite(placed.centerY)).toBe(true)
  })

  it('多个标签依次占位,互不重叠', () => {
    const placed = placeScreenLabels(
      [screen({ id: 'a' }), screen({ id: 'b' }), screen({ id: 'c' })],
      { width: 800, height: 600 },
    )
    expect(overlapArea(placed[0], placed[1])).toBe(0)
    expect(overlapArea(placed[1], placed[2])).toBe(0)
    expect(overlapArea(placed[0], placed[2])).toBe(0)
  })
})


describe('shapeObstacleRects:图形占位', () => {
  it('点按半径(至少 3px)加 pad 生成方块', () => {
    const rects = shapeObstacleRects([{ kind: 'point', x: 10, y: 20 }])
    expect(rects).toHaveLength(1)
    expect(rects[0]).toEqual({ x: 5, y: 15, w: 10, h: 10 })
  })

  it('点带自定义半径时用真实半径', () => {
    const [rect] = shapeObstacleRects([{ kind: 'point', x: 0, y: 0, r: 8 }])
    expect(rect.w).toBe(20) // (8 + 2) * 2
  })

  it('圆用 24 个采样点近似,避免文字落在圆周上', () => {
    const rects = shapeObstacleRects([{ kind: 'circle', x: 0, y: 0, r: 10 }])
    expect(rects).toHaveLength(24)
    expect(rects.every((rect) => Math.hypot(rect.x + 2, rect.y + 2) <= 10.001)).toBe(true)
  })

  it('圆没有 r 时用 radius,都没有则退化成 1', () => {
    expect(shapeObstacleRects([{ kind: 'circle', x: 0, y: 0, radius: 5 }])[0].x)
      .toBeCloseTo(3)
    const unit = shapeObstacleRects([{ kind: 'circle', x: 0, y: 0 }])
    expect(unit[0].x).toBeCloseTo(-1)
  })

  it('线段按默认步长采样(每 10px 一个小方块)', () => {
    const rects = shapeObstacleRects([{ kind: 'segment', from: [0, 0], to: [30, 0] }])
    expect(rects).toHaveLength(4) // ceil(30/10) + 1
  })

  it('缺 from/to 的线段按原点处理,不抛异常', () => {
    // 零长线仍按一个点采样:count 至少为 1,所以是两个重叠小方块
    const rects = shapeObstacleRects([{ kind: 'line' }])
    expect(rects).toHaveLength(2)
    expect(rects[0]).toEqual({ x: -2, y: -2, w: 4, h: 4 })
  })

  it('曲线点集降采样(步长随点数增长),不会生成上万个方块', () => {
    const points = Array.from({ length: 4000 }, (_, i) => [i, 0])
    const rects = shapeObstacleRects([{ kind: 'curve', points }])
    // 4000 点 → 约 160 段 → 每段再按 8px 采样
    expect(rects.length).toBeLessThan(900)
    expect(rects.length).toBeGreaterThan(100)
  })

  it('多边形额外补一个包围盒(实心填充也要避开)', () => {
    const rects = shapeObstacleRects([
      { kind: 'polygon', points: [[0, 0], [60, 0], [0, 60]] },
    ])
    const box = rects[rects.length - 1]
    expect(box.x).toBe(-2)
    expect(box.w).toBe(64)
  })

  it('points 里的坏点被过滤,不会求出 NaN 包围盒', () => {
    const rects = shapeObstacleRects([
      {
        kind: 'polygon',
        points: [[0, 0], [10, 0], [0, 10], ['a', 'b'] as unknown as number[]],
      },
    ])
    expect(rects.every((rect) => Number.isFinite(rect.x) && Number.isFinite(rect.w)))
      .toBe(true)
  })

  it('未知 kind 不产生占位', () => {
    expect(shapeObstacleRects([{ kind: 'note', x: 1, y: 1 }])).toEqual([])
  })
})

describe('figureRectOfShapes:主体包围盒', () => {
  it('空数组返回 null(没有主体就没有“排到外面”这回事)', () => {
    expect(figureRectOfShapes([])).toBeNull()
  })

  it('点与圆按半径扩出包围盒', () => {
    const rect = figureRectOfShapes([{ kind: 'point', x: 0, y: 0, r: 5 }])!
    expect(rect).toEqual({ x: -5, y: -5, w: 10, h: 10 })
  })

  it('线段/向量用端点', () => {
    const rect = figureRectOfShapes([
      { kind: 'segment', from: [0, 0], to: [100, 50] },
      { kind: 'vector', from: [10, 10], to: [20, 20] },
    ])!
    expect(rect).toEqual({ x: 0, y: 0, w: 100, h: 50 })
  })

  it('点集形状遍历全部点', () => {
    const rect = figureRectOfShapes([
      { kind: 'polygon', points: [[-10, -20], [30, 40]] },
    ])!
    expect(rect).toEqual({ x: -10, y: -20, w: 40, h: 60 })
  })

  it('只有轴时退化成用轴本身(至少别返回 null)', () => {
    const rect = figureRectOfShapes([
      { kind: 'axis', from: [-10, 0], to: [10, 0] },
    ])!
    expect(rect.w).toBe(20)
    expect(rect.h).toBe(1) // 高度为 0 时兜底成 1,避免后续除零
  })

  it('坐标全是 NaN 时返回 null(宁可不排,也不要 NaN 盒子)', () => {
    expect(figureRectOfShapes([{ kind: 'point', x: 'a', y: 'b' }])).toBeNull()
  })

  it('缺 from/to 的线段不影响其他形状', () => {
    const rect = figureRectOfShapes([
      { kind: 'segment' },
      { kind: 'point', x: 3, y: 4, r: 2 },
    ])!
    expect(rect).toEqual({ x: 1, y: 2, w: 4, h: 4 })
  })
})

describe('outwardSides:按锚点象限给出朝外优先方向', () => {
  const figure: Rect = { x: 0, y: 0, w: 100, h: 100 }

  it('没有主体时不给任何偏好', () => {
    expect(outwardSides({ x: 0, y: 0 }, null)).toEqual([])
  })

  it('四个象限各先朝自己那一侧', () => {
    expect(outwardSides({ x: 0, y: 50 }, figure)[0]).toBe('left')
    expect(outwardSides({ x: 100, y: 50 }, figure)[0]).toBe('right')
    expect(outwardSides({ x: 50, y: 0 }, figure)[0]).toBe('top')
    expect(outwardSides({ x: 50, y: 100 }, figure)[0]).toBe('bottom')
  })

  it('横纵距离相等时横向优先(文字横排更自然)', () => {
    expect(outwardSides({ x: 0, y: 0 }, figure)[0]).toBe('left')
    expect(outwardSides({ x: 100, y: 100 }, figure)[0]).toBe('right')
  })

  it('四个方向都在列表里,只是顺序不同', () => {
    const sides = outwardSides({ x: 0, y: 50 }, figure)
    expect([...sides].sort()).toEqual(['bottom', 'left', 'right', 'top'])
  })
})

