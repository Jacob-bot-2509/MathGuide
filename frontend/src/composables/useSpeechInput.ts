/** 语音输入:浏览器本地识别 + 「点停即转写」的四档编排。
 *
 * 优先 Web Speech;浏览器没有 API 或 Google 语音服务不可达(network)时,
 * 自动切到 MediaRecorder → 16kHz WAV → 后端 /api/speech/transcribe。
 * 后台 ASR 默认智谱 glm-asr-2512,可用 MG_ASR_PROVIDER=qwen 切 Qwen Omni。
 *
 * 从 ChatWorkspace 抽出的原因:这一块是自带状态机的独立子系统(识别会话、预热定时器、
 * 转写流序号、输入框回滚),与对话/会话模型无关,却占了组件近 240 行。
 *
 * 四档转写(见 toggleMic 里 onend 的注释):
 * ① 缓存有精修结果 → 直接上屏;② 说话期间预热已完成 → 用 LLM 结果;
 * ③ 否则本地编译器 0ms 出符号;④ LLM 后台精修无感覆盖。
 *
 * 依赖:输入框(读写)与自动增高由调用方注入;设置项直接读全局 settings store。
 */
import { ref, type Ref } from 'vue'
import {
  beautifyMath,
  cachedConvert,
  normalizeSpeechCase,
  saveConvert,
  speechMathConvert,
} from '@/utils/speechMath'
import { settingsState, updateSettings } from '@/stores/settings'
import { speechToMath, transcribeSpeech } from '@/services/chatService'
import { blobToBase64, blobToWav } from '@/utils/wav'
import { t } from '@/utils/i18n'

/* Web Speech API:results 里的每一项(SpeechRecognitionResult)只有 isFinal,
   识别文本在首个候选上(r[0].transcript)——项本身没有 transcript 属性,
   直接读会得到 undefined 拼进输入框 */
interface SRResult {
  isFinal: boolean
  length: number
  [i: number]: { transcript: string } | undefined
}

interface ISpeechRecognition {
  lang: string
  interimResults: boolean
  /** 持续听写:一句话说完不自动停止,由用户点麦克风结束(长段口述更稳) */
  continuous: boolean
  onresult: ((e: { results: ArrayLike<SRResult> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  start(): void
  stop(): void
}

type SRConstructor = new () => ISpeechRecognition

function getSR(): SRConstructor | null {
  const w = window as unknown as {
    SpeechRecognition?: SRConstructor
    webkitSpeechRecognition?: SRConstructor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export interface SpeechInputDeps {
  /** 识别结果直接写进输入框;转写结果也回写到这里 */
  input: Ref<string>
  /** 输入框随内容增高 */
  autoGrow: () => void
  toast: (message: string, durationMs?: number) => void
}

export function useSpeechInput(deps: SpeechInputDeps) {
  const listening = ref(false)
  let sr: ISpeechRecognition | null = null
  let srBaseText = ''
  let srStopToConvert = false // 用户主动点停 → 结束后自动转写数学符号
  let recorder: MediaRecorder | null = null
  let recorderStream: MediaStream | null = null
  let recorderTimer: ReturnType<typeof setTimeout> | null = null
  let recorderMime = ''
  let recorderStarting = false
  let recorderSeq = 0
  const RECORD_MAX_MS = 29_000

  /* 转写提速编排:说话中后台预热(停顿 800ms 起转,结果攒着不打扰输入框)+
     点停 0ms 本地速转先出符号 + LLM 精修流式覆盖;seq 保证新旧转换互不干扰 */
  let convSeq = 0
  let convCancel: (() => void) | null = null
  let convAcc = '' // 当前流累计结果
  let convRaw = '' // 当前流对应的原文
  let convLive = false // 是否把流式结果显示到输入框
  let convWarmDone = false
  let convDebounce: ReturnType<typeof setTimeout> | null = null

  function cancelConvert() {
    convSeq += 1
    convCancel?.()
    convCancel = null
    convLive = false
  }

  function startConvert(raw: string, live: boolean) {
    if (!raw.trim()) return
    cancelConvert()
    convRaw = raw
    convLive = live
    convAcc = ''
    const seq = convSeq
    // 本次转换开始前的输入框内容(live 模式下通常是本地速转结果):
    // 流式覆盖后若模型半途失败,要能撤回到它,而不是把半截转写留在输入框里
    const fallbackText = deps.input.value
    // 先本地归一大小写(ASR 大小写是噪声,不刻意念"大"一律小写),
    // 再交 LLM 按数学惯例自动判别(矩阵 A/随机变量 X 等该大写则大写)
    convCancel = speechToMath(normalizeSpeechCase(raw), {
      onDelta: (full) => {
        if (seq !== convSeq) return
        convAcc = full
        if (convLive) {
          // 输入框是纯文本:把模型可能输出的 ^/_、LaTeX 记号美化为 Unicode 直读形式
          const pretty = beautifyMath(full)
          if (pretty !== deps.input.value) {
            deps.input.value = pretty
            deps.autoGrow()
          }
        }
      },
      onDone: (full) => {
        if (seq !== convSeq) return
        saveConvert(raw, beautifyMath(full), 'llm') // 精修结果(美化后)入缓存:同句再念零请求
      },
      onFail: () => {
        if (seq !== convSeq) return
        // 撤回本次流式覆盖;用户中途手改过输入框则不动,避免吞掉编辑
        if (convLive && deps.input.value === beautifyMath(convAcc)) {
          deps.input.value = fallbackText
          deps.autoGrow()
        }
        if (!listening.value) deps.toast(t('learn.toastConvertFail'))
      },
    }).cancel
  }

  /** 识别/转写完成后的四档上屏;Web Speech 与录音兜底共用。 */
  function finalizeSpeech(raw: string): void {
    if (!raw.trim() || raw === srBaseText) return
    const cached = cachedConvert(raw)
    if (cached && cached.source === 'llm') {
      deps.input.value = cached.text
      deps.autoGrow()
    } else if (convRaw === raw && convAcc) {
      convLive = true
      // 与①③④同一口径:预热流是 LLM 原始输出(可能含 ^_{}、LaTeX 记号),
      // 漏掉美化会让同一句话因走哪条路径而长得不一样
      deps.input.value = beautifyMath(convAcc)
      deps.autoGrow()
    } else {
      const local = cached?.text ?? speechMathConvert(raw)
      if (!cached) saveConvert(raw, local, 'local')
      deps.input.value = local
      deps.autoGrow()
      startConvert(raw, true)
    }
  }

  function cleanupRecorder(): void {
    if (recorderTimer) {
      clearTimeout(recorderTimer)
      recorderTimer = null
    }
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      if (recorder.state !== 'inactive') {
        try { recorder.stop() } catch { /* already stopped */ }
      }
      recorder = null
    }
    recorderStream?.getTracks().forEach((track) => track.stop())
    recorderStream = null
    recorderStarting = false
  }

  function pickRecorderMime(Recorder: typeof MediaRecorder): string {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
    ]
    for (const type of candidates) {
      if (typeof Recorder.isTypeSupported !== 'function' || Recorder.isTypeSupported(type)) {
        return type
      }
    }
    return ''
  }

  async function finishRecording(chunks: Blob[], mime: string, seq: number, base: string): Promise<void> {
    if (seq !== recorderSeq) return
    listening.value = false
    cleanupRecorder()
    const blob = new Blob(chunks, { type: mime || 'audio/webm' })
    if (!blob.size) return
    try {
      const wav = await blobToWav(blob)
      if (seq !== recorderSeq) return
      if (wav.size > 1_600_000) {
        deps.toast(t('learn.toastTranscribeFail'), 5000)
        return
      }
      const audio = await blobToBase64(wav)
      if (seq !== recorderSeq) return
      const language = settingsState.language === 'en' ? 'en' : 'zh'
      const { text } = await transcribeSpeech(audio, 'wav', language)
      if (seq !== recorderSeq) return
      if (!text.trim()) {
        deps.toast(t('learn.toastNoVoice'))
        return
      }
      if (deps.input.value !== base) {
        deps.input.value += text
        deps.autoGrow()
        return
      }
      deps.input.value = base + text
      deps.autoGrow()
      finalizeSpeech(deps.input.value)
    } catch {
      if (seq === recorderSeq) deps.toast(t('learn.toastTranscribeFail'), 5000)
    }
  }

  /** 浏览器没有 Web Speech 时的兜底:MediaRecorder → WAV → 后端 ASR。 */
  async function startRecorder(): Promise<void> {
    if (recorderStarting) return
    const Recorder = (window as unknown as { MediaRecorder?: typeof MediaRecorder }).MediaRecorder
    if (!Recorder || !navigator.mediaDevices?.getUserMedia) {
      deps.toast(t('learn.toastNoSR'))
      return
    }
    const seq = ++recorderSeq
    recorderStarting = true
    // 先点亮麦克风:getUserMedia 的权限弹窗/系统响应可能很慢,
    // 原先要等它 resolve 才改 listening,用户会以为按钮没反应。
    listening.value = true
    deps.toast(t('learn.listening'), 1500)
    let request: Promise<MediaStream> | null = null
    let timeout: ReturnType<typeof setTimeout> | undefined
    try {
      request = navigator.mediaDevices.getUserMedia({ audio: true })
      const stream = await Promise.race([
        request,
        new Promise<never>((_, reject) => {
          timeout = setTimeout(() => reject(new Error('microphone timeout')), 8000)
        }),
      ])
      if (seq !== recorderSeq) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      recorderStream = stream
      recorderMime = pickRecorderMime(Recorder)
      recorder = new Recorder(stream, recorderMime ? { mimeType: recorderMime } : undefined)
      const chunks: Blob[] = []
      const mime = recorderMime
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data)
      }
      recorder.onerror = () => {
        listening.value = false
        cleanupRecorder()
        deps.toast(t('learn.toastNoVoice'))
      }
      const base = deps.input.value
      recorder.onstop = () => { void finishRecording(chunks, mime, seq, base) }
      srBaseText = base
      cancelConvert()
      recorder.start()
      listening.value = true
      recorderTimer = setTimeout(() => {
        if (recorder?.state === 'recording') recorder.stop()
      }, RECORD_MAX_MS)
    } catch (err) {
      // 超时后 getUserMedia 仍可能晚到:拿到后立刻关掉,不让麦克风在后台常亮
      void request?.then((stream) => {
        stream.getTracks().forEach((track) => track.stop())
      }).catch(() => {})
      if (seq !== recorderSeq) return
      cleanupRecorder()
      listening.value = false
      const name = (err as { name?: string } | null)?.name
      deps.toast(
        name === 'NotAllowedError' || name === 'SecurityError'
          ? t('learn.toastMicDenied')
          : t('learn.toastNoVoice'),
        4000,
      )
    } finally {
      if (timeout) clearTimeout(timeout)
      if (seq === recorderSeq) recorderStarting = false
    }
  }

  function toggleMic() {
    if (recorderStarting) {
      recorderSeq += 1
      cleanupRecorder()
      listening.value = false
      return
    }
    if (listening.value) {
      if (recorder) {
        try { recorder.stop() } catch { /* already stopped */ }
        return
      }
      srStopToConvert = true
      sr?.stop()
      return
    }
    if (!settingsState.voiceAccess) {
      deps.toast(t('learn.toastVoiceDenied'))
      return
    }
    // Web Speech API 只在安全上下文可用;HTTP 局域网下权限可能显示已允许,
    // 但识别器拿不到音频。先给明确原因,别让用户以为是麦克风坏了。
    if (!window.isSecureContext) {
      deps.toast(t('learn.toastVoiceInsecure'), 6000)
      return
    }
    recorderSeq += 1
    const Ctor = getSR()
    if (!Ctor) {
      void startRecorder()
      return
    }
    sr = new Ctor()
    const recognition = sr
    sr.lang = settingsState.language === 'en' ? 'en-US' : 'zh-CN'
    sr.interimResults = true
    sr.continuous = true
    srBaseText = deps.input.value
    convWarmDone = false
    cancelConvert() // 清理上一次语音遗留的转写流
    sr.onresult = (e) => {
      if (sr !== recognition) return
      let final = ''
      let interim = ''
      for (let i = 0; i < e.results.length; i++) {
        const r = e.results[i]
        // 识别文本在首个候选 r[0].transcript 上
        const text = r[0]?.transcript ?? ''
        if (!text) continue
        if (r.isFinal) final += text
        else interim += text
      }
      deps.input.value = srBaseText + final + interim
      deps.autoGrow()
      // 后台预热:停顿 800ms 后把当前文本拿去转写(结果先攒着,点停即展示)
      if (convDebounce) clearTimeout(convDebounce)
      convDebounce = setTimeout(() => {
        convDebounce = null
        if (listening.value && !convWarmDone) {
          convWarmDone = true
          startConvert(deps.input.value, false)
        }
      }, 800)
    }
    sr.onend = () => {
      if (sr !== recognition) return
      listening.value = false
      if (convDebounce) {
        clearTimeout(convDebounce)
        convDebounce = null
      }
      // 用户主动点停且有新识别内容 → 转写四档:
      // ① 缓存里有精修结果 → 直接上屏,零网络;
      // ② 说话期间预热已完成 → 直接上屏 LLM 结果;
      // ③ 否则本地编译器 0ms 出符号上屏;
      // ④ LLM 后台精修无感覆盖(结果回写缓存)。
      if (srStopToConvert) {
        srStopToConvert = false
        finalizeSpeech(deps.input.value)
      }
    }
    sr.onerror = (e) => {
      if (sr !== recognition) return
      listening.value = false
      if (e.error === 'aborted') return
      // 麦克风权限被拒(not-allowed / service-not-allowed)单独提示
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        deps.toast(t('learn.toastMicDenied'), 3600)
        return
      }
      // 安卓设备的识别走 Google 语音服务,国内网络不通时上报 network;
      // 不再让用户卡在“有权限但没反应”,直接切到录音 + 后端 ASR。
      if (e.error === 'network') {
        deps.toast(t('learn.toastVoiceFallback'), 3600)
        sr = null
        void startRecorder()
        return
      }
      deps.toast(t('learn.toastNoVoice'))
    }
    listening.value = true
    try {
      sr.start()
    } catch {
      listening.value = false
      // 识别器同步拒绝启动时原先静默复位,用户只看到麦克风闪一下
      deps.toast(t('learn.toastNoVoice'))
    }
  }

  /** 模型语音回复开关(功能待开发,开启后仍以文本回复) */
  function setModelVoice(on: boolean) {
    updateSettings({ modelVoice: on })
    if (on) deps.toast(t('learn.toastVoiceDev'))
  }

  /** 离开页面:停掉识别、清掉预热/转写定时器,避免后台还在烧麦克风 */
  function dispose() {
    recorderSeq += 1
    const recognition = sr
    sr = null
    recognition?.stop()
    cleanupRecorder()
    listening.value = false
    cancelConvert()
    if (convDebounce) {
      clearTimeout(convDebounce)
      convDebounce = null
    }
  }

  return { listening, toggleMic, setModelVoice, cancelConvert, dispose }
}
