import { fitSegments, residualSegments } from '../src/utils/regressionChart'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean) {
  if (ok) passed++
  else failed.push(name)
}

const result = {
  points: [
    { row: 0, x: 1, actual: 2, fitted: 2.2, residual: -0.2 },
    { row: 1, x: 2, actual: 4, fitted: 3.8, residual: 0.2 },
  ],
  fitCurve: [{ x: 1, y: 2.2 }, { x: 2, y: 3.8 }],
} as never

check('fit curve returns one segment', fitSegments(result).length === 1)
check('residuals keep two points', residualSegments(result).length === 2)

if (failed.length) {
  console.error(`FAIL ${failed.length}: ${failed.join(', ')}`)
  process.exit(1)
}
console.log(`regression chart: ${passed} passed`)
