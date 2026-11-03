/** GeoGebra 2D 构造 XML → 本系统 DiagramSpec。
 *
 * 只解析白名单对象:point / segment / line / vector / circle / polygon /
 * function / tangent / intersect。所有绘制仍由 DiagramSvg 完成。
 */

import type { DiagramShape, DiagramSpec } from './diagramSpec'

const EPS = 1e-9
const MAX_FUNCTION_POINTS = 241

// ---------- 安全表达式求值 ----------

type TokenType = 'num' | 'ident' | 'op' | 'lparen' | 'rparen' | 'comma'

interface Token {
  type: TokenType
  value: string
}

const FUNCTIONS: Record<string, { arity: number | [number, number]; fn: (...args: number[]) => number }> = {
  sin: { arity: 1, fn: Math.sin },
  cos: { arity: 1, fn: Math.cos },
  tan: { arity: 1, fn: Math.tan },
  sec: { arity: 1, fn: (x) => 1 / Math.cos(x) },
  csc: { arity: 1, fn: (x) => 1 / Math.sin(x) },
  cot: { arity: 1, fn: (x) => 1 / Math.tan(x) },
  asin: { arity: 1, fn: Math.asin },
  acos: { arity: 1, fn: Math.acos },
  atan: { arity: 1, fn: Math.atan },
  sinh: { arity: 1, fn: Math.sinh },
  cosh: { arity: 1, fn: Math.cosh },
  tanh: { arity: 1, fn: Math.tanh },
  exp: { arity: 1, fn: Math.exp },
  ln: { arity: 1, fn: Math.log },
  log: { arity: [1, 2], fn: (x, base) => (base === undefined ? Math.log10(x) : Math.log(x) / Math.log(base)) },
  sqrt: { arity: 1, fn: Math.sqrt },
  abs: { arity: 1, fn: Math.abs },
  floor: { arity: 1, fn: Math.floor },
  ceil: { arity: 1, fn: Math.ceil },
  round: { arity: 1, fn: Math.round },
  sign: { arity: 1, fn: Math.sign },
  min: { arity: [2, 8], fn: (...args) => Math.min(...args) },
  max: { arity: [2, 8], fn: (...args) => Math.max(...args) },
  pow: { arity: 2, fn: Math.pow },
}

function normalizeExpression(source: string): string {
  return source
    .replace(/[−–—]/g, '-')
    .replace(/[×·⋅]/g, '*')
    .replace(/÷/g, '/')
    .replace(/²/g, '^2')
    .replace(/³/g, '^3')
    .replace(/π/g, 'pi')
    .replace(/\s+/g, '')
}

function tokenize(source: string): Token[] | null {
  const text = normalizeExpression(source)
  const tokens: Token[] = []
  let index = 0
  while (index < text.length) {
    const ch = text[index]
    if (/[0-9.]/.test(ch)) {
      let end = index
      while (end < text.length && /[0-9.]/.test(text[end])) end += 1
      const value = text.slice(index, end)
      if (!Number.isFinite(Number(value))) return null
      tokens.push({ type: 'num', value })
      index = end
      continue
    }
    if (/[A-Za-z_]/.test(ch)) {
      let end = index
      while (end < text.length && /[A-Za-z0-9_]/.test(text[end])) end += 1
      tokens.push({ type: 'ident', value: text.slice(index, end).toLowerCase() })
      index = end
      continue
    }
    if ('+-*/^'.includes(ch)) {
      tokens.push({ type: 'op', value: ch })
      index += 1
      continue
    }
    if (ch === '(') {
      tokens.push({ type: 'lparen', value: ch })
      index += 1
      continue
    }
    if (ch === ')') {
      tokens.push({ type: 'rparen', value: ch })
      index += 1
      continue
    }
    if (ch === ',') {
      tokens.push({ type: 'comma', value: ch })
      index += 1
      continue
    }
    return null
  }
  return tokens
}

type UnaryFn = (x: number) => number

class ExpressionParser {
  private index = 0

  constructor(private readonly tokens: Token[]) {}

  parse(): UnaryFn {
    const fn = this.parseExpression()
    if (this.index !== this.tokens.length) throw new Error('trailing tokens')
    return fn
  }

  private peek(): Token | undefined {
    return this.tokens[this.index]
  }

  private consume(): Token {
    const token = this.tokens[this.index]
    if (!token) throw new Error('unexpected end')
    this.index += 1
    return token
  }

  private matchOp(value: string): boolean {
    const token = this.peek()
    return token?.type === 'op' && token.value === value
  }

  private parseExpression(): UnaryFn {
    let left = this.parseTerm()
    while (this.matchOp('+') || this.matchOp('-')) {
      const op = this.consume().value
      const right = this.parseTerm()
      const prev = left
      left = op === '+' ? (x) => prev(x) + right(x) : (x) => prev(x) - right(x)
    }
    return left
  }

  private parseTerm(): UnaryFn {
    let left = this.parseUnary()
    while (true) {
      if (this.matchOp('*') || this.matchOp('/')) {
        const op = this.consume().value
        const right = this.parseUnary()
        const prev = left
        left = op === '*' ? (x) => prev(x) * right(x) : (x) => prev(x) / right(x)
        continue
      }
      const token = this.peek()
      if (token && (token.type === 'num' || token.type === 'ident'
        || token.type === 'lparen')) {
        // GeoGebra 允许 2x、x(y+1) 这类隐式乘法。
        const right = this.parseUnary()
        const prev = left
        left = (x) => prev(x) * right(x)
        continue
      }
      break
    }
    return left
  }

  private parseUnary(): UnaryFn {
    if (this.matchOp('+') || this.matchOp('-')) {
      const op = this.consume().value
      const value = this.parseUnary()
      return op === '-' ? (x) => -value(x) : value
    }
    return this.parsePower()
  }

  private parsePower(): UnaryFn {
    const base = this.parsePrimary()
    if (this.matchOp('^')) {
      this.consume()
      const exponent = this.parseUnary()
      return (x) => Math.pow(base(x), exponent(x))
    }
    return base
  }

  private parsePrimary(): UnaryFn {
    const token = this.consume()
    if (token.type === 'num') {
      const value = Number(token.value)
      return () => value
    }
    if (token.type === 'lparen') {
      const value = this.parseExpression()
      const close = this.consume()
      if (close.type !== 'rparen') throw new Error('missing )')
      return value
    }
    if (token.type !== 'ident') throw new Error('unexpected token')
    const name = token.value
    if (this.peek()?.type === 'lparen' && FUNCTIONS[name]) {
      this.consume()
      const args: UnaryFn[] = []
      if (this.peek()?.type !== 'rparen') {
        args.push(this.parseExpression())
        while (this.peek()?.type === 'comma') {
          this.consume()
          args.push(this.parseExpression())
        }
      }
      const close = this.consume()
      if (close.type !== 'rparen') throw new Error('missing )')
      const spec = FUNCTIONS[name]
      if (Array.isArray(spec.arity)) {
        if (args.length < spec.arity[0] || args.length > spec.arity[1]) {
          throw new Error('bad arity')
        }
      } else if (args.length !== spec.arity) {
        throw new Error('bad arity')
      }
      return (x) => spec.fn(...args.map((arg) => arg(x)))
    }
    if (name === 'x') return (x) => x
    if (name === 'pi') return () => Math.PI
    if (name === 'e') return () => Math.E
    throw new Error('unknown identifier')
  }
}

/** 编译一元表达式;失败返回 null。不求值任意字符串,不使用 eval。 */
export function compileExpression(source: string): UnaryFn | null {
  try {
    const tokens = tokenize(source)
    if (!tokens || !tokens.length) return null
    return new ExpressionParser(tokens).parse()
  } catch {
    return null
  }
}

// ---------- GeoGebra XML 读取 ----------

interface XmlBlock {
  attrs: Record<string, string>
  body: string
}

function decodeXml(value: string): string {
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

function attrMap(source: string): Record<string, string> {
  const attrs: Record<string, string> = {}
  const re = /([A-Za-z_:][A-Za-z0-9_:.-]*)\s*=\s*"([^"]*)"/g
  for (const match of source.matchAll(re)) {
    attrs[match[1]] = decodeXml(match[2])
  }
  return attrs
}

function findBlocks(source: string, tag: string): XmlBlock[] {
  const out: XmlBlock[] = []
  const re = new RegExp(
    `<${tag}\\s+([^>]*?)(?:\\/>|>([\\s\\S]*?)<\\/${tag}>)`,
    'g',
  )
  for (const match of source.matchAll(re)) {
    out.push({ attrs: attrMap(match[1] || ''), body: match[2] || '' })
  }
  return out
}

interface GeoCommand {
  name: string
  inputs: string[]
  outputs: string[]
}

function constructionOf(xml: string): string {
  const start = xml.indexOf('<construction')
  if (start < 0) return xml
  const close = xml.indexOf('</construction>', start)
  return close > start ? xml.slice(start, close) : xml.slice(start)
}

function commandArgs(body: string, tag: 'input' | 'output'): string[] {
  const out: string[] = []
  for (const block of findBlocks(body, tag)) {
    const keys = Object.keys(block.attrs)
      .filter((key) => /^a\d+$/.test(key))
      .sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)))
    for (const key of keys) {
      if (block.attrs[key]) out.push(block.attrs[key])
    }
  }
  return out
}

function commandInputs(body: string): string[] {
  return commandArgs(body, 'input')
}

function commandOutputs(body: string): string[] {
  return commandArgs(body, 'output')
}

interface Point2 {
  x: number
  y: number
}

function finitePoint(x: number, y: number): Point2 | null {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null
  if (Math.abs(x) > 1e4 || Math.abs(y) > 1e4) return null
  return { x, y }
}

function pointLiteral(token: string): Point2 | null {
  const match = token.trim().match(
    /^\(\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*\)$/,
  )
  if (!match) return null
  return finitePoint(Number(match[1]), Number(match[2]))
}

function prettyExpression(source: string): string {
  return source
    .replace(/\^\(?([23])\)?/g, (_match, digit: string) => (digit === '2' ? '²' : '³'))
    .replace(/\*/g, '·')
    .replace(/\s+/g, '')
}

function functionBody(expression: string): string {
  const eq = expression.indexOf('=')
  return (eq >= 0 ? expression.slice(eq + 1) : expression).trim()
}

function pointLabel(label: string): string {
  const text = label.trim()
  if (!/^[A-Za-z][A-Za-z0-9_']{0,5}$/.test(text)) return ''
  if (['x', 'y', 'z', 'f', 'g'].includes(text.toLowerCase()) && text.length === 1) {
    return text.toLowerCase() === 'g' ? text : ''
  }
  return text
}

interface Bounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

function shapeBounds(shapes: DiagramShape[]): Bounds | null {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  const add = (x: number, y: number): void => {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return
    minX = Math.min(minX, x)
    minY = Math.min(minY, y)
    maxX = Math.max(maxX, x)
    maxY = Math.max(maxY, y)
  }
  for (const shape of shapes) {
    if (shape.kind === 'point') {
      add(Number(shape.x), Number(shape.y))
    } else if (shape.kind === 'circle') {
      const r = Math.abs(Number(shape.r) || 0)
      add(Number(shape.x) - r, Number(shape.y) - r)
      add(Number(shape.x) + r, Number(shape.y) + r)
    } else if (['segment', 'line', 'vector'].includes(shape.kind)) {
      const from = Array.isArray(shape.from) ? shape.from : []
      const to = Array.isArray(shape.to) ? shape.to : []
      if (from.length >= 2) add(Number(from[0]), Number(from[1]))
      if (to.length >= 2) add(Number(to[0]), Number(to[1]))
    } else if (Array.isArray(shape.points)) {
      for (const point of shape.points) {
        if (Array.isArray(point) && point.length >= 2) {
          add(Number(point[0]), Number(point[1]))
        }
      }
    }
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null
  return { minX, minY, maxX, maxY }
}

function lineEndpoints(
  a: number,
  b: number,
  c: number,
  bounds: Bounds,
): [Point2, Point2] | null {
  const spanX = Math.max(1, bounds.maxX - bounds.minX)
  const spanY = Math.max(1, bounds.maxY - bounds.minY)
  const minX = bounds.minX - spanX * 0.12
  const maxX = bounds.maxX + spanX * 0.12
  const minY = bounds.minY - spanY * 0.12
  const maxY = bounds.maxY + spanY * 0.12
  const points: Point2[] = []
  if (Math.abs(b) > EPS) {
    for (const x of [minX, maxX]) {
      const y = -(a * x + c) / b
      if (y >= minY - EPS && y <= maxY + EPS) points.push({ x, y })
    }
  }
  if (Math.abs(a) > EPS) {
    for (const y of [minY, maxY]) {
      const x = -(b * y + c) / a
      if (x >= minX - EPS && x <= maxX + EPS) points.push({ x, y })
    }
  }
  const unique: Point2[] = []
  for (const point of points) {
    if (!unique.some((item) => Math.abs(item.x - point.x) < 1e-6
      && Math.abs(item.y - point.y) < 1e-6)) {
      unique.push(point)
    }
  }
  if (unique.length < 2) return null
  let best: [Point2, Point2] = [unique[0], unique[1]]
  let bestDistance = -1
  for (let i = 0; i < unique.length; i += 1) {
    for (let j = i + 1; j < unique.length; j += 1) {
      const distance = Math.hypot(
        unique[i].x - unique[j].x, unique[i].y - unique[j].y,
      )
      if (distance > bestDistance) {
        bestDistance = distance
        best = [unique[i], unique[j]]
      }
    }
  }
  return best
}

function sampleFunction(
  expression: string,
  bounds: Bounds | null,
): DiagramShape[] {
  const fn = compileExpression(expression)
  if (!fn) return []
  let xMin = -5
  let xMax = 5
  if (bounds) {
    const span = Math.max(1, bounds.maxX - bounds.minX)
    xMin = bounds.minX - span * 0.5
    xMax = bounds.maxX + span * 0.5
  }
  if (xMax - xMin < 2) {
    const center = (xMin + xMax) / 2
    xMin = center - 1
    xMax = center + 1
  }
  const step = (xMax - xMin) / (MAX_FUNCTION_POINTS - 1)
  const label = `y=${prettyExpression(expression)}`.slice(0, 170)
  const shapes: DiagramShape[] = []
  let current: number[][] = []
  let lastY: number | null = null
  let labeled = false
  const flush = (): void => {
    if (current.length > 1) {
      shapes.push({
        kind: 'curve', points: current,
        label: labeled ? '' : label,
      })
      labeled = true
    }
    current = []
    lastY = null
  }
  for (let index = 0; index < MAX_FUNCTION_POINTS; index += 1) {
    const x = xMin + step * index
    let y: number
    try {
      y = fn(x)
    } catch {
      flush()
      continue
    }
    if (!Number.isFinite(y) || Math.abs(y) > 1e4) {
      flush()
      continue
    }
    if (lastY !== null && Math.abs(y - lastY) > 200) flush()
    current.push([x, y])
    lastY = y
  }
  flush()
  return shapes
}

function addShape(
  shapes: DiagramShape[],
  shape: DiagramShape,
): void {
  const label = typeof shape.label === 'string' ? shape.label.trim() : ''
  if (label) shape.label = label.slice(0, 170)
  else delete shape.label
  shapes.push(shape)
}

/** 把 GeoGebra getXML() 的结果转成我们自己的 2D DiagramSpec。 */
export function diagramFromGeoGebraXml(xml: string): DiagramSpec | null {
  if (!xml || !xml.includes('<construction')) return null
  const construction = constructionOf(xml)
  const expressions = new Map<string, string>()
  for (const block of findBlocks(construction, 'expression')) {
    const label = block.attrs.label
    if (label && block.attrs.exp) expressions.set(label, block.attrs.exp)
  }
  const commandByOutput = new Map<string, GeoCommand>()
  for (const block of findBlocks(construction, 'command')) {
    const command: GeoCommand = {
      name: (block.attrs.name || '').toLowerCase(),
      inputs: commandInputs(block.body),
      outputs: commandOutputs(block.body),
    }
    for (const output of command.outputs) {
      if (!commandByOutput.has(output)) commandByOutput.set(output, command)
    }
  }
  const elements: XmlBlock[] = findBlocks(construction, 'element')
  const pointMap = new Map<string, Point2>()
  for (const element of elements) {
    const label = element.attrs.label || ''
    if (element.attrs.type !== 'point' || !label) continue
    const coords = findBlocks(element.body, 'coords')[0]
    if (!coords) continue
    const point = finitePoint(
      Number(coords.attrs.x), Number(coords.attrs.y),
    )
    if (point) pointMap.set(label, point)
  }
  let pointBounds: Bounds | null = null
  for (const point of pointMap.values()) {
    if (!pointBounds) {
      pointBounds = {
        minX: point.x, minY: point.y, maxX: point.x, maxY: point.y,
      }
    } else {
      pointBounds.minX = Math.min(pointBounds.minX, point.x)
      pointBounds.minY = Math.min(pointBounds.minY, point.y)
      pointBounds.maxX = Math.max(pointBounds.maxX, point.x)
      pointBounds.maxY = Math.max(pointBounds.maxY, point.y)
    }
  }
  const resolvePoint = (token: string): Point2 | null => {
    const key = token.trim()
    if (pointMap.has(key)) return pointMap.get(key) || null
    return pointLiteral(key)
  }

  const shapes: DiagramShape[] = []
  const consumed = new Set<string>()
  const seenPoints = new Set<string>()
  const pendingLines: Array<{
    a: number
    b: number
    c: number
    label: string
  }> = []
  const pendingTangents: Array<{
    point: Point2
    slope: number | null
  }> = []

  const addPoint = (label: string, point: Point2): void => {
    const key = `${point.x.toFixed(6)}|${point.y.toFixed(6)}`
    if (seenPoints.has(key)) return
    seenPoints.add(key)
    addShape(shapes, {
      kind: 'point', x: point.x, y: point.y,
      label: label ? pointLabel(label) : '',
    })
  }

  for (const element of elements) {
    const label = element.attrs.label || ''
    const type = (element.attrs.type || '').toLowerCase()
    if (!label || consumed.has(label)) continue
    const command = commandByOutput.get(label)
    const coords = findBlocks(element.body, 'coords')[0]
    if (type === 'point') {
      const point = pointMap.get(label)
      if (point) addPoint(label, point)
      continue
    }
    if (type === 'function') {
      const expression = expressions.get(label)
      if (!expression) continue
      const body = functionBody(expression)
      const sampled = sampleFunction(body, shapeBounds(shapes) || pointBounds)
      if (sampled.length) {
        shapes.push(...sampled)
      }
      continue
    }
    if (type === 'line') {
      if (!coords) continue
      const a = Number(coords.attrs.x)
      const b = Number(coords.attrs.y)
      const c = Number(coords.attrs.z)
      if (![a, b, c].every(Number.isFinite)) continue
      if (command?.name === 'tangent') {
        const point = command.inputs.map(resolvePoint).find(
          (item): item is Point2 => item !== null,
        )
        if (point) {
          pendingTangents.push({
            point,
            slope: Math.abs(b) > EPS ? -a / b : null,
          })
          continue
        }
      }
      pendingLines.push({
        a, b, c, label: command?.name === 'tangent' ? '切线' : '',
      })
      continue
    }
    if (type === 'segment') {
      const points = command?.inputs.map(resolvePoint) || []
      if (points.length >= 2 && points[0] && points[1]) {
        addShape(shapes, {
          kind: 'segment', from: [points[0].x, points[0].y],
          to: [points[1].x, points[1].y],
        })
        continue
      }
      if (coords) {
        pendingLines.push({
          a: Number(coords.attrs.x), b: Number(coords.attrs.y),
          c: Number(coords.attrs.z), label: '',
        })
      }
      continue
    }
    if (type === 'ray') {
      const points = command?.inputs.map(resolvePoint) || []
      if (points.length >= 2 && points[0] && points[1]) {
        addShape(shapes, {
          kind: 'segment', from: [points[0].x, points[0].y],
          to: [points[1].x, points[1].y],
        })
      }
      continue
    }
    if (type === 'vector') {
      const points = command?.inputs.map(resolvePoint) || []
      if (points.length >= 2 && points[0] && points[1]) {
        addShape(shapes, {
          kind: 'vector', from: [points[0].x, points[0].y],
          to: [points[1].x, points[1].y],
          label: pointLabel(label),
        })
        continue
      }
      const start = findBlocks(element.body, 'startPoint')[0]
      const origin = start ? resolvePoint(start.attrs.exp || '') : null
      if (origin && coords) {
        addShape(shapes, {
          kind: 'vector', from: [origin.x, origin.y],
          to: [
            origin.x + Number(coords.attrs.x),
            origin.y + Number(coords.attrs.y),
          ],
          label: pointLabel(label),
        })
      }
      continue
    }
    if (type === 'conic' || type === 'circle') {
      const matrix = findBlocks(element.body, 'matrix')[0]
      if (!matrix) continue
      const a0 = Number(matrix.attrs.A0)
      const a1 = Number(matrix.attrs.A1)
      const a2 = Number(matrix.attrs.A2)
      const a3 = Number(matrix.attrs.A3)
      const a4 = Number(matrix.attrs.A4)
      const a5 = Number(matrix.attrs.A5)
      if (![a0, a1, a2, a3, a4, a5].every(Number.isFinite)) continue
      if (Math.abs(a3) > 1e-6 || Math.abs(a0 - a1) > 1e-6 || Math.abs(a0) < EPS) {
        continue
      }
      const centerX = -a4 / a0
      const centerY = -a5 / a1
      const radiusSq = centerX * centerX + centerY * centerY - a2 / a0
      if (radiusSq <= EPS) continue
      const radius = Math.sqrt(radiusSq)
      if (!Number.isFinite(radius) || radius > 1e4) continue
      addShape(shapes, {
        kind: 'circle', x: centerX, y: centerY, r: radius,
      })
      continue
    }
    if (type === 'polygon' || type === 'triangle' || type === 'quadrilateral') {
      const points = (command?.inputs || [])
        .map(resolvePoint)
        .filter((item): item is Point2 => item !== null)
      if (points.length < 3) continue
      addShape(shapes, {
        kind: 'polygon', points: points.map((point) => [point.x, point.y]),
      })
      for (const output of command?.outputs || []) consumed.add(output)
      continue
    }
  }

  const bounds = shapeBounds(shapes) || (
    pendingLines.length || pendingTangents.length
      ? { minX: -5, minY: -5, maxX: 5, maxY: 5 }
      : null
  )
  if (!bounds) return null
  for (const pending of pendingLines) {
    const endpoints = lineEndpoints(pending.a, pending.b, pending.c, bounds)
    if (!endpoints) continue
    addShape(shapes, {
      kind: 'line', from: [endpoints[0].x, endpoints[0].y],
      to: [endpoints[1].x, endpoints[1].y], label: pending.label,
    })
  }
  for (const pending of pendingTangents) {
    const spanX = Math.max(0.5, bounds.maxX - bounds.minX)
    const spanY = Math.max(0.5, bounds.maxY - bounds.minY)
    const dx = Math.max(0.25, spanX * 0.05)
    const dy = Math.max(0.25, spanY * 0.05)
    if (pending.slope === null) {
      addShape(shapes, {
        kind: 'segment',
        from: [pending.point.x, pending.point.y - dy],
        to: [pending.point.x, pending.point.y + dy],
        label: '切线',
      })
    } else {
      addShape(shapes, {
        kind: 'segment',
        from: [
          pending.point.x - dx,
          pending.point.y - pending.slope * dx,
        ],
        to: [
          pending.point.x + dx,
          pending.point.y + pending.slope * dx,
        ],
        label: '切线',
      })
    }
  }
  if (!shapes.length) return null
  return {
    schemaVersion: 1,
    type: 'plot2d',
    nodes: [],
    edges: [],
    shapes,
    annotations: [],
  }
}
