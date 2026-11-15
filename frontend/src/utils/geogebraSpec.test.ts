/**
 * geogebraSpec:GeoGebra 2D XML → DiagramSpec,以及安全表达式求值器。
 *
 * 为什么这条链路值得测:前端拿到的是模型/外部粘贴来的 XML 字符串,
 * 一旦解析器看走眼,轻则图里多出一条穿过画布的“幽灵直线”,
 * 重则把 1e308 之类坐标画进 SVG 让整页卡死。
 * 表达式求值器更是不能出错 —— 它替代了 eval,是唯一的“算数”入口。
 */
import { describe, expect, it } from 'vitest'
import { compileExpression, diagramFromGeoGebraXml } from '@/utils/geogebraSpec'

const wrap = (inner: string): string =>
  `<geogebra><euclidianView/><construction>${inner}</construction></geogebra>`

describe('compileExpression:安全表达式求值', () => {
  it('多项式与隐式乘法(GeoGebra 惯用 2x、x(y+1) 写法)', () => {
    const square = compileExpression('x^2')!
    expect(square(3)).toBe(9)
    const implicit = compileExpression('2x')!
    expect(implicit(5)).toBe(10)
    const nested = compileExpression('2(x+1)(x-1)')!
    expect(nested(3)).toBe(16)
  })

  it('常量 pi / e 与一元函数', () => {
    expect(compileExpression('sin(pi/2)')!(0)).toBeCloseTo(1)
    expect(compileExpression('ln(e)')!(0)).toBeCloseTo(1)
    expect(compileExpression('sqrt(16)')!(0)).toBe(4)
    expect(compileExpression('abs(-3)')!(0)).toBe(3)
  })

  it('log 允许 1~2 个参数(缺省底数按 10 处理)', () => {
    expect(compileExpression('log(8,2)')!(0)).toBeCloseTo(3)
    expect(compileExpression('log(100)')!(0)).toBeCloseTo(2)
  })

  it('变参函数 min/max:2~8 个参数', () => {
    expect(compileExpression('min(3,1,2)')!(0)).toBe(1)
    expect(compileExpression('max(1,5,2,4)')!(0)).toBe(5)
    // 超过 8 个参数属于畸形输入,应整体判失败而不是静默截断
    expect(compileExpression('max(1,2,3,4,5,6,7,8,9)')).toBeNull()
  })

  it('末尾带多余 token 视为畸形,不返回半成品函数', () => {
    expect(compileExpression('x)')).toBeNull()
    expect(compileExpression('1+')).toBeNull()
  })

  it('非法字符 / 坏数字直接判失败', () => {
    expect(compileExpression('x%2')).toBeNull()
    expect(compileExpression('1.2.3')).toBeNull()
    expect(compileExpression('')).toBeNull()
  })

  it('未知标识符与括号不闭合不应抛异常,只返回 null', () => {
    expect(compileExpression('foo(1)')).toBeNull()
    expect(compileExpression('y+1')).toBeNull()
    expect(compileExpression('(1+2')).toBeNull()
    expect(compileExpression('sin(')).toBeNull()
  })

  it('函数参数个数不对时判失败', () => {
    expect(compileExpression('sin(1,2)')).toBeNull()
    expect(compileExpression('pow(2)')).toBeNull()
  })

  it('符号归一化:× ÷ π 上标与 Unicode 减号都当普通运算符', () => {
    expect(compileExpression('2×3')!(0)).toBe(6)
    expect(compileExpression('6÷3')!(0)).toBe(2)
    expect(compileExpression('2π')!(0)).toBeCloseTo(2 * Math.PI)
    expect(compileExpression('x²')!(4)).toBe(16)
    expect(compileExpression('x³')!(2)).toBe(8)
    expect(compileExpression('1−-1')!(0)).toBe(2)
    expect(compileExpression('  2 · 3  ')!(0)).toBe(6)
  })

  it('一元负号与幂的结合顺序', () => {
    expect(compileExpression('-x^2')!(3)).toBe(-9)
    expect(compileExpression('+x')!(7)).toBe(7)
    expect(compileExpression('2^-1')!(0)).toBeCloseTo(0.5)
  })

  it('三角/反三角/双曲等函数都可求值', () => {
    expect(compileExpression('cos(0)')!(0)).toBe(1)
    expect(compileExpression('tan(0)')!(0)).toBe(0)
    expect(compileExpression('sec(0)')!(0)).toBe(1)
    expect(compileExpression('csc(pi/2)')!(0)).toBeCloseTo(1)
    expect(compileExpression('cot(pi/4)')!(0)).toBeCloseTo(1)
    expect(compileExpression('asin(1)')!(0)).toBeCloseTo(Math.PI / 2)
    expect(compileExpression('acos(1)')!(0)).toBe(0)
    expect(compileExpression('atan(0)')!(0)).toBe(0)
    expect(compileExpression('sinh(0)')!(0)).toBe(0)
    expect(compileExpression('cosh(0)')!(0)).toBe(1)
    expect(compileExpression('tanh(0)')!(0)).toBe(0)
    expect(compileExpression('exp(0)')!(0)).toBe(1)
    expect(compileExpression('floor(2.7)')!(0)).toBe(2)
    expect(compileExpression('ceil(2.1)')!(0)).toBe(3)
    expect(compileExpression('round(2.6)')!(0)).toBe(3)
    expect(compileExpression('sign(-4)')!(0)).toBe(-1)
    expect(compileExpression('pow(2,10)')!(0)).toBe(1024)
  })
})

describe('diagramFromGeoGebraXml:整体与降级', () => {
  it('空串或没有 construction 时返回 null(而不是空 spec 占位)', () => {
    expect(diagramFromGeoGebraXml('')).toBeNull()
    expect(diagramFromGeoGebraXml('<geogebra/>')).toBeNull()
  })

  it('construction 里没有任何可画对象时返回 null', () => {
    expect(diagramFromGeoGebraXml('<geogebra><construction></construction></geogebra>'))
      .toBeNull()
  })

  it('没有 </construction> 结束标签也能解析(截断的 XML)', () => {
    const spec = diagramFromGeoGebraXml(
      '<geogebra><construction><element type="point" label="A">'
      + '<coords x="1" y="2" z="1"/></element>',
    )
    expect(spec?.shapes).toHaveLength(1)
    expect(spec?.schemaVersion).toBe(1)
    expect(spec?.type).toBe('plot2d')
  })
})

describe('diagramFromGeoGebraXml:点', () => {
  const point = (label: string, x: string, y: string, z = '1'): string =>
    `<element type="point" label="${label}"><coords x="${x}" y="${y}" z="${z}"/></element>`

  it('把 point 元素转成点形状并保留标签', () => {
    const spec = diagramFromGeoGebraXml(wrap(point('A', '1', '2')))!
    expect(spec.shapes).toEqual([{ kind: 'point', x: 1, y: 2, label: 'A' }])
  })

  it('同坐标的重复点只画一个(避免叠字)', () => {
    const spec = diagramFromGeoGebraXml(wrap(point('A', '1', '2') + point('B', '1', '2')))!
    expect(spec.shapes).toHaveLength(1)
  })

  it('x/y/z/f 这类轴名不当标签,只有 g 例外', () => {
    const shapes = diagramFromGeoGebraXml(
      wrap(point('x', '1', '1') + point('g', '2', '2') + point('A1', '3', '3')),
    )!.shapes
    expect(shapes.map((item) => item.label)).toEqual([undefined, 'g', 'A1'])
  })

  it('超长标签按正则判非法,直接丢标签而不是截断', () => {
    const shapes = diagramFromGeoGebraXml(wrap(point('abcdefghi', '1', '1')))!.shapes
    expect(shapes[0]).toEqual({ kind: 'point', x: 1, y: 1 })
  })

  it('非有限坐标或超过 1e4 的点被丢弃', () => {
    expect(diagramFromGeoGebraXml(wrap(point('A', 'abc', '1')))).toBeNull()
    expect(diagramFromGeoGebraXml(wrap(point('A', '2e4', '1')))).toBeNull()
  })

  it('缺 coords 的 point 元素被跳过', () => {
    expect(diagramFromGeoGebraXml(wrap('<element type="point" label="A"></element>')))
      .toBeNull()
  })

  it('XML 实体(数字与十六进制)在属性里被解码', () => {
    const spec = diagramFromGeoGebraXml(
      wrap('<element type="point" label="A">'
        + '<coords x="&#49;" y="&#x32;" z="1"/></element>'),
    )!
    expect(spec.shapes[0]).toEqual({ kind: 'point', x: 1, y: 2, label: 'A' })
  })

  it('无法识别的元素类型与无标签元素都不产生形状', () => {
    const xml = wrap(
      '<element type="text" label="t"><coords x="1" y="1" z="1"/></element>'
      + '<element type="point"><coords x="1" y="1" z="1"/></element>',
    )
    expect(diagramFromGeoGebraXml(xml)).toBeNull()
  })
})
describe('diagramFromGeoGebraXml:段/射线/向量', () => {
  const point = (label: string, x: string, y: string): string =>
    `<element type="point" label="${label}"><coords x="${x}" y="${y}" z="1"/></element>`
  const command = (name: string, inputs: string[], outputs: string[]): string =>
    `<command name="${name}">`
    + inputs.map((item, index) => `<input a${index}="${item}"/>`).join('')
    + outputs.map((item, index) => `<output a${index}="${item}"/>`).join('')
    + '</command>'

  it('Segment 命令的两个端点被解析成段', () => {
    const xml = wrap(
      point('A', '0', '0') + point('B', '2', '3')
      + command('Segment', ['A', 'B'], ['s'])
      + '<element type="segment" label="s"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes)
      .toContainEqual({ kind: 'segment', from: [0, 0], to: [2, 3] })
  })

  it('输入是字面量坐标 "(1,2)" 时也能解析(手写命令)', () => {
    const xml = wrap(
      point('A', '0', '0')
      + command('Segment', ['(1,2)', '(3,4)'], ['s'])
      + '<element type="segment" label="s"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes)
      .toContainEqual({ kind: 'segment', from: [1, 2], to: [3, 4] })
  })

  it('字面量坐标非法时退回 coords 直线分支', () => {
    const xml = wrap(
      point('A', '0', '0')
      + command('Segment', ['(1,2,3)', 'nope'], ['s'])
      + '<element type="segment" label="s"><coords x="0" y="1" z="0"/></element>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.some((item) => item.kind === 'line'))
      .toBe(true)
  })

  it('Ray 有起点与方向点时以两点连线近似', () => {
    const xml = wrap(
      point('A', '0', '0') + point('B', '1', '1')
      + command('Ray', ['A', 'B'], ['r'])
      + '<element type="ray" label="r"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes)
      .toContainEqual({ kind: 'segment', from: [0, 0], to: [1, 1] })
  })

  it('Ray 缺端点时不画(避免冒出一条零长线)', () => {
    const xml = wrap(
      point('A', '0', '0')
      + command('Ray', ['A', 'nope'], ['r'])
      + '<element type="ray" label="r"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.every((item) => item.kind !== 'segment'))
      .toBe(true)
  })

  it('Vector 命令的两个点转成向量并保留标签', () => {
    const xml = wrap(
      point('A', '0', '0') + point('B', '3', '4')
      + command('Vector', ['A', 'B'], ['v'])
      + '<element type="vector" label="v"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes).toContainEqual({
      kind: 'vector', from: [0, 0], to: [3, 4], label: 'v',
    })
  })

  it('没有命令时用 startPoint + coords 还原向量', () => {
    const xml = wrap(
      point('A', '1', '1')
      + '<element type="vector" label="v">'
      + '<startPoint exp="A"/><coords x="2" y="0" z="0"/>'
      + '</element>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes).toContainEqual({
      kind: 'vector', from: [1, 1], to: [3, 1], label: 'v',
    })
  })

  it('startPoint 指向不存在的点时不画向量', () => {
    const xml = wrap(
      point('A', '1', '1')
      + '<element type="vector" label="v">'
      + '<startPoint exp="Q"/><coords x="2" y="0" z="0"/>'
      + '</element>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.every((item) => item.kind !== 'vector'))
      .toBe(true)
  })
})

describe('diagramFromGeoGebraXml:直线与切线', () => {
  const point = (label: string, x: string, y: string): string =>
    `<element type="point" label="${label}"><coords x="${x}" y="${y}" z="1"/></element>`

  it('普通直线按已知点包围盒裁剪成有限线段', () => {
    const xml = wrap(
      point('A', '-1', '-1') + point('B', '1', '1')
      + '<element type="line" label="f"><coords x="0" y="1" z="0"/></element>',
    )
    const line = diagramFromGeoGebraXml(xml)!.shapes
      .find((item) => item.kind === 'line')!
    expect(line).toBeDefined()
    expect(line.label).toBeUndefined()
    expect((line.from as number[])[1]).toBeCloseTo(0)
  })

  it('完全没有形状可参考时,直线用默认视口裁剪', () => {
    const xml = wrap('<element type="line" label="f"><coords x="1" y="0" z="0"/></element>')
    const line = diagramFromGeoGebraXml(xml)!.shapes
      .find((item) => item.kind === 'line')!
    // 默认视口 -5..5,再按 span 外扩 12%,得到 ±6.2 的竖直线段
    expect((line.from as number[])[0]).toBeCloseTo(0)
    expect((line.from as number[])[1]).toBeCloseTo(-6.2)
    expect((line.to as number[])[1]).toBeCloseTo(6.2)
  })

  it('切线命令改成以切点为中心的短线段,并标注“切线”', () => {
    const xml = wrap(
      point('A', '1', '1')
      + '<command name="Tangent"><input a0="A"/><input a1="c"/>'
      + '<output a0="t"/></command>'
      + '<element type="line" label="t"><coords x="1" y="1" z="-2"/></element>',
    )
    const tangent = diagramFromGeoGebraXml(xml)!.shapes
      .find((item) => item.kind === 'segment')!
    expect(tangent.label).toBe('切线')
    const from = tangent.from as number[]
    const to = tangent.to as number[]
    // 斜率 -a/b = -1,线段关于切点 (1,1) 对称
    expect((to[1] - from[1]) / (to[0] - from[0])).toBeCloseTo(-1)
    expect((from[0] + to[0]) / 2).toBeCloseTo(1)
    expect((from[1] + to[1]) / 2).toBeCloseTo(1)
  })

  it('竖直切线(b=0)退化成上下短竖线,不会算出 Infinity', () => {
    const xml = wrap(
      point('A', '1', '1')
      + '<command name="Tangent"><input a0="A"/><input a1="c"/>'
      + '<output a0="t"/></command>'
      + '<element type="line" label="t"><coords x="1" y="0" z="-1"/></element>',
    )
    const tangent = diagramFromGeoGebraXml(xml)!.shapes
      .find((item) => item.kind === 'segment')!
    expect((tangent.from as number[])[0]).toBe(1)
    expect((tangent.to as number[])[0]).toBe(1)
    expect(Number.isFinite((tangent.from as number[])[1])).toBe(true)
  })

  it('切线命令但找不到切点时退化为普通直线', () => {
    const xml = wrap(
      point('A', '1', '1')
      + '<command name="Tangent"><input a0="Q"/><output a0="t"/></command>'
      + '<element type="line" label="t"><coords x="0" y="1" z="-1"/></element>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.some((item) => item.kind === 'line'))
      .toBe(true)
  })

  it('坐标非法的直线被跳过,不污染包围盒', () => {
    const xml = wrap(
      point('A', '0', '0')
      + '<element type="line" label="f"><coords x="oops" y="1" z="0"/></element>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.every((item) => item.kind !== 'line'))
      .toBe(true)
  })

  it('缺 coords 的 line 元素不产生任何形状', () => {
    expect(diagramFromGeoGebraXml(wrap('<element type="line" label="f"></element>')))
      .toBeNull()
  })
})


describe('diagramFromGeoGebraXml:圆锥曲线与多边形', () => {
  const matrix = (a0: string, a1: string, a2: string, a3 = '0', a4 = '0', a5 = '0'): string =>
    `<matrix A0="${a0}" A1="${a1}" A2="${a2}" A3="${a3}" A4="${a4}" A5="${a5}"/>`

  it('标准圆矩阵还原成圆心与半径', () => {
    const spec = diagramFromGeoGebraXml(
      wrap(`<element type="conic" label="c">${matrix('1', '1', '-4')}</element>`),
    )!
    expect(spec.shapes[0]).toMatchObject({ kind: 'circle', r: 2 })
    expect(Math.abs(spec.shapes[0].x as number)).toBe(0)
    expect(Math.abs(spec.shapes[0].y as number)).toBe(0)
  })

  it('circle 元素与 conic 走同一分支', () => {
    const spec = diagramFromGeoGebraXml(
      wrap(`<element type="circle" label="c">${matrix('1', '1', '-9')}</element>`),
    )!
    expect(spec.shapes[0]).toMatchObject({ kind: 'circle', r: 3 })
  })

  it('含 xy 交叉项 / 长短轴不等 / 零半径的矩阵不是圆,直接跳过', () => {
    expect(diagramFromGeoGebraXml(wrap(
      `<element type="conic" label="c">${matrix('1', '1', '-4', '1')}</element>`,
    ))).toBeNull()
    expect(diagramFromGeoGebraXml(wrap(
      `<element type="conic" label="c">${matrix('1', '2', '-4')}</element>`,
    ))).toBeNull()
    expect(diagramFromGeoGebraXml(wrap(
      `<element type="conic" label="c">${matrix('1', '1', '0')}</element>`,
    ))).toBeNull()
  })

  it('半径超过 1e4 的圆视为异常输入(画出来会撑爆视口)', () => {
    expect(diagramFromGeoGebraXml(wrap(
      `<element type="conic" label="c">${matrix('1', '1', '-1e9')}</element>`,
    ))).toBeNull()
  })

  it('矩阵缺项或非数字时跳过', () => {
    expect(diagramFromGeoGebraXml(wrap(
      `<element type="conic" label="c">${matrix('1', 'x', '-4')}</element>`,
    ))).toBeNull()
    expect(diagramFromGeoGebraXml(wrap('<element type="conic" label="c"></element>')))
      .toBeNull()
  })

  it('Polygon 命令的三点转成多边形,并消费掉输出标签', () => {
    const xml = wrap(
      '<element type="point" label="A"><coords x="0" y="0" z="1"/></element>'
      + '<element type="point" label="B"><coords x="2" y="0" z="1"/></element>'
      + '<element type="point" label="C"><coords x="0" y="2" z="1"/></element>'
      + '<command name="Polygon"><input a0="A"/><input a1="B"/><input a2="C"/>'
      + '<output a0="p"/></command>'
      + '<element type="polygon" label="p"/>'
      + '<element type="point" label="p"><coords x="9" y="9" z="1"/></element>',
    )
    const spec = diagramFromGeoGebraXml(xml)!
    expect(spec.shapes).toContainEqual({
      kind: 'polygon', points: [[0, 0], [2, 0], [0, 2]],
    })
    // 输出标签 p 已被多边形消费,后面的同名 point 元素不该再画点
    expect(spec.shapes.some((item) => item.kind === 'point' && item.x === 9)).toBe(false)
  })

  it('三点不足的多边形被跳过(退化图形没有意义)', () => {
    const xml = wrap(
      '<element type="point" label="A"><coords x="0" y="0" z="1"/></element>'
      + '<command name="Polygon"><input a0="A"/><input a1="B"/>'
      + '<output a0="p"/></command>'
      + '<element type="polygon" label="p"/>',
    )
    expect(diagramFromGeoGebraXml(xml)!.shapes.every((item) => item.kind !== 'polygon'))
      .toBe(true)
  })
})

describe('diagramFromGeoGebraXml:函数曲线采样', () => {
  const fn = (label: string, exp: string): string =>
    `<expression label="${label}" exp="${exp}"/>`
    + `<element type="function" label="${label}"/>`

  it('y=x^2 采样成单段曲线,标签用上标美化', () => {
    const spec = diagramFromGeoGebraXml(wrap(fn('f', 'y=x^2')))!
    expect(spec.shapes).toHaveLength(1)
    expect(spec.shapes[0].kind).toBe('curve')
    expect(spec.shapes[0].label).toBe('y=x²')
    expect((spec.shapes[0].points as number[][]).length).toBeGreaterThan(200)
  })

  it('表达式里没有等号时整串当函数体', () => {
    const spec = diagramFromGeoGebraXml(wrap(fn('f', '2*x')))!
    expect(spec.shapes[0].label).toBe('y=2·x')
  })

  it('只有单点作为参考时采样区间被撑到至少 2 宽', () => {
    const xml = wrap(
      '<element type="point" label="A"><coords x="0" y="0" z="1"/></element>'
      + fn('f', 'x'),
    )
    const curve = diagramFromGeoGebraXml(xml)!.shapes
      .find((item) => item.kind === 'curve')!
    const points = curve.points as number[][]
    expect(points[points.length - 1][0] - points[0][0]).toBeGreaterThanOrEqual(2)
  })

  it('间断函数(1/x)被切成多段,不会连出一条穿原点的假线', () => {
    const spec = diagramFromGeoGebraXml(wrap(fn('f', '1/x')))!
    expect(spec.shapes.length).toBeGreaterThan(1)
    expect(spec.shapes.every((item) => item.kind === 'curve')).toBe(true)
  })

  it('定义域外返回 NaN 的 log(x) 只保留右支', () => {
    const spec = diagramFromGeoGebraXml(wrap(fn('f', 'log(x)')))!
    const curve = spec.shapes.find((item) => item.kind === 'curve')!
    const points = curve.points as number[][]
    expect(points.every((point) => point[0] > 0)).toBe(true)
  })

  it('表达式语法错误或缺失时一个形状都不画', () => {
    expect(diagramFromGeoGebraXml(wrap(fn('f', 'y=foo(x)')))).toBeNull()
    expect(diagramFromGeoGebraXml(wrap('<element type="function" label="f"/>')))
      .toBeNull()
  })

  it('超长表达式标签被截断到 170 字符以内', () => {
    const long = 'x'.concat('+x'.repeat(120))
    const spec = diagramFromGeoGebraXml(wrap(fn('f', long)))!
    expect((spec.shapes[0].label as string).length).toBeLessThanOrEqual(170)
  })
})

