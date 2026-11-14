/**
 * 关于页内容结构测试。
 *
 * 这是版本号与协议正文的唯一真源:断言只针对「结构与一致性」——版本号与
 * 发布记录首位一致、日期格式合法、每条都有中英双语、协议每节都有正文。
 * 不断言长文案,避免改一句话就要改测试。
 */
import { describe, expect, it } from 'vitest'
import {
  APP_ISSUES_URL,
  APP_NAME,
  APP_RELEASES_URL,
  APP_REPO_URL,
  APP_STABLE_DATE,
  APP_STABLE_VERSION,
  APP_VERSION,
  OPEN_SOURCE,
  PRIVACY,
  PURPOSES,
  RELEASES,
  TERMS,
  type Bi,
  type LegalDoc,
} from '@/utils/aboutContent'

const VERSION_RE = /^v\d+\.\d+\.\d+$/
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

function expectBi(value: Bi, label: string) {
  expect(typeof value.zh, label).toBe('string')
  expect(typeof value.en, label).toBe('string')
  expect(value.zh.trim().length, label).toBeGreaterThan(0)
  expect(value.en.trim().length, label).toBeGreaterThan(0)
  // 中英不应是同一串(漏翻译的典型症状)
  expect(value.zh, label).not.toBe(value.en)
}

describe('应用元信息', () => {
  it('应用名与仓库地址', () => {
    expect(APP_NAME).toBe('MathGuide')
    expect(APP_REPO_URL).toMatch(/^https:\/\/github\.com\/[\w-]+\/[\w-]+$/)
    expect(APP_ISSUES_URL).toBe(`${APP_REPO_URL}/issues`)
    expect(APP_RELEASES_URL).toBe(`${APP_REPO_URL}/releases`)
  })

  it('版本号与稳定版号形态一致', () => {
    expect(APP_VERSION).toMatch(VERSION_RE)
    expect(APP_STABLE_VERSION).toMatch(VERSION_RE)
    expect(APP_STABLE_DATE).toMatch(DATE_RE)
    expect(Number.isNaN(new Date(APP_STABLE_DATE).getTime())).toBe(false)
  })
})

describe('RELEASES / 版本记录', () => {
  it('发布记录非空且版本号唯一', () => {
    expect(RELEASES.length).toBeGreaterThan(0)
    const versions = RELEASES.map((r) => r.version)
    expect(new Set(versions).size).toBe(versions.length)
    for (const version of versions) expect(version).toMatch(VERSION_RE)
  })

  it('首条就是当前版本,且只有它被标为 latest', () => {
    expect(RELEASES[0].version).toBe(APP_VERSION)
    expect(RELEASES[0].status).toBe('latest')
    expect(RELEASES[0].date).toBe(APP_STABLE_DATE)
    expect(RELEASES.filter((r) => r.status === 'latest')).toHaveLength(1)
  })

  it('稳定发布都有合法日期,开发版允许留空', () => {
    for (const release of RELEASES) {
      expect(['dev', 'latest', 'released']).toContain(release.status)
      if (release.status === 'dev') continue
      expect(release.date).toMatch(DATE_RE)
    }
  })

  it('每条记录都有双语条目', () => {
    for (const release of RELEASES) {
      expect(release.items.length, release.version).toBeGreaterThan(0)
      for (const item of release.items) expectBi(item, release.version)
    }
  })

  it('按发布日期倒序排列(新版本在前)', () => {
    const dated = RELEASES.filter((r) => r.date)
    const times = dated.map((r) => new Date(r.date).getTime())
    const sorted = [...times].sort((a, b) => b - a)
    expect(times).toEqual(sorted)
  })
})

describe('PURPOSES / 用途说明', () => {
  it('三条用途,各有图标与双语标题/描述', () => {
    expect(PURPOSES).toHaveLength(3)
    for (const purpose of PURPOSES) {
      expect(purpose.glyph.length).toBeGreaterThan(0)
      expectBi(purpose.title, 'purpose.title')
      expectBi(purpose.desc, 'purpose.desc')
    }
  })
})

describe('OPEN_SOURCE / 开源依赖', () => {
  it('每条都有名称与许可证标识', () => {
    expect(OPEN_SOURCE.length).toBeGreaterThan(0)
    for (const item of OPEN_SOURCE) {
      expect(item.name.trim().length).toBeGreaterThan(0)
      expect(item.license).toMatch(/^[A-Za-z0-9.\-+]+$/)
    }
    expect(new Set(OPEN_SOURCE.map((i) => i.name)).size).toBe(OPEN_SOURCE.length)
  })
})

describe('TERMS / PRIVACY / 协议正文结构', () => {
  const docs: Array<[string, LegalDoc]> = [['用户协议', TERMS], ['隐私政策', PRIVACY]]

  it.each(docs)('%s 有更新日期与双语前言', (_name, doc) => {
    expect(doc.updated).toMatch(DATE_RE)
    expectBi(doc.intro, 'intro')
  })

  it.each(docs)('%s 的每一节都有双语标题与至少一段正文', (_name, doc) => {
    expect(doc.sections.length).toBeGreaterThan(0)
    for (const section of doc.sections) {
      expectBi(section.title, 'section.title')
      const body = [...(section.paragraphs ?? []), ...(section.bullets ?? [])]
      expect(body.length).toBeGreaterThan(0)
      for (const block of body) expectBi(block, 'section.body')
    }
  })

  it.each(docs)('%s 的章节标题不重复', (_name, doc) => {
    const titles = doc.sections.map((s) => s.title.zh)
    expect(new Set(titles).size).toBe(titles.length)
  })

  it('协议与隐私政策不是同一份文档', () => {
    expect(TERMS.sections.map((s) => s.title.zh)).not.toEqual(PRIVACY.sections.map((s) => s.title.zh))
  })
})
