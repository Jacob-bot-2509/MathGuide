/**
 * MathGuide AI-for-Science 设计令牌生成与安全迁移脚本
 *
 * 解决两个核心问题：
 *   A. 生成全新的 AI for Science 双主题令牌表（Observatory Slate 深色仪器盘 /
 *      Archival Preprint 温润学术论文浅色模式），同时完整保留旧变量别名
 *      （--cyan / --bg-void / --bg-card / --line 等），确保全站 51 个组件
 *      与 1079 条前端测试零破坏平滑升级。
 *   B. 仅在 <style> 块内，将绕过主题系统的硬编码语义色（#ffd166 / #ff8a8a / #7ee787）
 *      和未定义变量（var(--bg)）迁移到语义令牌。
 *
 * 默认只读预览（--dry-run），不会改写源码；显式传入标志才落盘：
 *   node scripts/migrate-science-tokens.mjs                     # 预览将被迁移的改动
 *   node scripts/migrate-science-tokens.mjs --emit-tokens       # 生成 src/styles/tokens.science.css（不覆盖原 tokens.css）
 *   node scripts/migrate-science-tokens.mjs --apply             # 执行源码 <style> 块安全替换
 *   node scripts/migrate-science-tokens.mjs --apply --replace-tokens  # 替换 src/styles/tokens.css（自动备份 .bak）
 */
import { copyFileSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
const APPLY = args.includes('--apply')
const EMIT_TOKENS = args.includes('--emit-tokens')
const REPLACE_TOKENS = args.includes('--replace-tokens')

export const SCIENCE_TOKENS_CSS = `/* ============================================================
   MathGuide AI-for-Science 设计令牌 — Observatory & Preprint
   视觉定位：精密科研仪器（深色）× 学术预印本工作台（浅色）
   设计原则：
     1. 层次靠表面明度与 1px 精密发丝线，不再使用霓虹外发光与扫描线；
     2. 语义色独立成系（主色 / 证明通过 / 引用定理 / 警示 / 错误）；
     3. 完整保留旧变量别名（--cyan / --bg-* / --glow-*），实现全站零破坏过渡。
   ============================================================ */
:root {
  /* ---------- 1. 新语义表面层（Observatory Slate 深色仪器盘） ---------- */
  --surface-0: #0b0e14;
  --surface-1: #111622;
  --surface-2: #171e2e;
  --surface-3: #1e273b;
  --surface-glass: rgba(17, 22, 34, 0.86);

  /* ---------- 2. 新语义墨色（WCAG 2.1 AA / AAA） ---------- */
  --ink-hi: #edf2f8;
  --ink: #c6d0df;
  --ink-muted: #8a97ab;

  /* ---------- 3. 科学语义强调色 ---------- */
  --accent-primary: #58b4e6;    /* 仪器钴青：主操作与焦点 */
  --accent-secondary: #4e8df5;  /* 几何深蓝：次级交互与矢量 */
  --accent-cite: #929ff8;       /* 学术靛蓝：文献引用与定理标签 */
  --accent-proof: #46c29b;      /* 验真翠绿：双模型复核通过 / 已掌握 */
  --accent-warn: #e5b34c;       /* 批注琥珀：知识缺口 / 待入库 / 弱项 */
  --accent-danger: #e86c75;     /* 证伪珊瑚红：错误与高危操作 */

  /* ---------- 4. 结构描边与精密景深 ---------- */
  --border-subtle: rgba(148, 163, 184, 0.14);
  --border-strong: rgba(88, 180, 230, 0.42);
  --shadow-sm: 0 1px 2px rgba(2, 6, 16, 0.35);
  --shadow-md: 0 8px 24px rgba(2, 6, 16, 0.42);
  --shadow-lg: 0 20px 48px rgba(2, 6, 16, 0.56);
  --focus-ring: 0 0 0 2px rgba(88, 180, 230, 0.24);

  /* ---------- 5. 三声部科学排版系统（本地字体优先，兼容严格 CSP） ---------- */
  --font-serif: "Newsreader", "Source Serif 4", "Noto Serif SC", "Songti SC", Georgia, serif;
  --font-sans: "Inter", "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, sans-serif;
  --font-mono: "JetBrains Mono", "IBM Plex Mono", "Cascadia Mono", "SF Mono", Consolas, monospace;

  /* ---------- 6. 动效节奏（克制、精密、不抢读数注意力） ---------- */
  --dur-fast: 0.16s;
  --dur-med: 0.28s;
  --dur-slow: 0.64s;
  --ease-in: cubic-bezier(0.4, 0, 1, 1);
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);

  /* ---------- 7. 兼容别名层（全站 51 个组件零破坏映射） ---------- */
  --bg-void: var(--surface-0);
  --bg-panel: var(--surface-glass);
  --bg-card: var(--surface-2);

  --cyan: var(--accent-primary);
  --blue: var(--accent-secondary);
  --violet: var(--accent-cite);
  --magenta: var(--accent-cite);
  --success: var(--accent-proof);
  --warn: var(--accent-warn);
  --danger: var(--accent-danger);

  --text-hi: var(--ink-hi);
  --text: var(--ink);
  --text-dim: var(--ink-muted);

  --line: var(--border-subtle);
  --line-bright: var(--border-strong);

  /* 将旧的霓虹外发光收敛为克制的仪器聚焦光环 */
  --glow-cyan: var(--focus-ring);
  --glow-violet: 0 0 0 2px rgba(146, 159, 248, 0.24);
  --glow-magenta: 0 0 0 2px rgba(146, 159, 248, 0.24);

  --font-ui: var(--font-sans);
  --font-tech: var(--font-mono);
}

/* ============================================================
   浅色主题：Archival Preprint（温润学术纸张，专为长时间推导与精读论文设计）
   ============================================================ */
:root[data-theme='light'] {
  --surface-0: #f6f5f0;
  --surface-1: #efede6;
  --surface-2: #ffffff;
  --surface-3: #e8e5dc;
  --surface-glass: rgba(255, 255, 255, 0.90);

  --ink-hi: #111827;
  --ink: #2b3445;
  --ink-muted: #566275;

  --accent-primary: #175c8a;    /* 普鲁士学术蓝（在白纸上对比度 > 7:1） */
  --accent-secondary: #2458b8;
  --accent-cite: #4b4fc4;
  --accent-proof: #16795a;
  --accent-warn: #a66208;
  --accent-danger: #be2b3e;

  --border-subtle: rgba(15, 23, 42, 0.10);
  --border-strong: rgba(23, 92, 138, 0.40);
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 6px 18px rgba(15, 23, 42, 0.08);
  --shadow-lg: 0 18px 40px rgba(15, 23, 42, 0.12);
  --focus-ring: 0 0 0 2px rgba(23, 92, 138, 0.20);

  --glow-cyan: var(--focus-ring);
  --glow-violet: 0 0 0 2px rgba(75, 79, 196, 0.20);
  --glow-magenta: 0 0 0 2px rgba(75, 79, 196, 0.20);
}
`

/** 仅作用于 <style> 块的安全规则（保留 rgba 透明度、不碰 JS/TS 与图形常量） */
const STYLE_RULES = [
  {
    name: '修复未定义变量 var(--bg)',
    re: /var\(\s*--bg\s*\)/g,
    replace: 'var(--bg-void)',
  },
  {
    name: '收敛硬编码警示黄 #ffd166 -> var(--warn)',
    re: /#ffd166\b/gi,
    replace: 'var(--warn)',
  },
  {
    name: '收敛硬编码浅警示黄 #f6c85f -> var(--warn)',
    re: /#f6c85f\b/gi,
    replace: 'var(--warn)',
  },
  {
    name: '收敛硬编码警示红 #ff8a8a -> var(--danger)',
    re: /#ff8a8a\b/gi,
    replace: 'var(--danger)',
  },
  {
    name: '收敛硬编码成功绿 #7ee787 -> var(--success)',
    re: /#7ee787\b/gi,
    replace: 'var(--success)',
  },
  {
    name: '收敛硬编码成功绿 #6ee7a8 -> var(--success)',
    re: /#6ee7a8\b/gi,
    replace: 'var(--success)',
  },
]

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    return entry.isDirectory() ? walk(full) : [full]
  })
}

function transformStyleBlocks(filePath, content) {
  let changes = []
  const applyRules = (block) => {
    let next = block
    for (const rule of STYLE_RULES) {
      const hits = next.match(rule.re)
      if (hits && hits.length) {
        changes.push({ rule: rule.name, count: hits.length })
        next = next.replace(rule.re, rule.replace)
      }
    }
    return next
  }

  let updated
  if (filePath.endsWith('.css')) {
    updated = applyRules(content)
  } else {
    updated = content.replace(/(<style\b[^>]*>)([\s\S]*?)(<\/style>)/g, (_m, open, body, close) => {
      return `${open}${applyRules(body)}${close}`
    })
  }
  return { updated, changes }
}

function runCli() {
  const files = walk(join(ROOT, 'src')).filter(
    (f) => /\.(vue|css)$/.test(f) && !f.endsWith('tokens.css') && !f.endsWith('tokens.science.css'),
  )

  let totalFilesTouched = 0
  let totalReplacements = 0

  console.log(`\n═══════════════════════════════════════════════════════════════`)
  console.log(`  MathGuide AI-for-Science 令牌迁移器 (${APPLY ? 'APPLY 写入模式' : 'DRY-RUN 预览模式'})`)
  console.log(`═══════════════════════════════════════════════════════════════\n`)

  for (const file of files) {
    const raw = readFileSync(file, 'utf8')
    const { updated, changes } = transformStyleBlocks(file, raw)
    if (!changes.length) continue
    totalFilesTouched++
    const rel = relative(ROOT, file).replace(/\\/g, '/')
    const count = changes.reduce((sum, c) => sum + c.count, 0)
    totalReplacements += count
    console.log(`  ${APPLY ? '✓ 已更新' : '• 待迁移'} ${rel} (${count} 处)`)
    for (const c of changes) {
      console.log(`      - ${c.rule} × ${c.count}`)
    }
    if (APPLY) {
      writeFileSync(file, updated, 'utf8')
    }
  }

  console.log(`\n汇总：涉及 ${totalFilesTouched} 个文件，共 ${totalReplacements} 处样式替换。`)

  if (EMIT_TOKENS) {
    const outPath = join(ROOT, 'src/styles/tokens.science.css')
    writeFileSync(outPath, SCIENCE_TOKENS_CSS, 'utf8')
    console.log(`✓ 已生成候选 AI-for-Science 令牌表：src/styles/tokens.science.css`)
    console.log(`  可用以下命令校验其 WCAG 对比度：`)
    console.log(`  node scripts/ui-design-audit.mjs --tokens src/styles/tokens.science.css`)
  }

  if (APPLY && REPLACE_TOKENS) {
    const target = join(ROOT, 'src/styles/tokens.css')
    const backup = join(ROOT, 'src/styles/tokens.css.bak')
    copyFileSync(target, backup)
    writeFileSync(target, SCIENCE_TOKENS_CSS, 'utf8')
    console.log(`✓ 已备份旧令牌到 src/styles/tokens.css.bak 并写入新 AI-for-Science 令牌表`)
  }

  if (!APPLY && !EMIT_TOKENS) {
    console.log(`\n提示：当前为只读预览。可执行：`)
    console.log(`  node scripts/migrate-science-tokens.mjs --emit-tokens   # 先生成候选令牌文件`)
    console.log(`  node scripts/migrate-science-tokens.mjs --apply         # 仅迁移硬编码语义色与未定义变量`)
  }
  console.log('')
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url).toLowerCase() === resolve(process.argv[1]).toLowerCase()
if (isMain) runCli()
