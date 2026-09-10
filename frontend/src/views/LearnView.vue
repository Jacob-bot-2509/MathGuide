<script setup lang="ts">
/**
 * 学习辅助 —— 智能答疑对话界面(主功能)。
 *
 * 会话架构(上下文栈):
 * - 每次进入页面都开启全新会话;旧会话自动归档,
 *   在问题归纳面板按板块检索,可随时跳回原上下文。
 * - 每个会话归属一个高等数学板块;首次提问时绑定板块。
 * - 检测到与当前会话不同类型的问题 → 先检索同板块旧会话(上下文栈),
 *   命中则切回该会话延续上下文,否则新开一个会话;
 *   同类型问题的延续拓展 → 保持当前会话,避免不同类型问题相互纠缠。
 * - 所有会话持久化到 localStorage(记忆功能),
 *   问题归纳面板按板块汇总,点击问题可跳回当时所在的对话。
 *
 * 回复由后端 LLM 流式生成(services/chatService,SSE 契约);
 * 问题分类由前端关键词预判,后端路由做最终裁决。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef } from 'vue'
import { useRouter } from 'vue-router'
import MathText from '@/components/chat/MathText.vue'
import CategoryPanel from '@/components/chat/CategoryPanel.vue'
import SpeechTips from '@/components/chat/SpeechTips.vue'
import { COMMANDS } from '@/utils/commands'
import { catName, cmdDefault, cmdHint, cmdName, t } from '@/utils/i18n'
import { speechToMath, streamReply, type ChatMeta, type ChatStreamHandle } from '@/services/chatService'
import { CATEGORIES, DISPLAY_KEYS, FALLBACK_CATEGORY, classifyQuestion, isChitchat } from '@/utils/classifier'
import { settingsState, updateSettings } from '@/stores/settings'
import {
  MAX_SESSIONS,
  nextMsgId,
  nextSessionId,
  persistSessions,
  sessionsState,
  type ChatAttachment,
  type ChatMsg,
  type ChatSession,
} from '@/stores/sessions'
import { addToTrash } from '@/stores/trash'
import { addNotebookEntry, notebookState } from '@/stores/notebook'
import { compressImage } from '@/utils/avatar'
import { beautifyMath, cachedConvert, normalizeSpeechCase, saveConvert, speechMathConvert } from '@/utils/speechMath'
import { showToast } from '@/utils/toast'

const router = useRouter()

/* 文件导入上限(拖拽一次最多 3 个;粘贴文本截断上限,保护本地存储与请求体积) */
const MAX_DROP_FILES = 3
const PASTE_TEXT_MAX = 3000

/** 触屏设备判定:手机/平板用「粘贴导入」替代拖拽(拖拽仅限电脑端) */
const isTouchDevice = window.matchMedia('(pointer: coarse)').matches

/* 文本/PDF 教材:上传时提取正文随附件保存,章节导航等指令可基于内容工作。
   上限 3 万字,发挥 QwenLong 长上下文能力(移动端粘贴导入仍 3 千字) */
const FILE_TEXT_EXT = /\.(txt|md|markdown)$/i
const FILE_TEXT_MAX = 30000

/* 会话上下文栈(共享 store:归档与回收站恢复基于同一份数据) */
const sessions = toRef(sessionsState, 'sessions')
const activeId = toRef(sessionsState, 'activeId')
const input = ref('')
const panelOpen = ref(false)
const tipsOpen = ref(false)
const flashMsgId = ref(0)
const inputEl = ref<HTMLTextAreaElement | null>(null)
const listEl = ref<HTMLDivElement | null>(null)

/* 后台流:不同会话的输出并行生成,切换界面不中断;按消息 id 索引便于精确取消 */
let streams = new Map<number, ChatStreamHandle>()
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let flashTimer: ReturnType<typeof setTimeout> | null = null

const activeSession = computed(() => sessions.value.find((s) => s.id === activeId.value))

/** 是否"正在回答提问"(仅剩首条问候流时不算忙碌 —— 问候可被提问打断) */
const busy = computed(() => {
  const s = activeSession.value
  if (!s) return false
  const first = s.messages[0]
  if (first?.streaming) return false
  return s.messages.some((m) => m.streaming)
})

/* 问题归纳:所有板块常驻显示(无问题的板块显示 0),按教学板块顺序排列 */
const summary = computed(() => {
  const map = new Map<string, { key: string; label: string; color: string; questions: { id: number; text: string }[] }>()
  for (const c of [...CATEGORIES, FALLBACK_CATEGORY]) {
    map.set(c.key, { key: c.key, label: catName(c.key), color: c.color, questions: [] })
  }
  for (const s of sessions.value) {
    if (!s.cat) continue
    const entry = map.get(s.cat.key)
    if (!entry) continue
    for (const m of s.messages) {
      // 寒暄/闲聊等非问题语句不进问题归纳
      if (m.role === 'user' && !m.chitchat) entry.questions.push({ id: m.id, text: m.content })
    }
  }
  return DISPLAY_KEYS.flatMap((k) => {
    const v = map.get(k)
    return v ? [{ ...v, count: v.questions.length }] : []
  })
})

/** 问题总数:直接取 summary 的汇总,不再单独遍历会话重数一遍 */
const questionCount = computed(() => summary.value.reduce((n, c) => n + c.count, 0))

/* ---------- 会话管理(上下文栈) ---------- */

function createSession(cat?: ChatSession['cat']): ChatSession {
  const s: ChatSession = { id: nextSessionId(), cat, messages: [] }
  sessions.value.push(s)
  if (sessions.value.length > MAX_SESSIONS) sessions.value.shift()
  activeId.value = s.id
  persistSessions()
  return s
}

/** 页面卸载时:停止全部后台流与定时器,保留已生成内容 */
function stopAllStreams() {
  for (const s of streams.values()) s.cancel()
  streams.clear()
  for (const t of timers.values()) clearTimeout(t)
  timers.clear()
  for (const s of sessions.value) {
    for (const m of s.messages) {
      m.streaming = false
      m.thinking = false
    }
  }
  persistSessions()
}

/* ---------- 对话 ---------- */

/** 滚到底部;流式期间用瞬时滚动(避免 40ms 级 smooth 动画排队争抢主线程),主动发送等场景用平滑 */
function scrollBottom(smooth = true) {
  nextTick(() => {
    listEl.value?.scrollTo({ top: listEl.value.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  })
}

/** 是否"贴底"(距底部不足 60px):流式输出只在贴底时自动跟随;
 *  用户上拉回看时保持原地,不把对话框往下拽;重新滚回底部即恢复跟随 */
let pinnedToBottom = true

function onListScroll() {
  const el = listEl.value
  if (!el) return
  pinnedToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
}

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

/** 组装最近几轮历史(供模型理解上下文):去掉刚发的本条用户消息
    (它作为 prompt 单独传递),排除流式中的消息,单条截断;
    粘贴导入的文本文件以正文入历史,后续追问可基于文件内容作答。
    上限 16 条:更早的对话由后端滚动摘要压缩,早期上下文不丢失 */
function buildHistory(session: ChatSession): ChatMeta['history'] {
  return session.messages
    .slice(0, -1)
    .filter((m) => !m.streaming && m.content)
    .slice(-16)
    .map((m) => ({ role: m.role, content: (m.attachment?.text || m.content).slice(0, 400) }))
}

/** 让某会话的一条助手消息开始流式接收回复(输出在所属会话内进行,切换界面不中断) */
function streamInto(session: ChatSession, reply: ChatMsg, prompt: string, meta?: ChatMeta) {
  // 增量节流:高频 chunk 先攒进 pending,约每 24ms 合并提交一次;
  // MathText 对已闭合公式有渲染缓存,单次提交开销极小,不会随正文增长变慢
  let pending = ''
  let commit: ReturnType<typeof setTimeout> | null = null
  const flush = () => {
    commit = null
    if (!pending) return
    reply.content += pending
    pending = ''
    // 贴底才跟随滚动:用户上拉阅读时不打扰
    if (session === activeSession.value && pinnedToBottom) scrollBottom(false)
  }
  const stream = streamReply(prompt, {
    onDelta: (t) => {
      reply.thinking = false
      pending += t
      if (!reply.content) {
        // 首个增量立即上屏(欢迎语/回复的第一句话即刻出现),后续增量再走节流
        flush()
      } else if (!commit) {
        commit = setTimeout(flush, 24)
      }
    },
    onDone: () => {
      if (commit) {
        clearTimeout(commit)
        commit = null
      }
      flush() // 提交最后的残量,避免丢尾
      reply.streaming = false
      reply.thinking = false
      // 主动停止且未出字时给一句停止提示(此时流已被 cancelReply 移出 streams)
      if (!reply.content && !streams.has(reply.id)) reply.content = t('learn.stoppedNote')
      streams.delete(reply.id)
      persistSessions()
    },
    // 请求失败(典型:后端未启动 / 限流 429)时,若一字未出则显示对应提示,
    // 避免气泡永远停留在"思考中"且无任何反馈。
    // 失败路径 onDone 不再触发(settled 拦截),清理须在此完整收尾,
    // 否则 streaming 永真 → 发送按钮永远"生成中"。
    onError: (err?: unknown) => {
      if (commit) {
        clearTimeout(commit)
        commit = null
      }
      flush() // 先提交已收到的残量,不丢内容
      reply.thinking = false
      if (!reply.content) {
        reply.content = (err as { status?: number })?.status === 429
          ? t('learn.toastRateLimit')
          : t('learn.errStream')
      }
      reply.streaming = false
      streams.delete(reply.id)
      persistSessions()
    },
  }, meta)
  streams.set(reply.id, stream)
}

/** 延迟后开始流式输出(模拟"思考"阶段);定时器按消息 id 记录,便于精确取消 */
function scheduleStream(session: ChatSession, reply: ChatMsg, prompt: string, delay: number, meta?: ChatMeta) {
  const timer = setTimeout(() => {
    timers.delete(reply.id)
    if (reply.streaming) streamInto(session, reply, prompt, meta)
  }, delay)
  timers.set(reply.id, timer)
}

/** 精确取消一条回复:等待中的定时器与进行中的流一并清理(含尚未启动的孤儿流) */
function cancelReply(id: number) {
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
  const stream = streams.get(id)
  if (stream) {
    stream.cancel()
    streams.delete(id)
  }
}

/** 停止当前会话的生成:进行中的流中止后走正常收尾(保留已生成内容),
    尚未启动的(思考阶段)同步收尾,避免"生成中"卡死 */
function stopGenerating() {
  const session = activeSession.value
  if (!session) return
  for (const m of session.messages) {
    if (!m.streaming) continue
    cancelReply(m.id)
    m.thinking = false
    if (!streams.has(m.id)) {
      m.streaming = false
      if (!m.content) m.content = t('learn.stoppedNote')
    }
  }
  persistSessions()
}

function send(text?: string, cmd?: string) {
  let content = (text ?? input.value).trim()
  if (!content) return

  // 寒暄/闲聊:不分类、不切换或新开会话,只就话答话
  const chitchat = isChitchat(content)
  const catInfo = chitchat ? undefined : classifyQuestion(content)

  // 会话选择:同类型延续当前会话;不同类型检索同板块旧会话,否则新开;
  // 闲聊沿用当前会话(无会话则开一个未归类会话,不绑定板块、不进归纳面板)
  let session = activeSession.value
  if (!session) session = createSession(catInfo)

  if (catInfo) {
    if (!session.cat) {
      // 新会话首次提问:绑定板块
      session.cat = catInfo
    } else if (session.cat.key !== catInfo.key) {
      const current = session
      const existing = [...sessions.value].reverse().find((s) => s.cat?.key === catInfo.key && s.id !== current.id)
      if (existing) {
        activeId.value = existing.id
        session = existing
      } else {
        session = createSession(catInfo)
      }
    }
  }

  // 章节知识导航:会话里已有教材文本时随指令携带正文,模型只划分章节列表
  if (cmd === '章节知识导航') {
    const tb = latestTextbookText(session)
    if (tb) content = `${content}\n\n<教材文本>:\n${tb}`
  }

  // 目标会话仍在生成回复时暂不接收新问题(每会话一次一问);
  // 例外:仅剩首条问候流未完成 → 直接打断问候,让位给真实提问。
  // 被打断时给出提示并保留输入内容,避免问题被静默丢弃
  if (session.messages.some((m) => m.streaming)) {
    if (!session.messages[0]?.streaming) {
      showToast(t('learn.toastBusy'))
      return
    }
    cancelReply(session.messages[0].id)
    session.messages.shift()
  }

  session.messages.push({ id: nextMsgId(), role: 'user', content, cmd, chitchat: chitchat || undefined })
  input.value = ''
  autoGrow()
  pinnedToBottom = true // 自己刚发消息:强制回底并恢复跟随
  scrollBottom()
  persistSessions()

  // prompt 原文随流发送;指令与归属随 ChatMeta 传给后端(契约 ChatRequest);
  // 最近几轮历史一并携带,模型可理解上下文
  const history = buildHistory(session)
  const reply: ChatMsg = {
    id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true,
    // 章节列表回复打标:「返回」按钮跳转的目标
    nav: cmd === '章节知识导航' ? 'list' : undefined,
  }
  session.messages.push(reply)
  // 流式回调必须操作响应式代理(数组里读出的那条),而不是 push 进去的裸对象;
  // 裸对象上的修改不触发 Vue 更新 → 界面会"凝固"到下一次交互才刷新
  const live = session.messages[session.messages.length - 1]
  scheduleStream(session, live, content, 450, {
    cmd,
    sessionId: session.id,
    categoryKey: session.cat?.key,
    history,
  })
}

/** 点击指令:直接执行对应功能 */
function runCommand(cmd: string) {
  // 问题记录 = 本地归纳本:直接展示,不走后端
  if (cmd === '问题记录') {
    showNotebook()
    return
  }
  // 输入为空用指令默认问题;不清空输入,由 send 在成功发出后统一清空
  const text = input.value.trim() || cmdDefault(cmd) || cmd
  send(text, cmd)
}

/** 新建对话:当前会话与其进行中的输出原样保留(后台继续生成),切换至新会话 */
function newConversation() {
  createSession()
  greet()
}

/** 归纳面板删除记录:问答对移入回收站(30 天内可恢复),会话删空则整体移除 */
function deleteHistory(id: number) {
  const session = sessions.value.find((s) => s.messages.some((m) => m.id === id))
  if (!session) return
  if (!window.confirm(t('learn.deleteConfirm'))) return

  const idx = session.messages.findIndex((m) => m.id === id)
  const nextUser = session.messages.findIndex((m, i) => i > idx && m.role === 'user')
  const end = nextUser === -1 ? session.messages.length : nextUser
  const removed = session.messages.slice(idx, end)

  // 若删除范围内的回答在等待或正在生成,精确取消对应定时器与流(含未启动的)
  for (const m of removed) cancelReply(m.id)

  // 入回收站:保留板块与所属会话信息,便于恢复后重新分配
  addToTrash({
    id,
    question: removed.find((m) => m.role === 'user')?.content ?? '',
    answer: removed
      .filter((m) => m.role === 'assistant' && m.content)
      .map((m) => m.content)
      .join('\n\n'),
    cat: session.cat,
    sessionId: session.id,
    deletedAt: Date.now(),
  })

  session.messages.splice(idx, end - idx)

  // 会话已无用户消息则整体移除;若删的是当前会话,开启新会话
  if (!session.messages.some((m) => m.role === 'user')) {
    sessions.value = sessions.value.filter((s) => s.id !== session.id)
    if (activeId.value === session.id) {
      createSession()
      greet()
    }
  }
  persistSessions()
  showToast(t('learn.toastTrashed'))
}

/** 归纳面板点击问题:跳回该问答所在的会话上下文并定位 */
function jumpTo(id: number) {
  const session = sessions.value.find((s) => s.messages.some((m) => m.id === id))
  if (!session) return
  activeId.value = session.id
  persistSessions()
  panelOpen.value = false
  nextTick(() => {
    listEl.value
      ?.querySelector<HTMLElement>(`[data-msg-id="${id}"]`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    flashMsgId.value = id
    if (flashTimer) clearTimeout(flashTimer)
    flashTimer = setTimeout(() => (flashMsgId.value = 0), 1600)
  })
}

/* ---------- 章节导航交互(点击章节 → 知识指引;返回 → 回章节列表) ---------- */

/** 会话内最新的教材文本(粘贴导入或上传的文本文件),供章节导航使用 */
function latestTextbookText(session: ChatSession): string {
  for (const m of [...session.messages].reverse()) {
    if (m.role === 'user' && m.attachment?.text) return m.attachment.text
  }
  return ''
}

/** 对话区点击:承接 MathText 渲染的 cmd:// 契约按钮(章节胶囊 / 返回黄框 / 收录是否) */
function onListClick(e: MouseEvent) {
  const el = (e.target as HTMLElement).closest<HTMLElement>('[data-mg-cmd]')
  if (!el) return
  const url = el.dataset.mgCmd || ''
  if (url === 'cmd://back') {
    backToNavList()
    return
  }
  if (url.startsWith('cmd://chapter/')) {
    onNavChapter(decodeURIComponent(url.slice('cmd://chapter/'.length)))
    return
  }
  if (url === 'cmd://nb/yes' || url === 'cmd://nb/no') {
    const msgEl = (e.target as HTMLElement).closest<HTMLElement>('[data-msg-id]')
    onNotebookChoice(url.endsWith('/yes'), msgEl ? Number(msgEl.dataset.msgId) : 0)
    return
  }
  if (url.startsWith('cmd://nb/jump/')) {
    jumpToNotebookEntry(Number(url.slice('cmd://nb/jump/'.length)))
  }
}

/* ---------- 问题记录(归纳本):解答完询问是否收录,点「是」收纳成档 ---------- */

/** 收录选择:先摘掉按钮(防重复点击),「是」则把本题问答收纳进归纳本;
    无论是否都接一句形式性询问(一次性提问若干问题 → 统一收纳在一档) */
function onNotebookChoice(yes: boolean, msgId: number) {
  const session = activeSession.value
  if (!session) return
  const idx = session.messages.findIndex((m) => m.id === msgId)
  if (idx < 0) return
  const answer = session.messages[idx]
  answer.content = answer.content.replace(/\s*\[(是|否|Yes|No)\]\(cmd:\/\/nb\/(yes|no)\)/g, '')
  if (yes) {
    const question = [...session.messages.slice(0, idx)].reverse().find((m) => m.role === 'user')
    if (question) {
      addNotebookEntry(question.content, answer.content, session.id, question.id)
      showToast(t('learn.toastNbAdded'))
    }
  }
  session.messages.push({
    id: nextMsgId(),
    role: 'assistant',
    content: yes ? t('learn.nbAfterYes') : t('learn.nbAfterNo'),
  })
  persistSessions()
  scrollBottom()
}

/** 点击「问题记录」指令:本地归纳本,输出所整理的题目与参考解答(含参考思路),点击条目跳回原问答 */
function showNotebook() {
  const session = activeSession.value ?? createSession()
  if (session.messages.some((m) => m.streaming)) {
    showToast(t('learn.toastBusy'))
    return
  }
  const entries = notebookState.entries
  if (!entries.length) {
    session.messages.push({
      id: nextMsgId(),
      role: 'assistant',
      content: t('learn.nbEmpty'),
    })
  } else {
    const lines: string[] = [`📓 **${t('learn.nbTitle', { n: entries.length })}**`]
    for (const [i, e] of entries.entries()) {
      lines.push(`\n**${i + 1}. 题目**: [${e.question.slice(0, 120)}${e.question.length > 120 ? '…' : ''}](cmd://nb/jump/${e.id})`)
      // 预览同样过 Unicode 美化:去掉 $ 定界符、^/_ 与常见 LaTeX 记号,直读显示
      const preview = beautifyMath(e.answer.slice(0, 300))
      lines.push(`**参考解答**: ${preview}${e.answer.length > 300 ? '…' : ''}`)
    }
    session.messages.push({ id: nextMsgId(), role: 'assistant', content: lines.join('\n') })
  }
  persistSessions()
  scrollBottom()
}

/** 归纳本条目跳回原问答(温故知新) */
function jumpToNotebookEntry(id: number) {
  const entry = notebookState.entries.find((e) => e.id === id)
  if (!entry) return
  const session = sessions.value.find((s) => s.id === entry.sessionId)
  if (!session || !session.messages.some((m) => m.id === entry.msgId)) {
    showToast(t('learn.toastNbGone'))
    return
  }
  jumpTo(entry.msgId)
}

/** 点击章节:已讲解过 → 直接跳转到已生成的指引;未讲解 → 请求该章知识指引 */
function onNavChapter(name: string) {
  const session = activeSession.value
  if (!session) return
  const done = session.messages.find((m) => m.role === 'assistant' && m.navGuideFor === name && m.content)
  if (done) {
    jumpTo(done.id)
    return
  }
  if (session.messages.some((m) => m.streaming)) {
    showToast(t('learn.toastBusy'))
    return
  }
  const reply: ChatMsg = {
    id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true,
    navGuideFor: name,
  }
  session.messages.push(reply)
  const live = session.messages[session.messages.length - 1]
  // 教材文本已由后端按 sessionId 缓存(章节导航生成列表时入库),这里只发章节名
  scheduleStream(session, live, `请给出「${name}」这一章的大概知识指引`, 450, {
    cmd: '章节知识指引',
    sessionId: session.id,
    categoryKey: session.cat?.key,
    history: buildHistory(session),
  })
}

/** 「返回」:跳到本会话的章节列表(不重新生成) */
function backToNavList() {
  const session = activeSession.value
  if (!session) return
  const list = [...session.messages].reverse().find((m) => m.role === 'assistant' && m.nav === 'list')
  if (list) jumpTo(list.id)
}

/* ---------- 附件上传(相册 / 拍照 / 文件) ---------- */

const attachOpen = ref(false)
const imgInputEl = ref<HTMLInputElement | null>(null)
const camInputEl = ref<HTMLInputElement | null>(null)
const fileInputEl = ref<HTMLInputElement | null>(null)

function pickAlbum() {
  attachOpen.value = false
  imgInputEl.value?.click()
}

function pickCamera() {
  attachOpen.value = false
  camInputEl.value?.click()
}

function pickFile() {
  attachOpen.value = false
  fileInputEl.value?.click()
}

async function onImage(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await importImageFile(file)
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) attachFileItem(file)
}

/** 文件入库:PDF(pdfjs 提取文本层)/ 文本类(.txt/.md)读取正文随附件保存,其余仅元信息 */
async function attachFileItem(file: File) {
  if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
    try {
      const text = await extractPdfText(file)
      if (!text) {
        // 扫描版 PDF(无文本层):按普通文件接收并提示
        attachMessage({ kind: 'file', name: file.name, size: file.size }, file.name)
        showToast(t('learn.toastPdfNoText'))
        return
      }
      attachMessage({ kind: 'file', name: file.name, size: file.size, text }, file.name)
      return
    } catch {
      /* 解析失败按普通文件处理 */
    }
  }
  if (FILE_TEXT_EXT.test(file.name)) {
    try {
      const raw = await file.text()
      const capped = raw.trim().slice(0, FILE_TEXT_MAX)
      attachMessage({ kind: 'file', name: file.name, size: file.size, text: capped }, file.name)
      return
    } catch {
      /* 读取失败按普通文件处理 */
    }
  }
  attachMessage({ kind: 'file', name: file.name, size: file.size }, file.name)
}

/** PDF 文本提取(pdfjs 懒加载:仅首次传 PDF 时拉取,主包体积不受影响) */
async function extractPdfText(file: File): Promise<string> {
  const pdfjs = await import('pdfjs-dist')
  const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default
  const doc = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise
  const parts: string[] = []
  const pages = Math.min(doc.numPages, 80) // 页数上限,防超大 PDF 拖垮页面
  for (let i = 1; i <= pages; i++) {
    const page = await doc.getPage(i)
    const content = await page.getTextContent()
    parts.push(content.items.map((it) => ('str' in it ? it.str : '')).join(' '))
  }
  const text = parts.join('\n').replace(/\s+/g, ' ').trim()
  return text.slice(0, FILE_TEXT_MAX)
}

/** 图片统一入库:压缩为缩略 dataURL 后作为图片附件发送(相册/拍照/拖入/粘贴共用) */
async function importImageFile(file: File) {
  try {
    const url = await compressImage(file, 800)
    attachMessage({ kind: 'image', name: file.name, url, size: file.size }, file.name)
  } catch {
    showToast(t('acc.toastAvatarFail'))
  }
}

/* ---------- 拖拽导入(电脑端:从桌面/资源管理器拖文件进对话框) ---------- */

const dragging = ref(false)
let dragHideTimer: ReturnType<typeof setTimeout> | null = null

function onDragOver(e: DragEvent) {
  if (isTouchDevice || !e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  dragging.value = true
  if (dragHideTimer) {
    clearTimeout(dragHideTimer)
    dragHideTimer = null
  }
}

/** dragleave 在子元素间穿梭时会频繁触发:延迟收尾,避免遮罩闪烁 */
function onDragLeave() {
  if (dragHideTimer) clearTimeout(dragHideTimer)
  dragHideTimer = setTimeout(() => (dragging.value = false), 120)
}

async function onDropFiles(e: DragEvent) {
  if (isTouchDevice) return
  if (dragHideTimer) clearTimeout(dragHideTimer)
  dragging.value = false
  const files = Array.from(e.dataTransfer?.files ?? [])
  if (!files.length) return
  e.preventDefault()
  if (files.length > MAX_DROP_FILES) {
    showToast(t('learn.toastDropTooMany'))
    return
  }
  for (const f of files) {
    if (f.type.startsWith('image/')) await importImageFile(f)
    else await attachFileItem(f)
  }
}

/* ---------- 粘贴导入(移动端为主:剪贴板图片/文本 → 附件) ---------- */

/** 输入框粘贴到剪贴板文件(截图/复制图片)时:不进输入框,直接作为附件导入 */
function onPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (const item of items) {
    if (item.kind !== 'file') continue
    const f = item.getAsFile()
    if (!f) continue
    e.preventDefault()
    if (f.type.startsWith('image/')) importImageFile(f)
    else attachFileItem(f)
    return
  }
}

/** 移动端「粘贴导入」按钮:优先读剪贴板图片,退而读文本
    (作为 .txt 附件导入,正文随提示词交给模型阅读理解) */
async function pasteImport() {
  attachOpen.value = false
  // 剪贴板图片(截图/复制的图片)
  try {
    if (navigator.clipboard?.read) {
      const items = await navigator.clipboard.read()
      for (const item of items) {
        const imgType = item.types.find((ty) => ty.startsWith('image/'))
        if (!imgType) continue
        const blob = await item.getType(imgType)
        const ext = imgType.split('/')[1] || 'png'
        await importImageFile(new File([blob], `粘贴图片.${ext}`, { type: imgType }))
        return
      }
    }
  } catch {
    /* 无图片或未授权,继续尝试文本 */
  }
  // 剪贴板文本(复制的文档/题目/论文片段)
  try {
    const text = (await navigator.clipboard.readText()).trim()
    if (!text) {
      showToast(t('learn.toastPasteEmpty'))
      return
    }
    const capped = text.slice(0, PASTE_TEXT_MAX)
    attachMessage(
      { kind: 'file', name: '粘贴文本.txt', size: new Blob([capped]).size, text: capped },
      '粘贴文本.txt',
    )
  } catch {
    showToast(t('learn.toastPasteEmpty'))
  }
}

/** 附件消息:留在当前会话(未分类会话归入未归类),MG 给出附件接收回复 */
function attachMessage(attachment: ChatAttachment, content: string) {
  let session = activeSession.value
  if (!session) session = createSession(FALLBACK_CATEGORY)
  if (!session.cat) session.cat = FALLBACK_CATEGORY
  if (session.messages.some((m) => m.streaming)) {
    if (!session.messages[0]?.streaming) return
    cancelReply(session.messages[0].id)
    session.messages.shift()
  }

  session.messages.push({ id: nextMsgId(), role: 'user', content, attachment })
  pinnedToBottom = true
  scrollBottom()
  // 图片以 dataURL 随会话持久化:存储超限时明确提示,避免静默丢失记录
  if (!persistSessions()) showToast(t('learn.toastStorage'))

  const reply: ChatMsg = { id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true }
  session.messages.push(reply)
  // 同上:流式期间通过响应式代理更新,界面才能实时刷新
  const live = session.messages[session.messages.length - 1]
  // 契约 [attach:image|file]文件名;粘贴导入的文本带正文(空行分隔),后端交 LLM 阅读理解
  const attachPrompt = `[attach:${attachment.kind}]${attachment.name}${attachment.text ? `\n\n${attachment.text}` : ''}`
  scheduleStream(session, live, attachPrompt, 450, {
    sessionId: session.id,
    categoryKey: session.cat?.key,
    history: buildHistory(session),
  })
}

function fmtSize(bytes?: number): string {
  if (bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/* ---------- 语音输入(浏览器本地识别,Chrome / Edge 可用) ---------- */

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
  const w = window as unknown as { SpeechRecognition?: SRConstructor; webkitSpeechRecognition?: SRConstructor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

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
  convSeq++
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
  // 先本地归一大小写(ASR 大小写是噪声,不刻意念"大"一律小写),
  // 再交 LLM 按数学惯例自动判别(矩阵 A/随机变量 X 等该大写则大写)
  convCancel = speechToMath(normalizeSpeechCase(raw), {
    onDelta: (full) => {
      if (seq !== convSeq) return
      convAcc = full
      if (convLive) {
        // 输入框是纯文本:把模型可能输出的 ^/_、LaTeX 记号美化为 Unicode 直读形式
        const pretty = beautifyMath(full)
        if (pretty !== input.value) {
          input.value = pretty
          autoGrow()
        }
      }
    },
    onDone: (full) => {
      if (seq !== convSeq) return
      saveConvert(raw, beautifyMath(full), 'llm') // 精修结果(美化后)入缓存:同句再念零请求
    },
    onFail: () => {
      if (seq === convSeq && !listening.value) showToast(t('learn.toastConvertFail'))
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
    showToast(t('learn.toastVoiceDenied'))
    return
  }
  const Ctor = getSR()
  if (!Ctor) {
    showToast(t('learn.toastNoSR'))
    return
  }
  sr = new Ctor()
  sr.lang = settingsState.language === 'en' ? 'en-US' : 'zh-CN'
  sr.interimResults = true
  sr.continuous = true
  srBaseText = input.value
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
    input.value = srBaseText + final + interim
    autoGrow()
    // 后台预热:停顿 800ms 后把当前文本拿去转写(结果先攒着,点停即展示)
    if (convDebounce) clearTimeout(convDebounce)
    convDebounce = setTimeout(() => {
      convDebounce = null
      if (listening.value && !convWarmDone) {
        convWarmDone = true
        startConvert(input.value, false)
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
      const raw = input.value
      if (raw.trim() && raw !== srBaseText) {
        const cached = cachedConvert(raw)
        if (cached && cached.source === 'llm') {
          input.value = cached.text
          autoGrow()
        } else if (convRaw === raw && convAcc) {
          convLive = true
          input.value = convAcc
          autoGrow()
        } else {
          const local = cached?.text ?? speechMathConvert(raw)
          if (!cached) saveConvert(raw, local, 'local')
          input.value = local
          autoGrow()
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
      showToast(t('learn.toastMicDenied'), 3600)
      return
    }
    // 安卓设备的识别走 Google 语音服务,国内网络不通时上报 network
    showToast(e.error === 'network' ? t('learn.toastVoiceNetwork') : t('learn.toastNoVoice'))
  }
  listening.value = true
  try {
    sr.start()
  } catch {
    listening.value = false
  }
}

/** 模型语音回复开关(功能待开发,开启后仍以文本回复) */
function toggleModelVoice() {
  updateSettings({ modelVoice: !settingsState.modelVoice })
  if (settingsState.modelVoice) showToast(t('learn.toastVoiceDev'))
}

/* ---------- 初始化 ---------- */

function greet() {
  const session = activeSession.value ?? createSession()
  const reply: ChatMsg = { id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true }
  session.messages.push(reply)
  // 欢迎语是罐头文案:零延迟立即请求,配合首帧立即上屏 → 进入面板即刻出字。
  // live 取数组里的响应式代理:流式回调改它的字段,界面才会实时刷新
  const live = session.messages[session.messages.length - 1]
  scheduleStream(session, live, '', 0)
}

onMounted(() => {
  // 每次进入页面都开启全新对话;旧会话自动归档到相应板块
  // (会话档案由 stores/sessions 在应用启动时恢复)
  sessions.value = sessions.value.filter((s) => s.cat || s.messages.some((m) => m.role === 'user'))
  createSession()
  greet()
})

onBeforeUnmount(() => {
  stopAllStreams()
  sr?.stop()
  cancelConvert()
  if (convDebounce) clearTimeout(convDebounce)
  if (flashTimer) clearTimeout(flashTimer)
})
</script>

<template>
  <div class="learn" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDropFiles">
    <header class="chat-header">
      <button class="back" @click="router.push('/home')">{{ t('common.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t('learn.title') }}</span>
        <span class="tech-label sub">MODULE 01 · LEARN</span>
      </div>
      <div class="right">
        <button class="new-btn" @click="newConversation">{{ t('learn.newChat') }}</button>
        <!-- 板块上下文徽章(未归类会话不显示标题) -->
        <span v-if="activeSession?.cat && activeSession.cat.key !== 'other'" class="session-chip">
          <span class="dot" :style="{ background: activeSession.cat.color }"></span>
          {{ catName(activeSession.cat.key) }}{{ t('learn.context') }}
        </span>
        <span v-else-if="!activeSession?.cat" class="session-chip session-chip--dim">{{ t('learn.newSession') }}</span>
        <button class="sum-btn" @click="panelOpen = !panelOpen">
          {{ t('learn.archive') }}<span v-if="questionCount" class="sum-badge">{{ questionCount }}</span>
        </button>
        <span class="badge tech-label">{{ t('common.mgLearn') }}</span>
        <button class="dots-btn" :title="t('common.settings')" @click="router.push('/settings')">···</button>
      </div>
    </header>

    <!-- 问题归纳面板 -->
    <CategoryPanel
      v-if="panelOpen"
      :items="summary"
      :total="questionCount"
      @close="panelOpen = false"
      @jump="jumpTo"
      @delete="deleteHistory"
    />

    <!-- 念法速查贴士(语音输入中点击麦克风旁的📓打开) -->
    <SpeechTips v-if="tipsOpen" @close="tipsOpen = false" />

    <!-- 对话区(当前会话) -->
    <div ref="listEl" class="chat-list" @scroll="onListScroll" @click="onListClick">
      <template v-if="activeSession">
        <div
          v-for="m in activeSession.messages"
          :key="m.id"
          class="msg"
          :class="[m.role, { flash: m.id === flashMsgId }]"
          :data-msg-id="m.id"
        >
          <div class="bubble">
            <div v-if="m.attachment" class="attach">
              <img
                v-if="m.attachment.kind === 'image' && m.attachment.url"
                class="attach-img"
                :src="m.attachment.url"
                :alt="m.attachment.name"
              />
              <div v-else>
                <div class="attach-file">
                  <span class="af-icon">📄</span>
                  <span class="af-meta">
                    <span class="af-name">{{ m.attachment.name }}</span>
                    <span class="af-size">{{ fmtSize(m.attachment.size) }}</span>
                  </span>
                </div>
                <!-- 粘贴导入的文本:气泡内展示正文预览 -->
                <div v-if="m.attachment.text" class="af-preview">
                  {{ m.attachment.text.slice(0, 200) }}{{ m.attachment.text.length > 200 ? '…' : '' }}
                </div>
              </div>
            </div>
            <span v-if="m.role === 'user' && m.cmd" class="cmd-tag">{{ m.cmd }}</span>
            <span v-if="m.role === 'user' && activeSession.cat" class="cat-chip">
              <span class="cat-dot" :style="{ background: activeSession.cat.color }"></span>{{ catName(activeSession.cat.key) }}
            </span>
            <template v-if="m.role === 'assistant'">
              <span v-if="m.thinking" class="thinking">{{ t('learn.thinking') }}<span class="dots">···</span></span>
              <MathText v-if="m.content" :text="m.content" />
              <span v-if="m.streaming && !m.thinking" class="cursor">▍</span>
            </template>
            <template v-else>{{ m.content }}</template>
          </div>
        </div>
      </template>
    </div>

    <!-- 拖拽导入遮罩(电脑端):pointer-events 穿透,事件仍落在 .learn 上 -->
    <div v-if="dragging" class="drop-mask">
      <div class="drop-box">📂 {{ t('learn.dropHint') }}</div>
    </div>

    <!-- 输入区:输入行 + 指令栏 -->
    <footer class="input-bar">
      <div class="input-row">
        <!-- 附件:相册照片 / 拍照 / 文件 -->
        <div class="attach-wrap">
          <button class="mic" :class="{ 'is-on': attachOpen }" :title="t('learn.attach')" @click="attachOpen = !attachOpen">
            ＋
          </button>
          <div v-if="attachOpen" class="pop-overlay" @click="attachOpen = false"></div>
          <div v-if="attachOpen" class="attach-pop">
            <button class="attach-btn" @click="pickAlbum()">🖼️ {{ t('learn.attachAlbum') }}</button>
            <button class="attach-btn" @click="pickCamera()">📷 {{ t('learn.attachCamera') }}</button>
            <button class="attach-btn" @click="pickFile()">📄 {{ t('learn.attachFile') }}</button>
            <!-- 移动端专属:从剪贴板粘贴导入(复制图片/文档 → 一键导入) -->
            <button v-if="isTouchDevice" class="attach-btn" @click="pasteImport()">📋 {{ t('learn.attachPaste') }}</button>
          </div>
        </div>
        <input ref="imgInputEl" type="file" accept="image/*" hidden @change="onImage" />
        <input ref="camInputEl" type="file" accept="image/*" capture="environment" hidden @change="onImage" />
        <input ref="fileInputEl" type="file" hidden @change="onFile" />
        <!-- 语音输入:点一下开始、再点一下完成;进行中麦克风旁弹出📓念法本子,
             点开可查念法(不打断输入进程) -->
        <div class="mic-wrap">
          <button
            v-if="listening"
            class="tips-btn"
            :title="t('tips.title')"
            @click="tipsOpen = !tipsOpen"
          >
            📓
          </button>
          <button
            class="mic"
            :class="{ listening }"
            :title="listening ? t('learn.stopListening') : t('learn.voiceInput')"
            @click="toggleMic"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3z" />
              <path d="M19 11a7 7 0 0 1-14 0" />
              <path d="M12 18v3" />
            </svg>
          </button>
        </div>
        <textarea
          ref="inputEl"
          v-model="input"
          rows="1"
          class="input"
          :placeholder="listening ? t('learn.listening') : t('learn.placeholder')"
          @input="autoGrow"
          @keydown.enter.exact.prevent="send()"
          @paste="onPaste"
        ></textarea>
        <!-- 生成中变为「停止生成」:可中断长回答,已生成内容保留 -->
        <button class="send" :class="{ 'is-stop': busy }" @click="busy ? stopGenerating() : send()">
          {{ busy ? t('learn.stop') : t('learn.send') }}
        </button>
      </div>
      <div class="commands">
        <span class="tech-label cmd-label">{{ t('learn.cmdLabel') }}</span>
        <button v-for="c in COMMANDS" :key="c.key" class="cmd" :title="cmdHint(c.key)" @click="runCommand(c.key)">
          <span class="cmd-icon">{{ c.icon }}</span>{{ cmdName(c.key) }}
        </button>
        <span class="voice-toggle">
          <span class="voice-label">{{ t('learn.voiceLabel') }}</span>
          <button
            class="switch"
            :class="{ on: settingsState.modelVoice }"
            :title="t('learn.voiceHint')"
            @click="toggleModelVoice"
          >
            <span class="knob"></span>
          </button>
          <span class="dev-badge">{{ t('common.tbd') }}</span>
        </span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.learn {
  height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  backdrop-filter: blur(8px);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.title-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title {
  color: var(--text-hi);
  font-size: 15px;
  letter-spacing: 0.06em;
}

.sub {
  font-size: 10px;
}

.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.badge {
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 11px;
}

.session-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-hi);
  border: 1px solid var(--line);
  padding: 5px 12px;
  border-radius: 999px;
}

.session-chip .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.session-chip--dim {
  color: var(--text-dim);
}

.new-btn {
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 5px 14px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  letter-spacing: 0.06em;
  transition: all var(--dur-fast) var(--ease-out);
}

.new-btn:hover {
  background: color-mix(in srgb, var(--cyan) 16%, transparent);
  box-shadow: var(--glow-cyan);
}

.sum-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 5px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all var(--dur-fast) var(--ease-out);
}

.sum-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.sum-badge {
  display: inline-grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: rgba(77, 214, 255, 0.15);
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 10px;
}

/* ---------- 对话区 ---------- */
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 22px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.msg {
  display: flex;
  scroll-margin: 20px 0;
}

.msg.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 78%;
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.75;
}

.msg.user .bubble {
  background: color-mix(in srgb, var(--cyan) 9%, transparent);
  border: 1px solid color-mix(in srgb, var(--cyan) 32%, transparent);
  color: var(--text-hi);
  border-bottom-right-radius: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg.assistant .bubble {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-bottom-left-radius: 4px;
}

/* 归纳跳转定位后的高亮 */
.msg.flash .bubble {
  animation: msg-flash 1.6s ease-out;
}

@keyframes msg-flash {
  0% {
    border-color: var(--cyan);
    box-shadow: var(--glow-cyan);
  }
  100% {
    border-color: var(--line);
    box-shadow: none;
  }
}

.cmd-tag,
.cat-chip {
  display: inline-block;
  font-family: var(--font-tech);
  font-size: 10px;
  border: 1px solid var(--line-bright);
  padding: 1px 8px;
  border-radius: 999px;
  margin-right: 8px;
  vertical-align: 2px;
}

.cmd-tag {
  color: var(--cyan);
}

.cat-chip {
  color: var(--text-dim);
  border-color: var(--line);
}

.cat-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  margin-right: 5px;
  vertical-align: 1px;
}

.thinking {
  color: var(--text-dim);
  font-size: 13px;
}

.dots {
  animation: mg-blink 1.2s steps(1) infinite;
}

.cursor {
  display: inline-block;
  animation: mg-blink 1s steps(1) infinite;
  color: var(--cyan);
  margin-left: 2px;
}

/* ---------- 输入区 ---------- */
.input-bar {
  border-top: 1px solid var(--line);
  background: var(--bg-panel);
  padding: 12px 22px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.input-row {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.input {
  flex: 1;
  resize: none;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 14px;
  line-height: 1.6;
  padding: 11px 14px;
  outline: none;
  max-height: 160px;
  transition:
    border-color var(--dur-fast),
    box-shadow var(--dur-fast);
}

.input:focus {
  border-color: var(--line-bright);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cyan) 10%, transparent);
}

.input::placeholder {
  color: var(--text-dim);
}

.send {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 11px 26px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 14px;
  letter-spacing: 0.1em;
  transition: all var(--dur-fast) var(--ease-out);
}

.send:hover:not(:disabled) {
  background: color-mix(in srgb, var(--cyan) 18%, transparent);
  box-shadow: var(--glow-cyan);
}

.send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 停止生成态:暖黄色警示,点击中断当前回答 */
.send.is-stop {
  color: #ffd166;
  border-color: rgba(255, 209, 102, 0.5);
  background: rgba(255, 209, 102, 0.1);
}

.send.is-stop:hover {
  background: rgba(255, 209, 102, 0.18);
  box-shadow: 0 0 12px rgba(255, 209, 102, 0.25);
}

/* ---------- 指令栏(位于输入行下方) ---------- */
.commands {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.cmd-label {
  color: var(--text-dim);
  font-size: 10px;
  margin-right: 4px;
}

.cmd {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 5px 13px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  letter-spacing: 0.05em;
  transition: all var(--dur-fast) var(--ease-out);
}

.cmd:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
  transform: translateY(-2px);
}

.cmd-icon {
  font-size: 11px;
  color: var(--cyan);
}

/* ---------- 附件 ---------- */
.attach-wrap {
  position: relative;
  flex-shrink: 0;
}

.mic.is-on {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.pop-overlay {
  position: fixed;
  inset: 0;
  z-index: 30;
}

.attach-pop {
  position: absolute;
  bottom: calc(100% + 10px);
  left: 0;
  z-index: 31;
  min-width: 220px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  backdrop-filter: blur(10px);
  box-shadow: var(--glow-cyan);
}

.attach-btn {
  display: flex;
  align-items: center;
  gap: 10px;
  background: transparent;
  border: none;
  color: var(--text);
  padding: 9px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  text-align: left;
  white-space: nowrap;
  transition: all var(--dur-fast);
}

.attach-btn:hover {
  color: var(--cyan);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.attach {
  margin-bottom: 6px;
}

.attach-img {
  display: block;
  max-width: 220px;
  max-height: 160px;
  border-radius: 8px;
  border: 1px solid var(--line-bright);
}

.attach-file {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 12px;
}

.af-icon {
  font-size: 18px;
}

.af-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.af-name {
  font-size: 12.5px;
  color: var(--text-hi);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.af-size {
  font-size: 11px;
  color: var(--text-dim);
  font-family: var(--font-tech);
}

.af-preview {
  margin-top: 6px;
  max-width: 420px;
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-dim);
  background: var(--bg-void);
  border: 1px dashed var(--line);
  border-radius: 6px;
  padding: 6px 10px;
  white-space: pre-wrap;
  word-break: break-word;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ---------- 拖拽导入遮罩 ---------- */
.drop-mask {
  position: absolute;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--bg-void) 72%, transparent);
  backdrop-filter: blur(2px);
  pointer-events: none;
}

.drop-box {
  padding: 34px 56px;
  border: 2px dashed var(--cyan);
  border-radius: 14px;
  color: var(--cyan);
  font-size: 15px;
  letter-spacing: 0.08em;
  background: color-mix(in srgb, var(--cyan) 6%, transparent);
  box-shadow: var(--glow-cyan);
}

/* ---------- 语音 ---------- */
.dots-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 5px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  letter-spacing: 0.08em;
  transition: all var(--dur-fast) var(--ease-out);
}

.dots-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.mic {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  color: var(--text-dim);
  cursor: pointer;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

/* 语音输入中的麦克风与📓念法本子(本子仅语音中弹出) */
.mic-wrap {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.tips-btn {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--bg-card);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 17px;
  flex-shrink: 0;
  transition: all var(--dur-fast) var(--ease-out);
  animation: tips-pop 0.25s var(--ease-out);
}

.tips-btn:hover {
  box-shadow: var(--glow-cyan);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

@keyframes tips-pop {
  from {
    transform: scale(0.5);
    opacity: 0;
  }
}

.mic svg {
  width: 20px;
  height: 20px;
  stroke: currentColor;
  fill: none;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.mic:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.mic.listening {
  color: var(--danger);
  border-color: color-mix(in srgb, var(--danger) 60%, transparent);
  box-shadow: 0 0 12px color-mix(in srgb, var(--danger) 35%, transparent);
  animation: mg-pulse 1.1s ease-in-out infinite;
}

.voice-toggle {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.voice-label {
  color: var(--text-dim);
  font-size: 12px;
}

.switch {
  width: 34px;
  height: 18px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.15);
  border: 1px solid var(--line);
  position: relative;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.switch .knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--text-dim);
  transition: all var(--dur-fast) var(--ease-out);
}

.switch.on {
  background: rgba(77, 214, 255, 0.25);
  border-color: var(--line-bright);
}

.switch.on .knob {
  left: 18px;
  background: var(--cyan);
}

.dev-badge {
  font-size: 10px;
  font-family: var(--font-tech);
  color: var(--magenta);
  border: 1px solid rgba(255, 77, 210, 0.4);
  border-radius: 999px;
  padding: 0 6px;
}
</style>
