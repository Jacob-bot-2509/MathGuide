/**
 * 应用设置状态:语言 / 外观 / 字体大小 / 语音与隐私开关。
 */
import { reactive } from 'vue'

export interface AppSettings {
  language: 'zh' | 'en'
  theme: 'dark' | 'light'
  modelVoice: boolean
  albumAccess: boolean
  voiceAccess: boolean
  personalized: boolean
}

const DEFAULT_SETTINGS: AppSettings = {
  language: 'zh',
  theme: 'dark',
  modelVoice: false,
  albumAccess: false,
  voiceAccess: true,
  personalized: true,
}

const SETTINGS_KEY = 'mg-settings'

function loadSettings(): Partial<AppSettings> {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY)
    return raw ? (JSON.parse(raw) as Partial<AppSettings>) : {}
  } catch {
    return {}
  }
}

export const settingsState = reactive<AppSettings>({ ...DEFAULT_SETTINGS, ...loadSettings() })

export function updateSettings(patch: Partial<AppSettings>) {
  Object.assign(settingsState, patch)
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settingsState))
  } catch {
    /* 忽略 */
  }
  applySettings()
}

/** 把设置作用到界面:主题写入根节点 data-theme,全站 CSS 变量随之切换 */
export function applySettings() {
  document.documentElement.dataset.theme = settingsState.theme
}

applySettings()
