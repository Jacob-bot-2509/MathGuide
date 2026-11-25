/**
 * i18n 词条自测(vitest)。
 *
 * 三条断言:
 *   1. ZH 与 EN 键集合完全一致 —— 少一条,该语言就会把 key 原文显示给用户;
 *   2. 词条总数与 M3-4 拆分前一致(973)—— 防止拆文件时悄悄丢词条;
 *   3. 源码里 `t('x.y')` 用到的键必须存在 —— 防止加文案时只写模板不写词条。
 *
 * 这里直接 import 字典(纯数据、无副作用),比早期"解析源码文本"的写法可靠得多。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { en as enAccount, zh as zhAccount } from './i18n/account'
import { en as enChat, zh as zhChat } from './i18n/chat'
import { en as enCommon, zh as zhCommon } from './i18n/common'
import { en as enLearn, zh as zhLearn } from './i18n/learn'
import { en as enResearch, zh as zhResearch } from './i18n/research'

const ZH: Record<string, string> = {
  ...zhAccount,
  ...zhChat,
  ...zhCommon,
  ...zhLearn,
  ...zhResearch,
}
const EN: Record<string, string> = {
  ...enAccount,
  ...enChat,
  ...enCommon,
  ...enLearn,
  ...enResearch,
}

const SRC_DIR = fileURLToPath(new URL('..', import.meta.url))

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) {
      if (name !== 'i18n') sourceFiles(full, out)
    } else if (/\.(ts|vue)$/.test(name) && !/\.(test|d)\.ts$/.test(name)) {
      out.push(full)
    }
  }
  return out
}

describe('i18n 词条', () => {
  it('ZH 与 EN 键集合一致', () => {
    const zhKeys = Object.keys(ZH).sort()
    const enKeys = Object.keys(EN).sort()
    expect(zhKeys).toEqual(enKeys)
  })

  it('词条总数与拆分前一致(1030)', () => {
    expect(Object.keys(ZH)).toHaveLength(1030)
    expect(Object.keys(EN)).toHaveLength(1030)
  })

  it('源码 t() 引用的键都已定义', () => {
    const used = new Set<string>()
    const pattern = /\bt\(\s*'([A-Za-z][\w.-]*)'/g
    for (const file of sourceFiles(SRC_DIR)) {
      const text = readFileSync(file, 'utf8')
      let match: RegExpExecArray | null
      while ((match = pattern.exec(text)) !== null) {
        if (match[1].includes('.')) used.add(match[1])
      }
    }
    expect(used.size).toBeGreaterThan(500)
    const missing = [...used].filter((key) => !ZH[key] || !EN[key]).sort()
    expect(missing).toEqual([])
  })
})
