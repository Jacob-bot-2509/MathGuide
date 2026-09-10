/**
 * 语音数学本地编译器自测(前端无运行时,经 esbuild 打包后用 node 执行):
 *   npx esbuild scripts/speech-math-test.ts --bundle --format=cjs --outfile=.speech-math-test.cjs && node .speech-math-test.cjs
 * 新增规则时同步在 src/utils/speechMath.ts 的 SELF_TESTS 补用例。
 */
import { SELF_TESTS, speechMathConvert } from '../src/utils/speechMath'

let passed = 0
const failed: string[] = []
for (const [input, expect] of SELF_TESTS) {
  const got = speechMathConvert(input)
  if (got === expect) {
    passed++
  } else {
    failed.push(`✗ ${input}\n    期望: ${expect}\n    实际: ${got}`)
  }
}
console.log(`\n命中 ${passed}/${SELF_TESTS.length}`)
if (failed.length) {
  console.log(failed.join('\n'))
  process.exit(1)
} else {
  console.log('全部通过 ✅')
}
