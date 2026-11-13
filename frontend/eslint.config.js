/**
 * ESLint 9+ flat config。
 *
 * 刻意**不用** `pluginVue.configs['flat/recommended']`:那套预设以排版规则为主,
 * 在 v1.25.0 的 105 个源码文件上会一次产生上千条告警,等于让 CI 长红。
 * 现阶段只开「正确性」类规则;排版交给 prettier,存量文件随后续重构逐步收紧。
 */
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      '*.cjs',
      // 自测/审计脚本不是产品代码,由 scripts/run-tests.mjs 自己管
      'scripts/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
  },
  {
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser, ...globals.es2022 },
    },
    rules: {
      // ---- 与现有代码风格对齐:放宽容易误报的默认项 ----
      'no-empty': ['error', { allowEmptyCatch: true }],
      'no-constant-condition': ['error', { checkLoops: false }],
      // 中文界面文案里有意使用全角空格/不换行空格
      'no-irregular-whitespace': [
        'error',
        { skipStrings: true, skipComments: true, skipRegExps: true, skipTemplates: true },
      ],
      // 语音数学转写需要匹配 \\x00 等控制字符
      'no-control-regex': 'off',
      // 正则里的多余转义多为可读性选择(如 \\(、\\[),不强制删除
      'no-useless-escape': 'off',
      // eslint 10 新增:对「赋值后未读」的误报在 try/catch 兜底写法里较多
      'no-useless-assignment': 'off',
      // 日志只允许 warn/error(排查用),console.log 不进产品代码
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // 下划线前缀表示「有意不用」,与后端约定一致
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      // 现有代码大量使用 any 兜住第三方类型,先不拦;新增代码靠 review
      '@typescript-eslint/no-explicit-any': 'off',
      // 排版类:交给 prettier,不在此处制造噪音
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-self-closing': 'off',
      'vue/attributes-order': 'off',
      'vue/html-indent': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      // 组件名已由路由/目录表达(HomeView 等),无需再拦
      'vue/multi-word-component-names': 'off',
    },
  },
]
