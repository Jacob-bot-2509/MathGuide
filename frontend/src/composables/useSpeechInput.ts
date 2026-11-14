/** 语音输入:浏览器本地识别 + 「点停即转写」的四档编排。
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
import { speechToMath } from '@/services/chatService'
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

  function toggleMic() {
    if (listening.value) {
      srStopToConvert = true
      sr?.stop()
      return
    }
    if (!settingsState.voiceAccess) {
      deps.toast(t('learn.toastVoiceDenied'))
      return
    }
    const Ctor = getSR()
    if (!Ctor) {
      deps.toast(t('learn.toastNoSR'))
      return
    }
    sr = new Ctor()
    sr.lang = settingsState.language === 'en' ? 'en-US' : 'zh-CN'
    sr.interimResults = true
    sr.continuous = true
    srBaseText = deps.input.value
    convWarmDone = false
    cancelConvert() // 清理上一次语音遗留的转写流
    sr.onresult = (e) => {
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
        const raw = deps.input.value
        if (raw.trim() && raw !== srBaseText) {
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
      }
    }
    sr.onerror = (e) => {
      listening.value = false
      if (e.error === 'aborted') return
      // 麦克风权限被拒(not-allowed / service-not-allowed)单独提示
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        deps.toast(t('learn.toastMicDenied'), 3600)
        return
      }
      // 安卓设备的识别走 Google 语音服务,国内网络不通时上报 network
      deps.toast(e.error === 'network' ? t('learn.toastVoiceNetwork') : t('learn.toastNoVoice'))
    }
    listening.value = true
    try {
      sr.start()
    } catch {
      listening.value = false
    }
  }

  /** 模型语音回复开关(功能待开发,开启后仍以文本回复) */
  function setModelVoice(on: boolean) {
    updateSettings({ modelVoice: on })
    if (on) deps.toast(t('learn.toastVoiceDev'))
  }

  /** 离开页面:停掉识别、清掉预热/转写定时器,避免后台还在烧麦克风 */
  function dispose() {
    sr?.stop()
    cancelConvert()
    if (convDebounce) {
      clearTimeout(convDebounce)
      convDebounce = null
    }
  }

  return { listening, toggleMic, setModelVoice, cancelConvert, dispose }
}
