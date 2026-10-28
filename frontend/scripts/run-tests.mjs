/**
 * 前端自测统一入口:`npm test`。
 *
 * 每个脚本都是「esbuild 打包 → node 执行」的轻量测试,不引入测试框架:
 *   - 语音数学编译器(纯函数)
 *   - SSE 收尾契约(postSSE)
 *   - MathText 公式渲染 + 链接/转义安全(Vite SSR 真实渲染)
 *   - 回收站/本地数据/会话持久化
 *   - 待办清单时间与状态规则
 *   - 关于 MG 的版本记录与协议正文双语完整性
 *   - 账号导出:token 与内部标记不落进导出文件
 *
 * 每个套件跑完都清理生成的临时 bundle,避免污染工作区。
 */
import { execSync } from 'node:child_process'
import { rmSync } from 'node:fs'

const CASES = [
  {
    name: '语音数学编译器',
    bundle: 'npx esbuild scripts/speech-math-test.ts --bundle --format=cjs --outfile=.speech-math-test.cjs',
    run: 'node .speech-math-test.cjs',
    artifact: '.speech-math-test.cjs',
  },
  {
    name: 'SSE 收尾契约',
    bundle: 'npx esbuild scripts/sse-stream-test.ts --bundle --format=cjs --define:import.meta.env={} --outfile=.sse-stream-test.cjs',
    run: 'node .sse-stream-test.cjs',
    artifact: '.sse-stream-test.cjs',
  },
  {
    name: 'MathText 渲染与链接安全',
    bundle: 'npx esbuild scripts/math-text-test.ts --bundle --format=cjs --platform=node --external:vite --external:vue --external:vue/server-renderer --outfile=.math-text-test.cjs',
    run: 'node .math-text-test.cjs',
    artifact: '.math-text-test.cjs',
  },
  {
    name: '回收站/本地数据/会话持久化',
    bundle: 'npx esbuild scripts/trash-store-test.ts --bundle --format=cjs --platform=node --outfile=.trash-store-test.cjs',
    run: 'node .trash-store-test.cjs',
    artifact: '.trash-store-test.cjs',
  },
  {
    name: '待办清单时间/状态',
    bundle: 'npx esbuild scripts/todo-test.ts --bundle --format=cjs --platform=node --outfile=.todo-test.cjs',
    run: 'node .todo-test.cjs',
    artifact: '.todo-test.cjs',
  },
  {
    name: '知识图谱分层布局',
    bundle: 'npx esbuild scripts/graph-layout-test.ts --bundle --format=cjs --outfile=.graph-layout-test.cjs',
    run: 'node .graph-layout-test.cjs',
    artifact: '.graph-layout-test.cjs',
  },
  {
    name: '关于 MG 内容完整性',
    bundle: 'npx esbuild scripts/about-content-test.ts --bundle --format=cjs --platform=node --outfile=.about-content-test.cjs',
    run: 'node .about-content-test.cjs',
    artifact: '.about-content-test.cjs',
  },
  {
    name: '账号导出本机数据',
    bundle: 'npx esbuild scripts/account-export-test.ts --bundle --format=cjs --platform=node --define:import.meta.env={} --outfile=.account-export-test.cjs',
    run: 'node .account-export-test.cjs',
    artifact: '.account-export-test.cjs',
  },
]

let failed = 0
for (const testCase of CASES) {
  console.log(`\n=== ${testCase.name} ===`)
  try {
    execSync(testCase.bundle, { stdio: 'inherit' })
    execSync(testCase.run, { stdio: 'inherit' })
  } catch {
    failed++
    console.error(`✗ ${testCase.name} 失败`)
  } finally {
    try {
      rmSync(testCase.artifact, { force: true })
    } catch {
      /* 清理失败不影响测试结论 */
    }
  }
}

if (failed > 0) {
  console.error(`\n${failed} 个测试套件失败`)
  process.exit(1)
}
console.log('\n全部前端自测通过 ✅')
