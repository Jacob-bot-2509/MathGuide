/**
 * useSpeechInput 单测(node 环境):权限/不支持/识别/点停转写/错误/卸载。
 *
 * Web Speech 在 CI 里必然不存在,这些分支平时只能人工在 Chrome 上点;
 * 这里用假 SpeechRecognition 精确制造 onresult / onend / onerror。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

const mocks = vi.hoisted(() => ({
  settings: { voiceAccess: true, language: 'zh' as 'zh' | 'en', modelVoice: false },
  updateSettings: vi.fn(),
  saveConvert: vi.fn(),
  cancelSpeechToMath: vi.fn(),
}))

vi.mock('@/stores/settings', () => ({
  settingsState: mocks.settings,
  updateSettings: mocks.updateSettings,
}))
vi.mock('@/utils/speechMath', () => ({
  beautifyMath: (text: string) => text,
  cachedConvert: () => null,
  normalizeSpeechCase: (text: string) => text,
  saveConvert: mocks.saveConvert,
  speechMathConvert: (text: string) => `[local]${text}`,
}))
vi.mock('@/services/chatService', () => ({
  speechToMath: () => ({ cancel: mocks.cancelSpeechToMath }),
}))

import { useSpeechInput } from '@/composables/useSpeechInput'
import { t } from '@/utils/i18n'

class FakeSR {
  static last: FakeSR | null = null
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((e: { results: ArrayLike<{ isFinal: boolean; length: number; [i: number]: { transcript: string } | undefined }> }) => void) | null = null
  onend: (() => void) | null = null
  onerror: ((e: { error: string }) => void) | null = null
  started = 0
  stopped = 0

  constructor() {
    FakeSR.last = this
  }

  start() { this.started += 1 }
  stop() { this.stopped += 1 }
}

function makeHarness() {
  const input = ref('')
  const toasts: string[] = []
  const api = useSpeechInput({
    input,
    autoGrow: () => {},
    toast: (message) => toasts.push(message),
  })
  return { input, toasts, api }
}

function withRecognition(ctor: unknown) {
  vi.stubGlobal('window', { SpeechRecognition: ctor })
}

beforeEach(() => {
  vi.unstubAllGlobals()
  FakeSR.last = null
  mocks.settings.voiceAccess = true
  mocks.settings.language = 'zh'
  mocks.updateSettings.mockClear()
  mocks.saveConvert.mockClear()
  mocks.cancelSpeechToMath.mockClear()
})

describe('useSpeechInput 启动条件', () => {
  it('没授予语音权限时只提示,不创建识别器', () => {
    mocks.settings.voiceAccess = false
    withRecognition(FakeSR)
    const { toasts, api } = makeHarness()

    api.toggleMic()

    expect(api.listening.value).toBe(false)
    expect(FakeSR.last).toBeNull()
    expect(toasts).toContain(t('learn.toastVoiceDenied'))
  })

  it('浏览器不支持 Web Speech 时提示(桌面 Firefox 常见)', () => {
    withRecognition(undefined)
    const { toasts, api } = makeHarness()

    api.toggleMic()

    expect(api.listening.value).toBe(false)
    expect(toasts).toContain(t('learn.toastNoSR'))
  })

  it('启动后进入听写态,语言跟随界面设置', () => {
    mocks.settings.language = 'en'
    withRecognition(FakeSR)
    const { api } = makeHarness()

    api.toggleMic()

    expect(api.listening.value).toBe(true)
    expect(FakeSR.last?.lang).toBe('en-US')
    expect(FakeSR.last?.started).toBe(1)
    expect(FakeSR.last?.continuous).toBe(true)
  })

  it('再点一次麦克风是「停止」而不是重新开始', () => {
    withRecognition(FakeSR)
    const { api } = makeHarness()
    api.toggleMic()

    api.toggleMic()

    expect(FakeSR.last?.stopped).toBe(1)
    expect(FakeSR.last?.started).toBe(1)
  })
})

describe('useSpeechInput 识别与转写', () => {
  it('识别结果按「原文本 + 已确定 + 临时」拼进输入框', () => {
    withRecognition(FakeSR)
    const { input, api } = makeHarness()
    input.value = '前缀'
    api.toggleMic()

    FakeSR.last?.onresult?.({
      results: [
        { isFinal: true, length: 1, 0: { transcript: '矩阵' } },
        { isFinal: false, length: 1, 0: { transcript: '的秩' } },
      ],
    })

    expect(input.value).toBe('前缀矩阵的秩')
  })

  it('点停后走本地速转并上屏(不依赖网络)', () => {
    withRecognition(FakeSR)
    const { input, api } = makeHarness()
    api.toggleMic()
    FakeSR.last?.onresult?.({ results: [{ isFinal: true, length: 1, 0: { transcript: '根号二' } }] })
    input.value = '根号二'

    api.toggleMic()          // 用户点停
    FakeSR.last?.onend?.()   // 识别结束

    expect(input.value).toBe('[local]根号二')
    expect(mocks.saveConvert).toHaveBeenCalled()
    expect(api.listening.value).toBe(false)
  })

  it('麦克风被拒时给出单独提示,其余错误给通用提示', () => {
    withRecognition(FakeSR)
    const { toasts, api } = makeHarness()
    api.toggleMic()

    FakeSR.last?.onerror?.({ error: 'not-allowed' })
    expect(toasts).toContain(t('learn.toastMicDenied'))
    expect(api.listening.value).toBe(false)

    FakeSR.last?.onerror?.({ error: 'network' })
    expect(toasts).toContain(t('learn.toastVoiceNetwork'))
  })

  it('aborted(用户打断)不弹错误', () => {
    withRecognition(FakeSR)
    const { toasts, api } = makeHarness()
    api.toggleMic()
    const before = toasts.length

    FakeSR.last?.onerror?.({ error: 'aborted' })

    expect(toasts.length).toBe(before)
    expect(api.listening.value).toBe(false)
  })
})

describe('useSpeechInput 卸载与模型语音开关', () => {
  it('卸载时停掉识别并取消进行中的转写', () => {
    withRecognition(FakeSR)
    const { input, api } = makeHarness()
    api.toggleMic()
    FakeSR.last?.onresult?.({ results: [{ isFinal: true, length: 1, 0: { transcript: '极限' } }] })
    input.value = '极限'
    api.toggleMic()          // 点停
    FakeSR.last?.onend?.()   // 本地速转后进入 LLM 精修(此时有进行中的转写流)

    api.dispose()

    expect(FakeSR.last?.stopped).toBe(2)
    expect(mocks.cancelSpeechToMath).toHaveBeenCalled()
  })

  it('模型语音开关落到设置里,开启时提示待开发', () => {
    withRecognition(FakeSR)
    const { toasts, api } = makeHarness()

    api.setModelVoice(true)

    expect(mocks.updateSettings).toHaveBeenCalledWith({ modelVoice: true })
    expect(toasts).toContain(t('learn.toastVoiceDev'))
  })
})
