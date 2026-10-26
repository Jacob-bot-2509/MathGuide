/**
 * 关于 MG 内容自测:版本记录、用途项与协议正文的中英双语完整性。
 *
 * 目的不是校验文案措辞,而是防止新增条目时漏掉英文或漏写正文,
 * 导致界面回退成 i18n key 或出现空白段落。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import {
  APP_STABLE_VERSION,
  APP_VERSION,
  OPEN_SOURCE,
  PRIVACY,
  PURPOSES,
  RELEASES,
  TERMS,
  type Bi,
  type LegalDoc,
} from '../src/utils/aboutContent'

let passed = 0
const failed: string[] = []

function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

function hasText(value: unknown): boolean {
  return typeof value === 'string' && value.trim().length > 0
}

function biOk(value: Bi, label: string): boolean {
  const ok = !!value && hasText(value.zh) && hasText(value.en)
  check(label, ok)
  return ok
}

function legalOk(doc: LegalDoc, label: string) {
  check(`${label} 有更新日期`, /^\d{4}-\d{2}-\d{2}$/.test(doc.updated), doc.updated)
  biOk(doc.intro, `${label} 导语双语`)
  check(`${label} 至少有一节`, doc.sections.length > 0)
  doc.sections.forEach((section, index) => {
    biOk(section.title, `${label} 第 ${index + 1} 节标题双语`)
    const body = [...(section.paragraphs ?? []), ...(section.bullets ?? [])]
    check(`${label} 第 ${index + 1} 节有正文`, body.length > 0)
    body.forEach((item, bodyIndex) => {
      biOk(item, `${label} 第 ${index + 1} 节第 ${bodyIndex + 1} 条双语`)
    })
  })
}

const versionPattern = /^v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?$/
check('当前版本号格式', versionPattern.test(APP_VERSION), APP_VERSION)
check('稳定版号格式', versionPattern.test(APP_STABLE_VERSION), APP_STABLE_VERSION)
check('稳定版有发布说明', RELEASES.some((release) => release.version === APP_STABLE_VERSION))
check('版本号唯一', new Set(RELEASES.map((release) => release.version)).size === RELEASES.length)
check('只有一个 latest', RELEASES.filter((release) => release.status === 'latest').length === 1)

RELEASES.forEach((release) => {
  check(`${release.version} 有更新条目`, release.items.length > 0)
  check(
    `${release.version} 日期与状态一致`,
    release.status === 'dev' ? release.date === '' : /^\d{4}-\d{2}-\d{2}$/.test(release.date),
    release.date,
  )
  release.items.forEach((item, index) => {
    biOk(item, `${release.version} 第 ${index + 1} 条双语`)
  })
})

PURPOSES.forEach((purpose, index) => {
  check(`用途 ${index + 1} 有符号`, hasText(purpose.glyph))
  biOk(purpose.title, `用途 ${index + 1} 标题双语`)
  biOk(purpose.desc, `用途 ${index + 1} 描述双语`)
})

OPEN_SOURCE.forEach((item) => {
  check(`开源项目 ${item.name} 有许可证`, hasText(item.name) && hasText(item.license))
})

legalOk(TERMS, '服务协议')
legalOk(PRIVACY, '隐私政策')

// 隐私政策必须覆盖用户最关心的四类去向,避免改版时被误删。
const privacyText = JSON.stringify(PRIVACY)
for (const keyword of ['大模型服务', '检索平台', 'localStorage', 'backend/data']) {
  check(`隐私政策包含「${keyword}」`, privacyText.includes(keyword))
}

if (failed.length) {
  console.error(`关于 MG 内容自测:${passed}/${passed + failed.length} 通过`)
  failed.forEach((item) => console.error(`  ✗ ${item}`))
  process.exit(1)
}
console.log(`关于 MG 内容自测:${passed}/${passed} 通过`)
