import assert from 'node:assert/strict'
import { chapterLabel, displayName, matchesGraphNode, wrapGraphLabel, graphViewBounds, initialGraphView } from '../src/utils/graphLabels'

const node = { id: 'derivative-def', name: '导数的定义', nameEn: 'Definition of the Derivative', chapter: '导数与微分' }
assert.equal(displayName(node, 'en'), 'Definition of the Derivative')
assert.equal(displayName({ ...node, nameEn: '' }, 'en'), node.name)
assert.equal(displayName(node, 'zh'), node.name)
assert(matchesGraphNode(node, 'Derivative'))
assert(matchesGraphNode(node, '导数'))
assert.equal(chapterLabel(node.chapter, 'en', { [node.chapter]: 'Derivatives and Differentials' }), 'Derivatives and Differentials')
assert.equal(chapterLabel(node.chapter, 'en'), node.chapter)
assert.equal(chapterLabel(node.chapter, 'zh', { [node.chapter]: 'Derivatives and Differentials' }), node.chapter)
for (const aspect of [1256 / 700, 375 / 700]) {
  const points = [{ x: 69, y: 69 }, { x: 1000, y: 600 }]
  const bounds = graphViewBounds(points, aspect)
  assert(bounds.x <= 69 - 98 && bounds.y <= 69 - 38)
  assert(bounds.x + bounds.w >= 1000 + 98 && bounds.y + bounds.h >= 600 + 38)
}
const narrowPoints = [{ x: 69, y: 69 }, { x: 1000, y: 600 }]
const desktop = initialGraphView(narrowPoints, 1256 / 700, 1256, false)
assert(desktop.x <= 69 - 98 && desktop.x + desktop.w >= 1000 + 98)
const mobile = initialGraphView(narrowPoints, 375 / 400, 375, true)
assert(mobile.w <= 600)
assert(Math.abs(mobile.w - 375 * 1.5625) < 1e-6)
assert(12.5 * 375 / mobile.w >= 8)
const mobileBounds = graphViewBounds(narrowPoints, 375 / 400)
assert(mobile.x >= mobileBounds.x && mobile.x + mobile.w <= mobileBounds.x + mobileBounds.w + 1e-6)
assert(Math.abs(mobile.x + mobile.w / 2 - (mobileBounds.x + mobileBounds.w / 2)) < 1e-6)
// 手机/平板各种宽度:初始视野始终保证节点标签 ≥8px
for (const width of [320, 360, 375, 390, 414, 430, 768, 844, 1024]) {
  const phone = initialGraphView(narrowPoints, width / 640, width, true)
  assert(phone.w <= width * 1.5625 + 1e-6)
  assert(12.5 * width / phone.w >= 8 - 1e-9)
}
// 内容范围小于最小画布宽度时,窄屏仍按最小可读缩放收窄
const tiny = initialGraphView([{ x: 69, y: 69 }, { x: 80, y: 80 }], 375 / 400, 375, true)
assert.equal(tiny.w, 375 * 1.5625)
// Fit(全图)不受最小可读缩放限制
const full = initialGraphView(narrowPoints, 375 / 400, 375, true, true)
assert(full.x <= 69 - 98 && full.x + full.w >= 1000 + 98)
const measure = (value: string) => Array.from(value).length * 10
const lines = wrapGraphLabel('A very long mathematical expression and its properties', measure, 100)
assert.equal(lines.length, 2)
assert(lines[1].endsWith('…'))
assert(lines.every(line => measure(line) <= 100))
