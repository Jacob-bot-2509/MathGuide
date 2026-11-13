/**
 * i18n 双语键自测(esbuild 打包后 node 执行)。
 *
 * 覆盖:
 *   1. ZH 与 EN 的键集合必须完全一致(少一条 = 该语言回退成 key 原文);
 *   2. 源码里 `t('x.y')` 用到的键必须在字典里(否则界面直接显示 "x.y");
 *   3. 已定义但没人用的键只告警不失败(现存 80+ 条,作为清理清单)。
 *
 * 直接读源码文本而不是 import i18n.ts:后者会拉起 settings 状态与浏览器 API。
 */
/* eslint-disable */
declare const process: { exit(code: number): void; cwd(): string }

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = process.cwd()
const I18N = join(ROOT, 'src', 'utils', 'i18n.ts')
const SRC = join(ROOT, 'src')

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

/** 键都在同一个对象字面量里:`'a.b': '...'` / `"a.b": "..."` / `'a.b': `...`` */
function keysOf(block: string): Set<string> {
  const keys = new Set<string>()
  const re = /'([A-Za-z][\w.\-]*)'\s*:\s*['"`]/g
  let match: RegExpExecArray | null
  while ((match = re.exec(block)) !== null) keys.add(match[1])
  return keys
}

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) walk(full, out)
    else if (/\.(ts|vue)$/.test(name) && !/\.d\.ts$/.test(name)) out.push(full)
  }
  return out
}

/** 只认带点的键:排除 `t('key')` 这类泛型调用(非文案)。 */
function usedKeys(): Map<string, string> {
  const used = new Map<string, string>()
  const re = /\bt\(\s*'([A-Za-z][\w.\-]*)'/g
  for (const file of walk(SRC)) {
    if (file.endsWith(join('utils', 'i18n.ts'))) continue
    const text = readFileSync(file, 'utf8')
    let match: RegExpExecArray | null
    while ((match = re.exec(text)) !== null) {
      const key = match[1]
      if (key.includes('.') && !used.has(key)) {
        used.set(key, file.slice(ROOT.length + 1))
      }
    }
  }
  return used
}

function main() {
  const text = readFileSync(I18N, 'utf8')
  const zhAt = text.indexOf('const ZH: Dict = {')
  const enAt = text.indexOf('const EN: Dict = {')
  check('i18n.ts 能定位到 ZH/EN 两个字典', zhAt >= 0 && enAt > zhAt)
  if (zhAt < 0 || enAt <= zhAt) {
    console.log(`\ni18n 自测:${passed}/${passed + failed.length} 通过`)
    for (const item of failed) console.log(`✗ ${item}`)
    process.exit(1)
  }

  const zh = keysOf(text.slice(zhAt, enAt))
  const en = keysOf(text.slice(enAt))
  check('字典解析到足够的键(>=500)', zh.size >= 500, `ZH=${zh.size}`)

  const onlyZh = [...zh].filter((key) => !en.has(key)).sort()
  const onlyEn = [...en].filter((key) => !zh.has(key)).sort()
  check('ZH 与 EN 键集合一致', onlyZh.length === 0 && onlyEn.length === 0,
    `仅 ZH ${JSON.stringify(onlyZh.slice(0, 5))} / 仅 EN ${JSON.stringify(onlyEn.slice(0, 5))}`)

  const used = usedKeys()
  const missing = [...used].filter(([key]) => !zh.has(key) || !en.has(key)).sort()
  check('源码 t() 用到的键都已定义', missing.length === 0,
    missing.slice(0, 8).map(([key, file]) => `${key} (${file})`).join('; '))

  const unused = [...zh].filter((key) => !used.has(key)).sort()
  if (unused.length) {
    console.log(`\n提示:${unused.length} 个键已定义但源码未直接引用(可清理,不阻塞):`)
    console.log('  ' + unused.slice(0, 21).join(', '))
  }

  console.log(`\ni18n 自测:${passed}/${passed + failed.length} 通过(ZH ${zh.size} 键 / 引用 ${used.size} 键)`)
  for (const item of failed) console.log(`✗ ${item}`)
  if (failed.length) process.exit(1)
}

void main()
