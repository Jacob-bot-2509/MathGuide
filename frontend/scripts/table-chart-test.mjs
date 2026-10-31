import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from 'vue/server-renderer'

const server = await createServer({
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
  optimizeDeps: { noDiscovery: true },
})
try {
  const { default: Chart } = await server.ssrLoadModule('/src/components/research/TableChart.vue')
  const render = (chartType, values, xValues = null) => renderToString(h(Chart, {
    labels: ['1', '2', '3'], series: [{ key: 'A', label: 'A', values }], chartType, xValues,
  }))
  const count = (html, tag) => (html.match(new RegExp(`<${tag}\\b`, 'g')) || []).length

  const gap = await render('line', [1, null, 3])
  assert.equal(count(gap, 'polyline'), 2, 'missing Y must break the line')
  assert.equal(count(gap, 'circle'), 2)
  for (const type of ['line', 'scatter']) {
    const missingX = await render(type, [1, 2, 3], [100, null, 300])
    assert.equal(count(missingX, 'circle'), 2, `${type} must omit missing X`)
    const xs = [...missingX.matchAll(/<circle[^>]* cx="([^"]+)"/g)].map((m) => Number(m[1]))
    assert.deepEqual(xs, [62, 742], `${type} must scale from real X values`)
    if (type === 'line') assert.equal(count(missingX, 'polyline'), 2, 'missing X must break the line')
  }
  const bar = await render('bar', [1, 2, 3], [100, null, 300])
  assert.equal((bar.match(/opacity="0\.82"/g) || []).length, 2, 'bars must omit missing X')
  const noX = await render('scatter', [1, 2, 3], [null, null, null])
  assert.equal(count(noX, 'circle'), 0, 'all missing X values must not become row numbers')
  console.log('TableChart gap and missing-X tests passed')
} finally {
  await server.close()
}
