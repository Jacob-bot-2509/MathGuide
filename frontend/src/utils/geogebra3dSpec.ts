/** GeoGebra 3D XML → 本系统 geometry3d。
 *
 * 只转换实数三维可精确构造对象:点、线、段、向量、平面、球、多边形。
 * 参数曲面 `surfacecartesian3d` 不直接给网格,继续由旧构造器/采样处理。
 */

import type { DiagramShape, DiagramSpec } from './diagramSpec'

interface Block {
  attrs: Record<string, string>
  body: string
}

function decode(value: string): string {
  return value.replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, (match, code: string) => {
    if (code[0] === '#') {
      const hex = code[1]?.toLowerCase() === 'x'
      const point = Number.parseInt(code.slice(hex ? 2 : 1), hex ? 16 : 10)
      return Number.isFinite(point) ? String.fromCodePoint(point) : match
    }
    const named: Record<string, string> = {
      amp: '&', lt: '<', gt: '>', quot: '"', apos: "'",
    }
    return named[code.toLowerCase()] ?? match
  })
}

function attrs(source: string): Record<string, string> {
  const out: Record<string, string> = {}
  const re = /([A-Za-z_:][A-Za-z0-9_:.-]*)\s*=\s*"([^"]*)"/g
  for (const match of source.matchAll(re)) out[match[1]] = decode(match[2])
  return out
}

function blocks(source: string, tag: string): Block[] {
  const out: Block[] = []
  const re = new RegExp(
    `<${tag}\\s+([^>]*?)(?:\\/>|>([\\s\\S]*?)<\\/${tag}>)`,
    'g',
  )
  for (const match of source.matchAll(re)) {
    out.push({ attrs: attrs(match[1] || ''), body: match[2] || '' })
  }
  return out
}

function construction(xml: string): string {
  const start = xml.indexOf('<construction')
  if (start < 0) return xml
  const end = xml.indexOf('</construction>', start)
  return end > start ? xml.slice(start, end) : xml.slice(start)
}

function args(body: string, tag: 'input' | 'output'): string[] {
  const out: string[] = []
  for (const block of blocks(body, tag)) {
    const keys = Object.keys(block.attrs)
      .filter((key) => /^a\d+$/.test(key))
      .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
    for (const key of keys) if (block.attrs[key]) out.push(block.attrs[key])
  }
  return out
}

function parsePoint(token: string): [number, number, number] | null {
  const text = token.trim()
  const match = text.match(
    /^\(\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*\)$/,
  )
  if (!match) return null
  const point: [number, number, number] = [
    Number(match[1]), Number(match[2]), Number(match[3]),
  ]
  return point.every(Number.isFinite) ? point : null
}

function pointShape(point: [number, number, number], label = ''): DiagramShape {
  const shape: DiagramShape = {
    kind: 'point', x: point[0], y: point[1], z: point[2],
  }
  if (label) shape.label = label
  return shape
}

function segmentShape(a: [number, number, number], b: [number, number, number],
                      label = ''): DiagramShape {
  const shape: DiagramShape = {
    kind: 'segment', from: a.slice(), to: b.slice(),
  }
  if (label) shape.label = label
  return shape
}

function vectorShape(a: [number, number, number], b: [number, number, number],
                     label = ''): DiagramShape {
  const shape: DiagramShape = {
    kind: 'vector', from: a.slice(), to: b.slice(),
  }
  if (label) shape.label = label
  return shape
}

function planeShape(center: [number, number, number],
                    normal: [number, number, number], size: number,
                    label = ''): DiagramShape | null {
  const length = Math.hypot(...normal)
  if (length < 1e-9) return null
  const shape: DiagramShape = {
    kind: 'plane',
    x: center[0], y: center[1], z: center[2],
    width: size, height: size,
    normal: [normal[0] / length, normal[1] / length, normal[2] / length],
  }
  if (label) shape.label = label
  return shape
}

function pointLabel(name: string): string {
  return /^[A-Za-z][A-Za-z0-9_']{0,5}$/.test(name) ? name : ''
}

function bounds(points: Map<string, [number, number, number]>,
                shapes: DiagramShape[]): { span: number } {
  const values: number[] = []
  for (const point of points.values()) values.push(...point.map(Math.abs))
  for (const shape of shapes) {
    if (shape.kind === 'point') {
      values.push(Math.abs(Number(shape.x)), Math.abs(Number(shape.y)),
        Math.abs(Number(shape.z)))
    }
  }
  return { span: Math.max(2, ...values, 1) * 1.4 }
}

/** 3D 构造 XML → geometry3d;曲面/未知对象跳过。 */
export function diagramFromGeoGebra3DXml(xml: string): DiagramSpec | null {
  if (!xml || !xml.includes('<construction')) return null
  const body = construction(xml)
  const commands = new Map<string, { name: string; inputs: string[]; outputs: string[] }>()
  for (const block of blocks(body, 'command')) {
    const command = {
      name: (block.attrs.name || '').toLowerCase(),
      inputs: args(block.body, 'input'),
      outputs: args(block.body, 'output'),
    }
    for (const output of command.outputs) {
      if (!commands.has(output)) commands.set(output, command)
    }
  }
  const elements = blocks(body, 'element')
  const pointMap = new Map<string, [number, number, number]>()
  for (const element of elements) {
    if (element.attrs.type !== 'point3d' || !element.attrs.label) continue
    const coords = blocks(element.body, 'coords')[0]
    if (!coords) continue
    const w = Number(coords.attrs.w ?? 1)
    if (!Number.isFinite(w) || Math.abs(w) < 1e-9) continue
    const point: [number, number, number] = [
      Number(coords.attrs.x) / w,
      Number(coords.attrs.y) / w,
      Number(coords.attrs.z) / w,
    ]
    if (point.every((value) => Number.isFinite(value) && Math.abs(value) <= 1e4)) {
      pointMap.set(element.attrs.label, point)
    }
  }
  const resolve = (token: string): [number, number, number] | null => {
    const key = token.trim()
    return pointMap.get(key) || parsePoint(key)
  }
  const shapes: DiagramShape[] = []
  const consumed = new Set<string>()
  const seenPoints = new Set<string>()
  const pendingLines: Array<{
    origin: [number, number, number]
    direction: [number, number, number]
    label: string
  }> = []
  const pendingPlanes: Array<{
    normal: [number, number, number]
    constant: number
    label: string
  }> = []

  const addPoint = (name: string, point: [number, number, number]): void => {
    const key = point.map((value) => value.toFixed(6)).join('|')
    if (seenPoints.has(key)) return
    seenPoints.add(key)
    shapes.push(pointShape(point, pointLabel(name)))
  }

  for (const element of elements) {
    const name = element.attrs.label || ''
    const type = (element.attrs.type || '').toLowerCase()
    if (!name || consumed.has(name)) continue
    const command = commands.get(name)
    if (type === 'point3d') {
      const point = pointMap.get(name)
      if (point) addPoint(name, point)
      continue
    }
    if (type === 'line3d') {
      const points = (command?.inputs || []).map(resolve).filter(
        (item): item is [number, number, number] => item !== null,
      )
      if (points.length >= 2) {
        const direction: [number, number, number] = [
          points[1][0] - points[0][0],
          points[1][1] - points[0][1],
          points[1][2] - points[0][2],
        ]
        pendingLines.push({ origin: points[0], direction, label: '' })
        continue
      }
      const coords = blocks(element.body, 'coords')[0]
      if (coords) {
        pendingLines.push({
          origin: [
            Number(coords.attrs.ox), Number(coords.attrs.oy),
            Number(coords.attrs.oz),
          ],
          direction: [
            Number(coords.attrs.vx), Number(coords.attrs.vy),
            Number(coords.attrs.vz),
          ],
          label: '',
        })
      }
      continue
    }
    if (type === 'segment3d') {
      const points = (command?.inputs || []).map(resolve).filter(
        (item): item is [number, number, number] => item !== null,
      )
      if (points.length >= 2) shapes.push(segmentShape(points[0], points[1]))
      continue
    }
    if (type === 'vector3d') {
      const points = (command?.inputs || []).map(resolve).filter(
        (item): item is [number, number, number] => item !== null,
      )
      if (points.length >= 2) {
        shapes.push(vectorShape(points[0], points[1], pointLabel(name)))
        continue
      }
      const start = blocks(element.body, 'startPoint')[0]
      const coords = blocks(element.body, 'coords')[0]
      const origin = start ? resolve(start.attrs.exp || '') : null
      if (origin && coords) {
        const end: [number, number, number] = [
          origin[0] + Number(coords.attrs.x),
          origin[1] + Number(coords.attrs.y),
          origin[2] + Number(coords.attrs.z),
        ]
        shapes.push(vectorShape(origin, end, pointLabel(name)))
      }
      continue
    }
    if (type === 'plane3d') {
      const coords = blocks(element.body, 'coords')[0]
      if (!coords) continue
      pendingPlanes.push({
        normal: [
          Number(coords.attrs.x), Number(coords.attrs.y),
          Number(coords.attrs.z),
        ],
        constant: Number(coords.attrs.w ?? 0),
        label: '',
      })
      continue
    }
    if (type === 'quadric') {
      if (command?.name !== 'sphere') continue
      const points = (command.inputs || []).map(resolve).filter(
        (item): item is [number, number, number] => item !== null,
      )
      const center = points[0] || [0, 0, 0]
      const radius = Number(command.inputs?.[1] ?? 0)
      if (!Number.isFinite(radius) || radius <= 0) continue
      shapes.push({
        kind: 'sphere', x: center[0], y: center[1], z: center[2],
        r: radius,
      })
      continue
    }
    if (type === 'polygon3d' || type === 'triangle' || type === 'quadrilateral') {
      const points = (command?.inputs || []).map(resolve).filter(
        (item): item is [number, number, number] => item !== null,
      )
      if (points.length < 3) continue
      shapes.push({
        kind: 'polygon', points: points.map((point) => point.slice()),
      })
      for (const output of command?.outputs || []) consumed.add(output)
      continue
    }
    // surfacecartesian3d / list / numeric / text 不转,交给 fallback。
  }

  const span = bounds(pointMap, shapes).span
  for (const pending of pendingLines) {
    const length = Math.hypot(...pending.direction)
    if (length < 1e-9) continue
    const unit: [number, number, number] = [
      pending.direction[0] / length,
      pending.direction[1] / length,
      pending.direction[2] / length,
    ]
    const start: [number, number, number] = [
      pending.origin[0] - unit[0] * span,
      pending.origin[1] - unit[1] * span,
      pending.origin[2] - unit[2] * span,
    ]
    const end: [number, number, number] = [
      pending.origin[0] + unit[0] * span,
      pending.origin[1] + unit[1] * span,
      pending.origin[2] + unit[2] * span,
    ]
    shapes.push(segmentShape(start, end, pending.label))
  }
  for (const pending of pendingPlanes) {
    const lengthSq = pending.normal[0] ** 2 + pending.normal[1] ** 2
      + pending.normal[2] ** 2
    if (lengthSq < 1e-9) continue
    const factor = -pending.constant / lengthSq
    const center: [number, number, number] = [
      pending.normal[0] * factor,
      pending.normal[1] * factor,
      pending.normal[2] * factor,
    ]
    const shape = planeShape(center, pending.normal, span * 2, pending.label)
    if (shape) shapes.push(shape)
  }
  if (!shapes.length) return null
  return {
    schemaVersion: 1,
    type: 'geometry3d',
    nodes: [],
    edges: [],
    shapes,
    annotations: [],
  }
}
