/**
 * geogebra3dSpec:GeoGebra 3D XML → geometry3d。
 *
 * 为什么这条重要:3D 构造里的坐标是齐次形式 x/w、y/w、z/w,
 * w=0 就是“无穷远点”,一旦漏判就会在画布上生成 NaN 顶点,
 * 整块 WebGL 场景直接黑屏。这里逐条锁死退化情形。
 */
import { describe, expect, it } from 'vitest'
import { diagramFromGeoGebra3DXml } from '@/utils/geogebra3dSpec'

const wrap = (inner: string): string =>
  `<geogebra><construction>${inner}</construction></geogebra>`

const point3d = (label: string, x: string, y: string, z: string, w?: string): string =>
  `<element type="point3d" label="${label}"><coords x="${x}" y="${y}" z="${z}"`
  + `${w === undefined ? '' : ` w="${w}"`}/></element>`

const command = (name: string, inputs: string[], outputs: string[]): string =>
  `<command name="${name}">`
  + inputs.map((item, index) => `<input a${index}="${item}"/>`).join('')
  + outputs.map((item, index) => `<output a${index}="${item}"/>`).join('')
  + '</command>'

describe('diagramFromGeoGebra3DXml:入口与降级', () => {
  it('空串 / 无 construction 返回 null', () => {
    expect(diagramFromGeoGebra3DXml('')).toBeNull()
    expect(diagramFromGeoGebra3DXml('<geogebra/>')).toBeNull()
  })

  it('空 construction 返回 null(不返回空 spec)', () => {
    expect(diagramFromGeoGebra3DXml(wrap(''))).toBeNull()
  })

  it('construction 未闭合时仍能解析出前半部分', () => {
    const xml = '<geogebra><construction>' + point3d('A', '1', '2', '3')
    expect(diagramFromGeoGebra3DXml(xml)!.shapes).toHaveLength(1)
  })

  it('产出的 spec 类型固定为 geometry3d 且带 schemaVersion', () => {
    const spec = diagramFromGeoGebra3DXml(wrap(point3d('A', '1', '2', '3')))!
    expect(spec).toMatchObject({ type: 'geometry3d', schemaVersion: 1 })
    expect(spec.nodes).toEqual([])
    expect(spec.annotations).toEqual([])
  })
})

describe('diagramFromGeoGebra3DXml:点与齐次坐标', () => {
  it('普通点转成带 z 的点形状', () => {
    expect(diagramFromGeoGebra3DXml(wrap(point3d('A', '1', '2', '3')))!.shapes)
      .toEqual([{ kind: 'point', x: 1, y: 2, z: 3, label: 'A' }])
  })

  it('齐次坐标按 w 归一化后再画', () => {
    const shape = diagramFromGeoGebra3DXml(wrap(point3d('A', '2', '4', '6', '2')))!.shapes[0]
    expect(shape).toMatchObject({ x: 1, y: 2, z: 3 })
  })

  it('w=0 的无穷远点被丢弃(否则坐标变 Infinity)', () => {
    expect(diagramFromGeoGebra3DXml(wrap(point3d('A', '1', '1', '1', '0')))).toBeNull()
    expect(diagramFromGeoGebra3DXml(wrap(point3d('A', '1', '1', '1', 'abc')))).toBeNull()
  })

  it('坐标超过 1e4 或非有限时丢弃', () => {
    expect(diagramFromGeoGebra3DXml(wrap(point3d('A', '1e5', '0', '0')))).toBeNull()
    expect(diagramFromGeoGebra3DXml(wrap(point3d('A', 'NaN', '0', '0')))).toBeNull()
  })

  it('同坐标重复点只保留一个', () => {
    const xml = wrap(point3d('A', '1', '1', '1') + point3d('B', '1', '1', '1'))
    expect(diagramFromGeoGebra3DXml(xml)!.shapes).toHaveLength(1)
  })

  it('标签不合法时不带 label 字段', () => {
    const shapes = diagramFromGeoGebra3DXml(wrap(point3d('a b', '1', '1', '1')))!.shapes
    expect(shapes[0]).toEqual({ kind: 'point', x: 1, y: 1, z: 1 })
  })

  it('缺 coords 的 point3d 元素被跳过', () => {
    expect(diagramFromGeoGebra3DXml(wrap('<element type="point3d" label="A"></element>')))
      .toBeNull()
  })
})


describe('diagramFromGeoGebra3DXml:线与段', () => {
  it('Line 命令的两点确定方向,并按包围盒扩展成有限线段', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0') + point3d('B', '1', '0', '0')
      + command('Line', ['A', 'B'], ['l'])
      + '<element type="line3d" label="l"/>',
    )
    const segment = diagramFromGeoGebra3DXml(xml)!.shapes
      .find((item) => item.kind === 'segment')!
    expect(segment.from).toEqual([-2.8, 0, 0])
    expect(segment.to).toEqual([2.8, 0, 0])
  })

  it('没有命令时用 ox/oy/oz + vx/vy/vz 还原直线', () => {
    const xml = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="line3d" label="l">'
      + '<coords ox="0" oy="0" oz="0" vx="0" vy="1" vz="0"/>'
      + '</element>',
    )
    const segment = diagramFromGeoGebra3DXml(xml)!.shapes
      .find((item) => item.kind === 'segment')!
    expect((segment.from as number[])[1]).toBeCloseTo(-2.8)
    expect((segment.to as number[])[1]).toBeCloseTo(2.8)
  })

  it('方向向量为零的直线被跳过(无法确定画到哪)', () => {
    const xml = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="line3d" label="l">'
      + '<coords ox="0" oy="0" oz="0" vx="0" vy="0" vz="0"/>'
      + '</element>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes.every((item) => item.kind !== 'segment'))
      .toBe(true)
  })

  it('line3d 既无命令也无 coords 时静默跳过', () => {
    expect(diagramFromGeoGebra3DXml(wrap('<element type="line3d" label="l"/>'))).toBeNull()
  })

  it('Segment 命令的两点直接成段', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0') + point3d('B', '1', '2', '3')
      + command('Segment', ['A', 'B'], ['s'])
      + '<element type="segment3d" label="s"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes)
      .toContainEqual({ kind: 'segment', from: [0, 0, 0], to: [1, 2, 3] })
  })

  it('Segment 的点解析失败时不画', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0')
      + command('Segment', ['A', 'nope'], ['s'])
      + '<element type="segment3d" label="s"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes.every((item) => item.kind !== 'segment'))
      .toBe(true)
  })
})

describe('diagramFromGeoGebra3DXml:向量', () => {
  it('Vector 命令的两点转成向量并带标签', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0') + point3d('B', '1', '1', '1')
      + command('Vector', ['A', 'B'], ['v'])
      + '<element type="vector3d" label="v"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes).toContainEqual({
      kind: 'vector', from: [0, 0, 0], to: [1, 1, 1], label: 'v',
    })
  })

  it('用字面量坐标 "(1,2,3)" 作输入也能构造向量', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0')
      + command('Vector', ['(0,0,0)', '(1,2,3)'], ['v'])
      + '<element type="vector3d" label="v"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes)
      .toContainEqual({ kind: 'vector', from: [0, 0, 0], to: [1, 2, 3], label: 'v' })
  })

  it('没有命令时用 startPoint + coords 还原向量', () => {
    const xml = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="vector3d" label="v">'
      + '<startPoint exp="A"/><coords x="1" y="0" z="0"/>'
      + '</element>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes).toContainEqual({
      kind: 'vector', from: [1, 1, 1], to: [2, 1, 1], label: 'v',
    })
  })

  it('startPoint 无效或无 coords 时不画向量', () => {
    const badStart = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="vector3d" label="v">'
      + '<startPoint exp="Q"/><coords x="1" y="0" z="0"/>'
      + '</element>',
    )
    expect(diagramFromGeoGebra3DXml(badStart)!.shapes
      .every((item) => item.kind !== 'vector')).toBe(true)
    const noCoords = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="vector3d" label="v"><startPoint exp="A"/></element>',
    )
    expect(diagramFromGeoGebra3DXml(noCoords)!.shapes
      .every((item) => item.kind !== 'vector')).toBe(true)
  })
})

describe('diagramFromGeoGebra3DXml:平面 / 球 / 多边形', () => {
  it('plane3d 用法向量与常数项还原成面片', () => {
    const xml = wrap('<element type="plane3d" label="p">'
      + '<coords x="0" y="0" z="1" w="-2"/></element>')
    const plane = diagramFromGeoGebra3DXml(xml)!.shapes[0]
    expect(plane).toMatchObject({ kind: 'plane', x: 0, y: 0, z: 2 })
    expect(plane.normal).toEqual([0, 0, 1])
    expect(plane.width).toBeGreaterThan(0)
  })

  it('零法向量的平面被跳过(画不出朝向)', () => {
    const xml = wrap('<element type="plane3d" label="p">'
      + '<coords x="0" y="0" z="0" w="1"/></element>')
    expect(diagramFromGeoGebra3DXml(xml)).toBeNull()
  })

  it('缺 coords 的 plane3d 不产出形状', () => {
    expect(diagramFromGeoGebra3DXml(wrap('<element type="plane3d" label="p"/>')))
      .toBeNull()
  })

  it('Sphere 命令还原球心与半径', () => {
    const xml = wrap(
      point3d('A', '1', '2', '3')
      + command('Sphere', ['A', '2'], ['s'])
      + '<element type="quadric" label="s"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes)
      .toContainEqual({ kind: 'sphere', x: 1, y: 2, z: 3, r: 2 })
  })

  it('球心缺失时退回原点,但半径非法就整球丢弃', () => {
    const noCenter = wrap(
      command('Sphere', ['nope', '3'], ['s'])
      + '<element type="quadric" label="s"/>',
    )
    expect(diagramFromGeoGebra3DXml(noCenter)!.shapes)
      .toContainEqual({ kind: 'sphere', x: 0, y: 0, z: 0, r: 3 })
    const badRadius = wrap(
      point3d('A', '0', '0', '0')
      + command('Sphere', ['A', '0'], ['s'])
      + '<element type="quadric" label="s"/>',
    )
    expect(diagramFromGeoGebra3DXml(badRadius)!.shapes.every((item) => item.kind !== 'sphere'))
      .toBe(true)
  })

  it('非 sphere 的 quadric(椭球/双曲面)不转换', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0')
      + command('Cone', ['A', '2'], ['c'])
      + '<element type="quadric" label="c"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes.every((item) => item.kind !== 'sphere'))
      .toBe(true)
  })

  it('Polygon 命令的三点以上转成多边形并消费输出标签', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0') + point3d('B', '1', '0', '0')
      + point3d('C', '0', '1', '0')
      + command('Polygon', ['A', 'B', 'C'], ['q'])
      + '<element type="polygon3d" label="q"/>'
      + point3d('q', '9', '9', '9'),
    )
    const spec = diagramFromGeoGebra3DXml(xml)!
    expect(spec.shapes).toContainEqual({
      kind: 'polygon', points: [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    })
    expect(spec.shapes.some((item) => item.kind === 'point' && item.x === 9)).toBe(false)
  })

  it('少于三点的多边形不画', () => {
    const xml = wrap(
      point3d('A', '0', '0', '0')
      + command('Polygon', ['A', 'nope'], ['q'])
      + '<element type="polygon3d" label="q"/>',
    )
    expect(diagramFromGeoGebra3DXml(xml)!.shapes.every((item) => item.kind !== 'polygon'))
      .toBe(true)
  })

  it('曲面/文本等不支持的对象直接忽略', () => {
    const xml = wrap(
      point3d('A', '1', '1', '1')
      + '<element type="surfacecartesian3d" label="S"/>'
      + '<element type="text3d" label="t"/>',
    )
    const spec = diagramFromGeoGebra3DXml(xml)!
    expect(spec.shapes).toHaveLength(1)
    expect(spec.shapes[0].kind).toBe('point')
  })
})
