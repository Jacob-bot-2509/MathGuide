import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

/**
 * 前端单测(vitest)。
 *
 * 与 `scripts/run-tests.mjs` 那套「esbuild 打包 + node 断言」并行存在:
 * 老脚本继续跑(它们覆盖的是纯函数与打包契约,迁移成本不划算),
 * 新测试一律写在这里 —— 有 watch、有断言库、有覆盖率,还能直接测组件。
 *
 * 环境默认 node:被测模块要么是纯 TS,要么自己 stub 了 localStorage/fetch。
 * 需要 DOM 的组件测试在文件头写 `// @vitest-environment happy-dom`,
 * 用 `@vue/test-utils` 的 shallowMount 挂载,子组件全走桩,不拉渲染引擎。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      include: ['src/services/**/*.ts', 'src/stores/**/*.ts', 'src/utils/**/*.ts'],
      exclude: ['**/*.test.ts'],
      /**
       * 门槛只做两件事:防倒退 + 把 COVERAGE_PLAN §2 的"按文件定线"搬进 CI。
       * 全局值比现状(97.7 / 92.3 / 97.8 / 99.0)留了余量,避免一次无害重构就红;
       * 分组 glob 则按类别线硬卡,单个文件掉队会直接失败。
       */
      thresholds: {
        statements: 90,
        branches: 85,
        functions: 90,
        lines: 95,
        // U 类 · utils 纯函数
        'src/utils/**': { statements: 80, lines: 80 },
        // S 类 · stores 状态与持久化
        'src/stores/**': { statements: 70, lines: 70 },
        // V 类 · services 接口层
        'src/services/**': { statements: 60, lines: 60 },
      },
    },
  },
})
