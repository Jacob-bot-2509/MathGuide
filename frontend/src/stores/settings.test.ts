// @vitest-environment happy-dom
/**
 * 应用设置 store 测试。
 *
 * 设置同时承担「持久化」与「作用到界面」:词条语言、主题 data-theme 都从这里来。
 * 读坏必须回到默认值(en 才不会变成 undefined 让 t() 崩),主题必须真正写进 DOM。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const KEY = 'mg-settings'
const memory = new Map<string, string>()
let failWrites = false

function installStorage() {
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => memory.get(key) ?? null,
    setItem: (key: string, value: string) => {
      if (failWrites) throw new Error('QuotaExceededError')
      memory.set(key, String(value))
    },
    removeItem: (key: string) => {
      memory.delete(key)
    },
    clear: () => memory.clear(),
    key: (index: number) => [...memory.keys()][index] ?? null,
    get length() {
      return memory.size
    },
  })
}

beforeEach(() => {
  memory.clear()
  failWrites = false
  vi.resetModules()
  vi.unstubAllGlobals()
  installStorage()
  document.documentElement.removeAttribute('data-theme')
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('默认值', () => {
  it('没有存档时使用默认设置', async () => {
    const settings = await import('@/stores/settings')
    expect(settings.settingsState).toMatchObject({
      language: 'zh',
      theme: 'dark',
      modelVoice: false,
      albumAccess: false,
      voiceAccess: true,
      personalized: true,
      researchSearchMode: 'split',
    })
  })

  it('导入时把主题作用到根节点', async () => {
    memory.set(KEY, JSON.stringify({ theme: 'light' }))
    await import('@/stores/settings')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('脏 JSON 回退默认值,不抛错', async () => {
    memory.set(KEY, '{oops')
    const settings = await import('@/stores/settings')
    expect(settings.settingsState.language).toBe('zh')
    expect(settings.settingsState.theme).toBe('dark')
  })

  it('存档只覆盖提供的字段(逐字段合并)', async () => {
    memory.set(KEY, JSON.stringify({ language: 'en' }))
    const settings = await import('@/stores/settings')
    expect(settings.settingsState.language).toBe('en')
    expect(settings.settingsState.theme).toBe('dark') // 未提供的保持默认
    expect(settings.settingsState.voiceAccess).toBe(true)
  })
})

describe('updateSettings', () => {
  it('内存、localStorage 与 DOM 三处同步', async () => {
    const settings = await import('@/stores/settings')

    settings.updateSettings({ theme: 'light', language: 'en' })

    expect(settings.settingsState.theme).toBe('light')
    expect(settings.settingsState.language).toBe('en')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(JSON.parse(memory.get(KEY) ?? '{}')).toMatchObject({ theme: 'light', language: 'en' })
  })

  it('局部更新不影响其他字段', async () => {
    const settings = await import('@/stores/settings')
    settings.updateSettings({ personalized: false })
    expect(settings.settingsState).toMatchObject({
      personalized: false,
      theme: 'dark',
      researchSearchMode: 'split',
    })
  })

  it('写盘失败时界面仍然切换(仅本次会话有效)', async () => {
    const settings = await import('@/stores/settings')
    failWrites = true
    expect(() => settings.updateSettings({ researchSearchMode: 'page' })).not.toThrow()
    expect(settings.settingsState.researchSearchMode).toBe('page')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('applySettings 可单独调用(主题从当前状态同步)', async () => {
    const settings = await import('@/stores/settings')
    settings.settingsState.theme = 'light'
    settings.applySettings()
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
