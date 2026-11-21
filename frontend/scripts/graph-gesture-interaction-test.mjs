import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { transformSync } from 'esbuild'

const source = readFileSync(new URL('../src/views/GraphView.vue', import.meta.url), 'utf8')
const start = source.indexOf('function svgPoint(')
const end = source.indexOf('\nfunction select(', start)
assert.ok(start >= 0 && end > start, 'graph pointer handlers not found')
const helpers = readFileSync(new URL('../src/utils/graphGesture.ts', import.meta.url), 'utf8')
const code = transformSync(`${helpers}\n${source.slice(start, end)}\nexport { onDown, onMove, onUp }`, {
  loader: 'ts', format: 'cjs',
}).code

const view = { x: 0, y: 0, w: 1000, h: 1000 }
class Point {
  constructor(x = 0, y = 0) { this.x = x; this.y = y }
  matrixTransform() { return new Point(view.x + this.x * view.w / 1000, view.y + this.y * view.h / 1000) }
}
const context = {
  module: { exports: {} }, view, DOMPoint: Point,
  svgEl: { value: { createSVGPoint: () => new Point(), getScreenCTM: () => ({ inverse: () => ({}) }) } },
  layout: { value: { width: 2000 } },
  window: { addEventListener() {}, removeEventListener() {} }, setTimeout() {},
}
vm.runInNewContext(code, context)
const { onDown, onMove, onUp } = context.module.exports
const event = (pointerId, clientX, clientY = 0) => ({ pointerId, clientX, clientY, pointerType: 'touch', button: 0 })
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`)

onDown(event(1, 100))
onMove(event(1, 110))
onMove(event(1, 120))
close(view.x, -20)
onUp(event(1, 120))
Object.assign(view, { x: 0, y: 0, w: 1000, h: 1000 })
onDown(event(1, 200))
onDown(event(2, 600))
onMove(event(1, 100))
close(view.w, 800)
const afterFirstMove = { ...view }
onMove(event(1, 100))
for (const key of ['x', 'y', 'w', 'h']) close(view[key], afterFirstMove[key])
onMove(event(2, 700))
close(view.w, 1000 * 400 / 600)
onUp(event(2, 700))
onUp(event(1, 100))
console.log('Graph continuous pointer gestures passed')
