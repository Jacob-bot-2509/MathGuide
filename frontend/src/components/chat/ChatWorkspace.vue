<script setup lang="ts">
/**
 * 聊天工作区(学习辅助 / 科学研究共用外壳)。
 *
 * 两个板块的用户界面与交互完全一致,但会话、归纳本、回收站记录与后端链路
 * 按 workspace 完全隔离:学习区只走学习链路,科研区独占研究检索链路。
 *
 * 会话架构(上下文栈):
 * - 每次进入页面都开启全新会话;旧会话自动归档,
 *   在问题归纳面板按板块检索,可随时跳回原上下文。
 * - 每个会话归属一个高等数学板块;首次提问时绑定板块。
 * - 检测到与当前会话不同类型的问题 → 先检索同板块旧会话(上下文栈),
 *   命中则切回该会话延续上下文,否则新开一个会话;
 *   同类型问题的延续拓展 → 保持当前会话,避免不同类型问题相互纠缠。
 * - 所有会话持久化到 localStorage(记忆功能),按工作区分键;
 *   问题归纳面板按板块汇总,点击问题可跳回当时所在的对话。
 *
 * 回复由后端 LLM 流式生成(services/chatService,SSE 契约);
 * 问题分类由前端关键词预判,后端路由做最终裁决。
 */
import { computed, defineAsyncComponent, markRaw, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import MathText from '@/components/chat/MathText.vue'
import DiagramBlockView from '@/components/diagram/DiagramBlock.vue'
import DiagramBoundary from '@/components/diagram/DiagramBoundary.vue'
import { appendDiagram, splitMessageBlocks, type DiagramBlock } from '@/utils/diagramSpec'
import { planDiagram } from '@/services/diagramService'
import CategoryPanel from '@/components/chat/CategoryPanel.vue'
import ResearchScopePanel from '@/components/chat/ResearchScopePanel.vue'
import ResearchArchivePanel from '@/components/chat/ResearchArchivePanel.vue'
import PaperWorkspace from '@/components/research/PaperWorkspace.vue'
import PaperImportPrompt from '@/components/research/PaperImportPrompt.vue'
import TodoPanel from '@/components/chat/TodoPanel.vue'
import AnalysisPanel from '@/components/chat/AnalysisPanel.vue'
import DocModal from '@/components/chat/DocModal.vue'
import TodoReminder from '@/components/chat/TodoReminder.vue'
import NotebookPanel from '@/components/chat/NotebookPanel.vue'
import FormulaPanel from '@/components/chat/FormulaPanel.vue'
import SpeechTips from '@/components/chat/SpeechTips.vue'
import MgSwitch from '@/components/common/MgSwitch.vue'
import { COMMANDS, RESEARCH_COMMANDS } from '@/utils/commands'
import { catName, cmdDefault, cmdHint, cmdName, t } from '@/utils/i18n'
import {
  requestIntuition,
  type ChatMeta,
} from '@/services/chatService'
import { getResearchTable } from '@/services/researchTableService'
import { getResearchDocMeta, uploadTempPaper, type PaperAction, type ResearchDoc } from '@/services/researchService'
import { deletePaperHistory, importTempPaper } from '@/services/literatureService'
import { downloadBlob, exportSurveyPdf } from '@/services/docService'
import { CATEGORIES, DISPLAY_KEYS, FALLBACK_CATEGORY, categoryByKey, classifyQuestion, isChitchat } from '@/utils/classifier'
import { buildChapterMarkdown, chapterKey, locateChapter, sliceChapter, withRanges } from '@/utils/bookChapters'
import { getCachedGuide, getCachedToc, loadBook, saveGuide, saveToc, touchBook } from '@/utils/bookStore'
import { historyQa } from '@/utils/docHistory'
import { detectAmbiguous, topicById, type AmbiguousOption } from '@/utils/ambiguous'
import { usePaperChat } from '@/composables/usePaperChat'
import { settingsState } from '@/stores/settings'
import { isAllSelected, scopeForRequest, selectedSources } from '@/stores/researchScope'
import {
  MAX_SESSIONS,
  sessionStore,
  type ChatMsg,
  type ChatSession,
  type Workspace,
} from '@/stores/sessions'
import { addToTrash } from '@/stores/trash'
import { notebookStore } from '@/stores/notebook'
import { setTodoWorkspace } from '@/stores/todo'
import { showToast } from '@/utils/toast'
import { chapterNameFromCmd, chapterPageFromCmd } from '@/utils/cmdLink'
import { splitStableBlocks } from '@/utils/mathBlocks'
import { useChatAttachments } from '@/composables/useChatAttachments'
import { useSpeechInput } from '@/composables/useSpeechInput'
import { useChatStream } from '@/composables/useChatStream'
import { useResearchSplit } from '@/composables/useResearchSplit'
import { useDiagramFocus } from '@/composables/useDiagramFocus'
import { SPLIT_MIN_WIDTH } from '@/utils/splitPane'

const props = withDefaults(defineProps<{ workspace?: Workspace }>(), { workspace: 'learn' })

const router = useRouter()
const route = useRoute()

/** 科研检索分栏:懒加载整页检索组件,分栏与独立页共用同一套逻辑 */
const ResearchSearchView = defineAsyncComponent(
  () => import('@/views/ResearchSearchView.vue'),
)

const workspaceBodyRef = ref<HTMLElement | null>(null)
const listEl = ref<HTMLDivElement | null>(null)
const focusCloseEl = ref<HTMLButtonElement | null>(null)

/* 科研检索右侧分栏:开关、比例、拖拽与本地记忆都交给 composable */
const {
  searchOpen,
  splitResizing,
  splitRatio,
  clampSplit,
  startSplitDrag,
  nudgeSplit,
  resetSplit,
  closeSplitIfNarrow,
} = useResearchSplit({ bodyRef: workspaceBodyRef })
const searchPaneRef = ref<{
  locateForQuestion: (q: string) => Promise<void>
  reloadDocs: () => Promise<void>
  applyPaperActions: (actions: PaperAction[], requestId?: string) => Promise<void>
  openDocForActions: (
    docId: string, title: string, actions: PaperAction[], requestId?: string,
  ) => Promise<void>
} | null>(null)
const currentPaper = ref<{ docId: string; title: string } | null>(null)
/** 拖入本次对话的论文:直接作为对话上下文,结束时再询问是否入库。 */
const stagedPaper = ref<{ docId: string; title: string } | null>(null)
const stagedPapers = ref<Array<{
  docId: string
  title: string
  pages: number
  msgId: number
}>>([])
const importPromptOpen = ref(false)
const importPromptBusy = ref(false)
let importPromptResolve: ((proceed: boolean) => void) | null = null
/** 从数据表页带过来的表:作为对话上下文,随消息发送 tableId */
type RegressionSpec = {
  x: string[]
  y: string
  model: 'ols' | 'poly'
  degree?: number
  tableUpdatedAt?: number
}
const tableContext = ref<{
  id: string; title: string; regression?: RegressionSpec
} | null>(null)
const researchDiagrams = ref(false)

function onPaperChange(paper: { docId: string; title: string } | null): void {
  currentPaper.value = paper
  if (paper) stagedPaper.value = null
}

/** 论文动作与流式入口:和 PaperWorkspace 共用同一套动作帧处理。
 *  只有科研区有论文上下文;学习区 getTarget 恒为 null,不会触发论文动作。 */
const paperChat = usePaperChat({
  getTarget: () => (isResearch.value
    ? currentPaper.value || stagedPaper.value
    : null),
  applyActions: (target, actions, requestId) => {
    void applyPaperActionsFromModel(actions, requestId, target)
  },
})

/** 模型完成入库:更新拖入论文状态,刷新档案/检索页,后续按库内论文处理。 */
function markPaperImported(info: {
  docId: string; title?: string; status?: string; reason?: string
}): void {
  if (!info?.docId) return
  const paper = stagedPapers.value.find((item) => item.docId === info.docId)
  if (paper) {
    const msg = findMessage(paper.msgId)
    if (msg?.paperImport) {
      msg.paperImport.status = info.status === 'imported' ? 'imported' : 'pending'
    }
    if (info.title) paper.title = info.title
  }
  if (stagedPaper.value?.docId === info.docId && info.title) {
    stagedPaper.value = { ...stagedPaper.value, title: info.title }
  }
  if (info.status === 'imported') {
    showToast(t('learn.paperImported'))
    void searchPaneRef.value?.reloadDocs()
    void archivePanelRef.value?.reload?.()
  } else if (info.status === 'failed') {
    showToast(info.reason || t('learn.paperImportFail'))
  }
  if (!flushSessions(true)) showToast(t('learn.toastStorage'))
}

async function loadTableContext(): Promise<void> {
  const tableId = typeof route.query.tableId === 'string' ? route.query.tableId : ''
  if (!tableId || !isResearch.value) return
  try {
    const table = await getResearchTable(tableId)
    let regression: RegressionSpec | undefined
    if (route.query.regression === '1') {
      try {
        const raw = sessionStorage.getItem(`mg-regression-${table.id}`)
        if (raw) {
          const parsed = JSON.parse(raw) as RegressionSpec
          if (Array.isArray(parsed.x) && parsed.y && parsed.model) regression = parsed
        }
      } catch {
        regression = undefined
      }
    }
    tableContext.value = { id: table.id, title: table.title, regression }
  } catch {
    tableContext.value = null
  }
}

/** 检索按钮:按设置与本机宽度选择分栏或独立页 */
function openResearchSearch(): void {
  if (!isResearch.value) return
  // 图解放大占用右侧;打开检索前先退出放大,避免两个分栏抢同一侧。
  if (focusDiagram.value) {
    closeDiagramFocus({ restoreSearch: false })
  }
  if (settingsState.researchSearchMode === 'page' || window.innerWidth < SPLIT_MIN_WIDTH) {
    router.push('/research/search')
    return
  }
  searchOpen.value = !searchOpen.value
  if (searchOpen.value) {
    nextTick(() => {
      splitRatio.value = clampSplit(
        splitRatio.value, workspaceBodyRef.value?.clientWidth ?? 0)
    })
  }
}

function onSplitAsk(prompt: string): void {
  if (prompt) send(prompt)
}

/* ---------- 图解放大 ---------- */
/* 浮层几何、手势、宽屏分栏与关闭后的焦点还原都在 composable 里;
   消息列表与检索开关作为依赖注入,组件只做接线。 */
const {
  focusDiagram,
  diagramSplitResizing,
  searchWasOpen,
  isNarrow,
  focusPanel,
  focusPaneStyle,
  isFocused,
  openDiagramFocus,
  closeDiagramFocus,
  onChatPaneClick,
  onRootClick,
  startDiagramSplitDrag,
  nudgeDiagramSplit,
  resetDiagramSplit,
  reclampSplitIfWide,
  onDiagramPointerDown,
  onDiagramPointerMove,
  onDiagramPointerUp,
  onDiagramPointerCancel,
  onFocusPointerDown,
  onFocusPointerMove,
  onFocusPointerUp,
  onFocusPointerCancel,
} = useDiagramFocus({ bodyRef: workspaceBodyRef, listEl, closeEl: focusCloseEl, searchOpen })
/** 模型动作到达:确保右侧阅读器存在,再跳页/高亮/批注。
 *  独立页面模式不强行跳转,避免打断当前对话。 */
async function applyPaperActionsFromModel(
  actions: PaperAction[],
  requestId = '',
  targetOverride: { docId: string; title?: string } | null = null,
): Promise<void> {
  if (!isResearch.value) return
  const target = targetOverride || currentPaper.value || stagedPaper.value
  if (!target) return
  if (!searchPaneRef.value) {
    if (settingsState.researchSearchMode === 'page'
      || window.innerWidth < SPLIT_MIN_WIDTH) return
    searchOpen.value = true
    for (let i = 0; i < 20 && !searchPaneRef.value; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
  }
  if (currentPaper.value) {
    await searchPaneRef.value?.applyPaperActions(actions, requestId)
  } else {
    await searchPaneRef.value?.openDocForActions(
      target.docId, target.title || '', actions, requestId)
  }
}

/** 窗口变窄时收起分栏,避免聊天区被压到不可用 */
function onWorkspaceResize(): void {
  closeSplitIfNarrow()
  reclampSplitIfWide()
}

/** 科研区:独占研究检索链路与搜索范围面板;学习区不跨区查文献 */
const isResearch = computed(() => props.workspace === 'research')


/** 触屏设备判定:手机/平板用「粘贴导入」替代拖拽(拖拽仅限电脑端) */
const isTouchDevice = window.matchMedia?.('(pointer: coarse)').matches ?? false


/* 会话上下文栈:按工作区取独立仓库,两区同号 sessionId 也不会串档 */
const store = sessionStore(props.workspace)
const sessions = toRef(store.state, 'sessions')
const activeId = toRef(store.state, 'activeId')
watch(activeId, () => {
  if (focusDiagram.value) closeDiagramFocus()
})
const { persistSessions, flushSessions, nextMsgId, nextSessionId } = store

/* 归纳本同样按工作区隔离:科研区收的题不会出现在学习区 */
const notebooks = notebookStore(props.workspace)

/* 待办也按工作区隔离:学习区的任务不会出现在科研区 */
setTodoWorkspace(props.workspace)

/* 指令栏:学习区不显示搜索范围;科研区不设问题记录,改为研究档案 */
const commands = computed(() =>
  isResearch.value
    ? RESEARCH_COMMANDS
    : COMMANDS.filter((c) => c.key !== '搜索范围'),
)
const input = ref('')
/** 浮层面板统一开关:同一时间只允许一个面板展开(点开新的自动收起旧的),
    关闭后其余按钮才可点(全屏遮罩拦截) */
type PanelKind = 'summary' | 'scope' | 'notebook' | 'formula' | 'todo' | 'archive' | 'analysis'
const activePanel = ref<PanelKind | null>(null)
const archivePanelRef = ref<InstanceType<typeof ResearchArchivePanel> | null>(null)
const paperDocId = ref<string | null>(null)

function openPaperWorkspace(doc: ResearchDoc): void {
  // 论文工作台及其论文图解只属于科学研究;学习辅助没有论文图鉴。
  if (!isResearch.value) return
  activePanel.value = null
  paperDocId.value = doc.id
}
const docOpen = ref(false)

function closePanel(): void {
  if (activePanel.value === 'archive' && archivePanelRef.value && !archivePanelRef.value.confirmClose()) return
  activePanel.value = null
}

function togglePanel(kind: PanelKind) {
  if (activePanel.value === 'archive' && archivePanelRef.value && !archivePanelRef.value.confirmClose()) return
  tipsOpen.value = false
  activePanel.value = activePanel.value === kind ? null : kind
}

/** 面板锚点:对齐所属按钮(相对 .learn 的 left/top/width) */
const panelAnchor = ref<{ left: number; top: number; width: number } | null>(null)

/** 量取按钮位置(面板出现前调用;按钮一定在页面上,量不到则退化为不传) */
function anchorTo(selector: string, panelWidth = 560) {
  const btn = document.querySelector<HTMLElement>(selector)
  const root = document.querySelector<HTMLElement>('.learn')
  if (!btn || !root) {
    panelAnchor.value = null
    return
  }
  const b = btn.getBoundingClientRect()
  const r = root.getBoundingClientRect()
  // iPad/窄屏上指令靠边时,以按钮中心展开的面板会伸出屏幕被裁掉。
  // 这里把中心夹在 [半宽+边距, 屏宽-半宽-边距] 内:面板仍靠近按钮,
  // 但整块落在可视区内。半宽取该面板的实际最大宽度。
  const half = Math.min(panelWidth / 2, Math.max(0, (r.width - 24) / 2))
  const center = Math.min(
    Math.max(b.left - r.left + b.width / 2, half + 12),
    Math.max(half + 12, r.width - half - 12),
  )
  panelAnchor.value = { left: center, top: b.bottom - r.top, width: 0 }
}
const tipsOpen = ref(false)
const flashMsgId = ref(0)
const inputEl = ref<HTMLTextAreaElement | null>(null)

/* 教材目录优先:有书签本地出目录;无书签只读前 20 页;点章节只发该章切片。
   版本号用于缓存失效:解析口径或提示词变化时 +1。 */
const TOC_SAMPLE_PAGES = 20
const PARSER_VERSION = 1
const PROMPT_VERSION = 1
const CHAPTER_TEXT_CAP = 200_000

/* 后台流:不同会话的输出并行生成,切换界面不中断;按消息 id 索引便于精确取消 */
/* 一条回复的流式生命周期(排队/节流上屏/收尾/中断)在 composable 里;
   这里只提供依赖:会话、滚动、落盘、图解追问与真正的发请求函数。 */
const {
  streamInto,
  scheduleStream,
  cancelReply,
  stopGenerating,
  resumeReply,
  stopAllStreams,
} = useChatStream({
  workspace: () => props.workspace,
  activeSession: () => activeSession.value ?? null,
  sessions: () => sessions.value,
  pinnedToBottom: () => pinnedToBottom,
  pinToBottom: () => { pinnedToBottom = true },
  scrollBottom,
  persist: persistSessions,
  flush: () => flushSessions(true),
  toast: showToast,
  history: buildHistory,
  markPaperImported,
  requestDiagram,
  stream: paperChat.stream,
})
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

/** 生成文档「在问题归纳中选择」的数据源:与问题归纳面板同口径的历史问答 */
const docHistory = computed(() => historyQa(sessions.value))

/* ---------- 会话管理(上下文栈) ---------- */

function createSession(cat?: ChatSession['cat']): ChatSession {
  const s: ChatSession = { id: nextSessionId(), cat, messages: [] }
  sessions.value.push(s)
  if (sessions.value.length > MAX_SESSIONS) sessions.value.shift()
  activeId.value = s.id
  persistSessions()
  return s
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
    被中断的回答(interrupted)也排除:半截话混进上下文,模型
    会把它当成完整的一轮去理解,徒增困惑。
    上限 16 条:更早的对话由后端滚动摘要压缩,早期上下文不丢失 */
function buildHistory(session: ChatSession, beforeId?: number): ChatMeta['history'] {
  const end = beforeId === undefined
    ? session.messages.length - 1
    : session.messages.findIndex((message) => message.id === beforeId)
  const upTo = end >= 0 ? session.messages.slice(0, end) : session.messages.slice(0, -1)
  return upTo
    .filter((m) => !m.streaming && !m.clarify && m.content && !m.interrupted && !m.stopped)
    .slice(-16)
    .map((m) => ({ role: m.role, content: (m.attachment?.text || m.content).slice(0, 400) }))
}

function clarifyScope(topicId: string): string {
  const topic = topicById(topicId)
  if (!topic) return ''
  return settingsState.language === 'en' ? topic.scope.en : topic.scope.zh
}

function clarifyOptions(topicId: string): AmbiguousOption[] {
  return topicById(topicId)?.options ?? []
}

function clarifyLabel(option: AmbiguousOption): string {
  return settingsState.language === 'en' ? option.label.en : option.label.zh
}

function clarifyHint(option: AmbiguousOption): string {
  return settingsState.language === 'en' ? option.hint.en : option.hint.zh
}

/** 用户选定跨板块方向后:把澄清气泡原地变成流式回答 */
function pickClarify(msg: ChatMsg, optionIndex: number): void {
  const clarity = msg.clarify
  const topic = clarity ? topicById(clarity.topicId) : null
  const option = topic?.options[optionIndex]
  if (!clarity || !topic || !option) return
  const session = sessions.value.find((item) => item.messages.some((message) => message.id === msg.id))
  if (!session) return

  const cat = categoryByKey(option.key)
  if (cat) session.cat = cat
  msg.clarify = undefined
  msg.content = ''
  msg.streaming = true
  msg.thinking = true

  const zh = settingsState.language !== 'en'
  const label = zh ? option.label.zh : option.label.en
  const hint = zh ? option.hint.zh : option.hint.en
  const prompt = zh
    ? `${clarity.question}\n\n[范围] 请从${label}角度回答,聚焦:${hint}。`
    : `${clarity.question}\n\n[Scope] Answer from the ${label} perspective, focusing on: ${hint}.`
  const history = buildHistory(session, msg.id)
  activeId.value = session.id
  pinnedToBottom = true
  streamInto(session, msg, prompt, {
    sessionId: session.id,
    categoryKey: option.key,
    history,
  })
  persistSessions()
  scrollBottom()
}


const exportMenu = ref<number | null>(null)
/** 正在生成 PDF 的研究消息 id(按钮转「生成中…」) */
const exportingMsg = ref<number | null>(null)

/** 导出研究综述:语言由菜单选定后执行;生成需 20~60 秒,期间按钮禁用 */
async function doExport(msg: ChatMsg, lang: 'zh' | 'en') {
  exportMenu.value = null
  if (exportingMsg.value !== null) return
  exportingMsg.value = msg.id
  try {
    const { blob } = await exportSurveyPdf(msg.content, lang)
    // 下载文件名用该消息的首行文字(通常是综述标题),非法文件名字符替换掉
    const title = (msg.content.split('\n').find((l) => l.trim()) || '研究综述')
      .slice(0, 40).replace(/[\\/:*?"<>|]/g, '_')
    downloadBlob(blob, `${title}-${lang}.pdf`)
    showToast(t('learn.exportDone'))
  } catch {
    showToast(t('learn.exportFailed'))
  } finally {
    exportingMsg.value = null
  }
}

/** 流式正文按稳定块渲染:已完成的块 props 不变,Vue 跳过重复解析/重渲染 */
function blocksOf(text: string): string[] {
  return splitStableBlocks(text)
}

/** 消息正文按图解锚点切成文本/图块;文本仍走稳定块渲染。 */
function messageBlocks(msg: ChatMsg): Array<{
  key: string
  kind: 'text' | 'diagram'
  text?: string
  diagram?: DiagramBlock
}> {
  const out: Array<{
    key: string
    kind: 'text' | 'diagram'
    text?: string
    diagram?: DiagramBlock
  }> = []
  splitMessageBlocks(msg.content, msg.diagrams).forEach((segment, si) => {
    if (segment.kind === 'diagram') {
      out.push({ key: `d-${si}-${segment.diagram.id}`, kind: 'diagram', diagram: segment.diagram })
      return
    }
    blocksOf(segment.text).forEach((text, ti) => {
      out.push({ key: `t-${si}-${ti}`, kind: 'text', text })
    })
  })
  return out
}

const diagramBusy = ref<number | null>(null)

function previousUserMessage(msg: ChatMsg): ChatMsg | undefined {
  for (const session of sessions.value) {
    const index = session.messages.findIndex((item) => item.id === msg.id)
    if (index < 0) continue
    return [...session.messages.slice(0, index)].reverse().find((item) => item.role === 'user')
  }
  return undefined
}

function previousQuestion(msg: ChatMsg): string {
  return previousUserMessage(msg)?.content || ''
}

/** 上一问是寒暄/闲聊时,回答只做对话,不提供图解与直觉解释入口。 */
function isChitchatTurn(msg: ChatMsg): boolean {
  return Boolean(previousUserMessage(msg)?.chitchat)
}

function hasDiagram(msg: ChatMsg): boolean {
  return !!msg.diagrams?.length
}

async function requestDiagram(
  msg: ChatMsg, question = '', silent = false,
): Promise<void> {
  const prompt = question || previousQuestion(msg)
  if (diagramBusy.value === msg.id || !msg.content.trim() || !prompt.trim()) return
  // 已有图解(自动或手动):直接复用已存快照,不再调模型加图。
  if (hasDiagram(msg)) return
  diagramBusy.value = msg.id
  try {
    const paperId = currentPaper.value?.docId || stagedPaper.value?.docId
    const spec = await planDiagram({
      question: prompt,
      answer: msg.content,
      paperId,
      tableId: isResearch.value ? tableContext.value?.id : undefined,
      mode: isResearch.value ? 'research' : 'learn',
      regression: isResearch.value ? tableContext.value?.regression : undefined,
    })
    if (!spec) {
      if (!silent) showToast(t('diagram.fail'))
      return
    }
    msg.diagrams = markRaw(appendDiagram(msg.diagrams, {
      id: `manual-${msg.id}-${Date.now()}`,
      anchorIndex: msg.content.length,
      spec,
    }))
    persistSessions()
  } catch {
    if (!silent) showToast(t('diagram.fail'))
  } finally {
    diagramBusy.value = null
  }
}

const intuitionBusy = ref<number | null>(null)

/** 按需生成直观解释;已有内容时再次点击 = 换个说法(跳过服务端缓存)。 */
function requestIntuitionFor(msg: ChatMsg): void {
  const question = previousQuestion(msg)
  if (!question || intuitionBusy.value === msg.id || !msg.content.trim()) return
  const refresh = !!msg.intuition
  intuitionBusy.value = msg.id
  let acc = ''
  requestIntuition(question, msg.content, refresh, {
    onDelta: (chunk) => {
      acc += chunk
      msg.intuition = acc
    },
    onDone: (full, complete) => {
      if (complete && full) msg.intuition = full
      else if (acc) msg.intuition = acc
      persistSessions()
      intuitionBusy.value = null
    },
    onError: () => {
      showToast(t('intuition.fail'))
    },
  })
}


function send(text?: string, cmd?: string, extra?: { pointId?: string }) {
  let content = (text ?? input.value).trim()
  if (!content) return
  // 阅读器打开时:先请求当前论文的命中段落,阅读器会滚到对应页并高亮。
  // 后端 paper_actions 到达后会以模型定位结果覆盖,两条路径都保留。
  if (isResearch.value && currentPaper.value && !cmd) {
    void searchPaneRef.value?.locateForQuestion(content)
  }

  // 寒暄/闲聊:不分类、不切换或新开会话,只就话答话
  const chitchat = isChitchat(content)
  // 科研区是一条持续对话:检索、定位、批注都依赖当前上下文,
  // 不能因为问题换了板块就被分类器切到旧会话或新开对话。
  // 学习区仍保留按板块切换会话的旧行为。
  const keepCurrentSession = isResearch.value
  // 跨板块知识点:裸词先问方向,不要在用户没选之前就绑定板块
  const ambiguous = !isResearch.value && !cmd && !chitchat ? detectAmbiguous(content) : null
  const catInfo = chitchat || ambiguous ? undefined : classifyQuestion(content)

  // 会话选择:同类型延续当前会话;不同类型检索同板块旧会话,否则新开;
  // 闲聊沿用当前会话(无会话则开一个未归类会话,不绑定板块、不进归纳面板)
  let session = activeSession.value
  if (!session) session = createSession(catInfo)

  if (catInfo) {
    if (!session.cat) {
      // 新会话首次提问:绑定板块
      session.cat = catInfo
    } else if (session.cat.key !== catInfo.key && !keepCurrentSession) {
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

  // 绑定到最终会话:板块切换可能把 session 换成已有会话
  if (extra?.pointId) session.pointId = extra.pointId

  // 新问题进来时丢弃未回答的澄清气泡:同一时刻只保留一个待选方向
  if (session.messages.some((m) => m.clarify)) {
    session.messages = session.messages.filter((m) => !m.clarify)
  }

  // 章节知识导航:教材书库优先(目录优先/按章切片);旧 text 教材仍随指令携带正文
  if (cmd === '章节知识导航') {
    const book = latestBook(session)
    if (book) {
      startBookNav(content, book, session)
      return
    }
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

  // 跨板块裸词:先渲染一张选择卡,用户选完再请求后端
  if (ambiguous) {
    session.messages.push({
      id: nextMsgId(),
      role: 'assistant',
      content: '',
      clarify: { topicId: ambiguous.id, question: content },
    })
    persistSessions()
    scrollBottom()
    return
  }

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
    pointId: extra?.pointId ?? session.pointId,
    history,
    // 搜索范围只属于科研链路:学习区不传,避免误触发跨区文献检索
    sources: isResearch.value ? scopeForRequest() : undefined,
    paperId: isResearch.value
      ? (stagedPaper.value?.docId || currentPaper.value?.docId)
      : undefined,
    tableId: isResearch.value ? tableContext.value?.id : undefined,
    tableRegression: isResearch.value ? tableContext.value?.regression : undefined,
    diagrams: isResearch.value ? researchDiagrams.value : undefined,
  })
}

/** 点击指令:直接执行对应功能 */
function runCommand(cmd: string) {
  // 生成文档 = 本地弹窗:按当前对话/问题归纳/独立要求生成,不走聊天流
  if (cmd === '生成文档') {
    docOpen.value = true
    activePanel.value = null
    tipsOpen.value = false
    return
  }
  // 问题记录 = 本地归纳本:直接展示,不走后端
  if (cmd === '问题记录') {
    showNotebook()
    return
  }
  // 搜索范围 = 本地设置(平台勾选):仅科研区有该链路,学习区忽略
  if (cmd === '搜索范围') {
    if (!isResearch.value) return
    anchorTo('.cmd[data-cmd="搜索范围"]', 340)
    togglePanel('scope')
    return
  }
  // 研究档案 = 科研区的本地项目档案:打开面板,不发请求
  if (cmd === '研究档案') {
    anchorTo('.cmd[data-cmd="研究档案"]', 640)
    togglePanel('archive')
    return
  }
  // 公式查询手册 = 板块词条面板:选板块后发该板块公式的提问
  if (cmd === '公式查询手册') {
    anchorTo('.cmd[data-cmd="公式查询手册"]', 420)
    togglePanel('formula')
    return
  }
  // 待办清单 = 本地任务面板:草稿/日程,不发请求
  if (cmd === '待办清单') {
    anchorTo('.cmd[data-cmd="待办清单"]', 560)
    togglePanel('todo')
    return
  }
  // 学习分析 = 本地快照面板:先看覆盖与薄弱点,再由用户决定是否让模型分析
  if (cmd === '学习分析') {
    anchorTo('.cmd[data-cmd="学习分析"]', 420)
    togglePanel('analysis')
    return
  }
  // 章节知识导航 = 教材书库:有书签本地出目录,无书签只送前 20 页
  if (cmd === '章节知识导航') {
    const session = activeSession.value
    const book = session ? latestBook(session) : null
    if (session && book) {
      startBookNav(input.value.trim() || cmdDefault(cmd) || cmd, book, session)
      return
    }
  }
  // 输入为空用指令默认问题;不清空输入,由 send 在成功发出后统一清空
  const text = input.value.trim() || cmdDefault(cmd) || cmd
  send(text, cmd)
}

/** 在分析面板点「让 MG 分析」:关闭面板,把分析请求发进聊天流。 */
function runLearningAnalysis() {
  activePanel.value = null
  const text = cmdDefault('学习分析') || '分析我的学习进度'
  send(text, '学习分析')
}

/** 新建对话:当前会话与其进行中的输出原样保留(后台继续生成),切换至新会话 */
async function newConversation() {
  if (!(await askPendingPapers())) return
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
    // 回收站恢复按记录写回原工作区,不会串到另一区
    workspace: props.workspace,
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
  activePanel.value = null
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

interface SessionBook {
  bookId: string
  bookPages?: number
  bookOutline?: boolean
}

/** 会话内最新的教材 PDF 书库引用;旧版 text 教材返回 null */
function latestBook(session: ChatSession): SessionBook | null {
  for (const m of [...session.messages].reverse()) {
    const attachment = m.attachment
    if (m.role === 'user' && attachment?.bookId) {
      return {
        bookId: attachment.bookId,
        bookPages: attachment.bookPages,
        bookOutline: attachment.bookOutline,
      }
    }
  }
  return null
}

/** 流结束后写缓存:错误提示不缓存,避免把失败结果固化 */
function cacheStreamResult(reply: ChatMsg, save: (content: string) => void): void {
  const stop = watch(() => reply.streaming, (streaming) => {
    if (streaming) return
    stop()
    if (reply.content && !reply.content.startsWith('⚠')) save(reply.content)
  })
}

/** 章节导航:书签本地出目录;无书签只送前 20 页,结果按哈希缓存 */
function startBookNav(text: string, book: SessionBook, session: ChatSession): void {
  if (session.messages.some((m) => m.streaming)) {
    showToast(t('learn.toastBusy'))
    return
  }
  input.value = ''
  activePanel.value = null
  session.messages.push({ id: nextMsgId(), role: 'user', content: text, cmd: '章节知识导航' })
  const reply: ChatMsg = { id: nextMsgId(), role: 'assistant', content: '', nav: 'list' }
  session.messages.push(reply)
  const live = session.messages[session.messages.length - 1]
  persistSessions()
  scrollBottom()

  void (async () => {
    let stored = null
    try {
      stored = await loadBook(book.bookId)
    } catch {
      stored = null
    }
    if (!stored) {
      live.content = t('learn.bookCacheLost')
      persistSessions()
      return
    }
    void touchBook(book.bookId)
    if (stored.outline.length) {
      live.content = buildChapterMarkdown(withRanges(stored.outline, stored.pages.length))
      persistSessions()
      scrollBottom()
      return
    }
    const cached = await getCachedToc(book.bookId, PARSER_VERSION)
    if (cached) {
      live.content = cached
      persistSessions()
      scrollBottom()
      return
    }
    const sample = stored.pages.slice(0, TOC_SAMPLE_PAGES).join('\n')
    if (!sample.trim()) {
      live.content = t('learn.bookNoToc')
      persistSessions()
      return
    }
    live.streaming = true
    live.thinking = true
    persistSessions()
    scrollBottom()
    scheduleStream(session, live, `${text}\n\n<教材文本>:\n${sample}`, 450, {
      cmd: '章节知识导航',
      sessionId: session.id,
      categoryKey: session.cat?.key,
      history: buildHistory(session),
    })
    cacheStreamResult(live, (content) => {
      void saveToc(book.bookId, PARSER_VERSION, content)
    })
  })()
}

/** 点章节:命中缓存直接显示;否则只发送该章切片(≤20 万字) */
function startChapterGuide(session: ChatSession, book: SessionBook, name: string, page: number | null, guideId: string): void {
  const reply: ChatMsg = {
    id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true,
    navGuideFor: guideId,
  }
  session.messages.push(reply)
  const live = session.messages[session.messages.length - 1]
  scrollBottom()

  void (async () => {
    let stored = null
    try {
      stored = await loadBook(book.bookId)
    } catch {
      stored = null
    }
    const unavailable = (message: string) => {
      live.content = message
      live.streaming = false
      live.thinking = false
      delete live.navGuideFor
      persistSessions()
      scrollBottom()
    }
    if (!stored) {
      unavailable(t('learn.bookCacheLost'))
      return
    }
    let prompt = `请给出「${name}」这一章的大概知识指引`
    let key = ''
    if (stored) {
      void touchBook(book.bookId)
      const chapters = withRanges(stored.outline, stored.pages.length)
      const chapter = locateChapter(stored.pages, chapters, name, page)
      if (!chapter) {
        unavailable(t('learn.bookChapterNotFound'))
        return
      }
      if (chapter) {
        key = chapterKey(chapter)
        const cached = await getCachedGuide(book.bookId, key, PROMPT_VERSION)
        if (cached) {
          live.content = cached
          live.streaming = false
          live.thinking = false
          persistSessions()
          scrollBottom()
          return
        }
        const slice = sliceChapter(stored.pages, chapter, CHAPTER_TEXT_CAP)
        prompt += `\n\n<教材文本>:\n${slice.text}`
        if (slice.truncated) prompt += '\n\n(本章过长,仅提供前 20 万字)'
      }
    }
    live.streaming = true
    live.thinking = true
    persistSessions()
    scheduleStream(session, live, prompt, 450, {
      cmd: '章节知识指引',
      sessionId: session.id,
      categoryKey: session.cat?.key,
      history: buildHistory(session),
    })
    if (key) {
      cacheStreamResult(live, (content) => {
        void saveGuide(book.bookId, key, PROMPT_VERSION, content)
      })
    }
  })()
}

/** 对话区点击:承接 MathText 渲染的 cmd:// 契约按钮(章节胶囊 / 返回黄框 / 收录是否) */
function onListClick(e: MouseEvent) {
  const el = (e.target as HTMLElement).closest<HTMLElement>('[data-mg-cmd]')
  if (!el) {
    // 点到对话区空白处:收起导出的语言菜单(菜单自身的点击被 @click.stop 拦住)
    if (exportMenu.value !== null) exportMenu.value = null
    return
  }
  const url = el.dataset.mgCmd || ''
  if (url === 'cmd://back') {
    backToNavList()
    return
  }
  if (url.startsWith('cmd://chapter/')) {
    // 模型输出的百分号编码可能是畸形的:安全解码,失败时保留原文
    const name = chapterNameFromCmd(url)
    if (name !== null) onNavChapter(name, chapterPageFromCmd(url))
    return
  }
  if (url.startsWith('cmd://point/')) {
    // 学习分析末尾的图谱定位链接:跳到图谱详情页并聚焦该知识点
    const pointId = url.slice('cmd://point/'.length)
    if (pointId) router.push({ path: '/graph', query: { focus: pointId } })
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
      notebooks.addEntry(question.content, answer.content, session.id, question.id)
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

/** 点击「问题记录」指令:打开归纳本词条面板 —— 不往对话框刷记录,
    词条滚动陈列,选中后跳回该问答所在的原对话上下文 */
function showNotebook() {
  anchorTo('.cmd[data-cmd="问题记录"]', 560)
  togglePanel('notebook')
}

/** 打开问题归纳面板(顶部「问题归纳」按钮):面板对齐按钮、从按钮下方展开 */
function toggleSummaryPanel() {
  anchorTo('.sum-btn', 320)
  togglePanel('summary')
}

/** 面板选中词条:关面板,跳回原问答上下文(会话/消息已不存在的给提示) */
function pickNotebookEntry(id: number) {
  activePanel.value = null
  jumpToNotebookEntry(id)
}

/** 公式手册选中板块:关面板,先发澄清请求——请 MG 询问想查哪个具体知识点,
    而不是一股脑列出该领域全部公式(两步流程:先问点、再作答) */
function pickFormula(key: string) {
  activePanel.value = null
  send(t('learn.formulaClarify', { cat: catName(key) }), '公式查询手册')
}

/** 归纳本条目跳回原问答(温故知新) */
function jumpToNotebookEntry(id: number) {
  const entry = notebooks.state.entries.find((e) => e.id === id)
  if (!entry) return
  const session = sessions.value.find((s) => s.id === entry.sessionId)
  if (!session || !session.messages.some((m) => m.id === entry.msgId)) {
    showToast(t('learn.toastNbGone'))
    return
  }
  jumpTo(entry.msgId)
}

/** 点击章节:已讲解过 → 直接跳转到已生成的指引;未讲解 → 请求该章知识指引 */
function onNavChapter(name: string, page: number | null = null) {
  const session = activeSession.value
  if (!session) return
  const book = latestBook(session)
  const guideId = book ? JSON.stringify([book.bookId, name, page]) : name
  const done = session.messages.find((m) => m.role === 'assistant' && m.navGuideFor === guideId && m.content)
  if (done) {
    jumpTo(done.id)
    return
  }
  if (session.messages.some((m) => m.streaming)) {
    showToast(t('learn.toastBusy'))
    return
  }
  if (book) {
    startChapterGuide(session, book, name, page, guideId)
    return
  }
  const reply: ChatMsg = {
    id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true,
    navGuideFor: name,
  }
  session.messages.push(reply)
  const live = session.messages[session.messages.length - 1]
  // 旧版 text 教材:正文已由后端按 sessionId 缓存(章节导航生成列表时入库),这里只发章节名
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

/* 附件接收(文件/拖拽/粘贴/剪贴板)在 composable 里;
   这里只接管模板要绑的事件与展示,菜单开合仍由组件自己管。 */
const {
  dragging,
  onImage,
  onFile,
  onDragOver,
  onDragLeave,
  onDropFiles,
  onPaste,
  pasteImport,
  fmtSize,
} = useChatAttachments({
  isResearch: () => isResearch.value,
  isTouchDevice,
  closeAttachMenu: () => { attachOpen.value = false },
  activeSession: () => activeSession.value ?? null,
  createSession,
  nextMsgId,
  cancelReply,
  scheduleStream,
  history: buildHistory,
  scrollBottom,
  pinToBottom: () => { pinnedToBottom = true },
  flush: () => flushSessions(true),
  toast: showToast,
  stagePaper: stagePaperFile,
})

function findMessage(id: number): ChatMsg | null {
  for (const session of sessions.value) {
    const found = session.messages.find((m) => m.id === id)
    if (found) return found
  }
  return null
}

function removeMessage(id: number): void {
  for (const session of sessions.value) {
    const index = session.messages.findIndex((m) => m.id === id)
    if (index >= 0) {
      session.messages.splice(index, 1)
      return
    }
  }
}

/** 拖入即用:临时论文直接成为本次对话的上下文,不要求先入库。 */
async function stagePaperFile(file: File): Promise<void> {
  if (!activeSession.value) return
  showToast(t('learn.paperParsing'))
  try {
    const res = await uploadTempPaper(file)
    if (res.duplicate && res.status && res.status !== 'temp') {
      showToast(t('learn.paperAlready'))
      return
    }
    const meta = await getResearchDocMeta(res.docId).catch(() => null)
    const title = meta?.title || file.name
    const pages = res.pages || meta?.pages || 0
    currentPaper.value = null
    stagedPaper.value = { docId: res.docId, title }

    const existing = stagedPapers.value.find((p) => p.docId === res.docId)
    if (existing) {
      persistSessions()
      scrollBottom(false)
      return
    }
    const session = activeSession.value
    const message: ChatMsg = {
      id: nextMsgId(),
      role: 'assistant',
      content: t('learn.paperReady'),
      paperImport: { docId: res.docId, title, pages, status: 'pending' },
    }
    session.messages.push(message)
    stagedPapers.value.push({
      docId: res.docId, title, pages, msgId: message.id,
    })
    if (!flushSessions(true)) showToast(t('learn.toastStorage'))
    scrollBottom(false)
  } catch (err) {
    const message = err instanceof Error && err.message ? err.message : 'unknown'
    showToast(t('learn.paperParseFail', { msg: message }))
  }
}

function pendingStagedPapers(): typeof stagedPapers.value {
  return stagedPapers.value.filter((paper) => {
    const msg = findMessage(paper.msgId)
    return msg?.paperImport?.status !== 'imported'
  })
}

function askPendingPapers(): Promise<boolean> {
  if (!pendingStagedPapers().length) return Promise.resolve(true)
  if (importPromptOpen.value) return Promise.resolve(false)
  importPromptOpen.value = true
  return new Promise((resolve) => {
    importPromptResolve = resolve
  })
}

async function confirmPaperChoices(
  choices: Record<string, 'import' | 'temp' | 'ignore'>,
): Promise<void> {
  if (importPromptBusy.value) return
  importPromptBusy.value = true
  const selected = { ...choices }
  const retry: typeof stagedPapers.value = []
  let completed = false
  let importedAny = false
  try {
    for (const paper of [...stagedPapers.value]) {
      const choice = selected[paper.docId] || 'import'
      const msg = findMessage(paper.msgId)
      // 模型已经完成入库的论文不再重复处理,保留其上下文。
      if (msg?.paperImport?.status === 'imported') continue
      if (choice === 'import') {
        try {
          await importTempPaper(paper.docId, undefined, true)
          if (msg?.paperImport) msg.paperImport.status = 'imported'
          importedAny = true
          showToast(t('learn.paperImported'))
        } catch {
          retry.push(paper)
          showToast(t('learn.paperImportFail'))
        }
      } else if (choice === 'temp') {
        if (msg?.paperImport) msg.paperImport.status = 'temp'
        showToast(t('learn.paperKept'))
      } else {
        try {
          await deletePaperHistory(paper.docId)
        } catch {
          /* 已入库或已删除:忽略删除失败 */
        }
        removeMessage(paper.msgId)
        showToast(t('learn.paperIgnored'))
      }
    }
    completed = retry.length === 0
    if (importedAny) await archivePanelRef.value?.reload?.()
  } finally {
    const imported = stagedPapers.value.filter((paper) => {
      const msg = findMessage(paper.msgId)
      return msg?.paperImport?.status === 'imported'
    })
    const next = [...imported, ...retry]
    const last = next[next.length - 1]
    stagedPapers.value = next
    stagedPaper.value = last ? { docId: last.docId, title: last.title } : null
    if (!flushSessions(true)) showToast(t('learn.toastStorage'))
    importPromptBusy.value = false
    importPromptOpen.value = false
    importPromptResolve?.(completed)
    importPromptResolve = null
  }
}

function cancelPaperPrompt(): void {
  if (importPromptBusy.value) return
  importPromptOpen.value = false
  importPromptResolve?.(false)
  importPromptResolve = null
}




/* ---------- 语音输入(浏览器本地识别,Chrome / Edge 可用) ---------- */
/* 识别会话、预热定时器、转写四档编排都在 composable 里;
   这里只把输入框与自动增高传进去。 */
const {
  listening,
  toggleMic,
  setModelVoice,
  dispose: disposeSpeech,
} = useSpeechInput({ input, autoGrow, toast: showToast })

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

/** 图谱详情页「前往」:消费一次 query,随后清掉,避免刷新重复发问。 */
function consumePointLink() {
  if (isResearch.value) return
  const point = typeof route.query.point === 'string'
    ? route.query.point.slice(0, 64) : ''
  if (!point || route.query.start !== '1') return
  const name = typeof route.query.name === 'string'
    ? route.query.name.slice(0, 40) : point
  router.replace({ path: '/learn' })
  nextTick(() => {
    send(t('learn.pointLessonPrompt', { name }), '知识点讲解', { pointId: point })
  })
}

function restoreStagedPapers(): void {
  const seen = new Set<string>()
  for (const session of sessions.value) {
    for (const msg of session.messages) {
      const info = msg.paperImport
      if (!info || info.status !== 'pending' || seen.has(info.docId)) continue
      seen.add(info.docId)
      stagedPapers.value.push({
        docId: info.docId,
        title: info.title,
        pages: info.pages,
        msgId: msg.id,
      })
      stagedPaper.value = { docId: info.docId, title: info.title }
    }
  }
}

onMounted(() => {
  // 每次进入页面都开启全新对话;旧会话自动归档到相应板块
  // (会话档案由 stores/sessions 在应用启动时恢复)
  sessions.value = sessions.value.filter((s) => s.cat
    || s.messages.some((m) => m.role === 'user' || m.paperImport))
  restoreStagedPapers()
  createSession()
  greet()
  consumePointLink()
  // 文献检索页「基于这些结果提问」:证据已拼好,进对话后直接发送
  if (isResearch.value) {
    const seed = sessionStorage.getItem('mg-research-seed')
    if (seed) {
      sessionStorage.removeItem('mg-research-seed')
      nextTick(() => send(seed))
    }
    void loadTableContext()
  }
  window.addEventListener('resize', onWorkspaceResize)
  window.addEventListener('beforeunload', warnPendingPapers)
})

onBeforeRouteLeave(async () => {
  if (!pendingStagedPapers().length) return true
  return askPendingPapers()
})

function warnPendingPapers(event: BeforeUnloadEvent): void {
  if (!pendingStagedPapers().length) return
  flushSessions(true)
  event.preventDefault()
  event.returnValue = ''
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWorkspaceResize)
  window.removeEventListener('beforeunload', warnPendingPapers)
  stopAllStreams()
  disposeSpeech()
  if (flashTimer) clearTimeout(flashTimer)
})
</script>

<template>
  <div class="learn" @click="onRootClick" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDropFiles">
    <header class="chat-header">
      <button class="back" @click="router.push('/home')">{{ t('common.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t(isResearch ? 'research.title' : 'learn.title') }}</span>
        <span class="tech-label sub">{{ isResearch ? 'MODULE 02 · RESEARCH' : 'MODULE 01 · LEARN' }}</span>
      </div>
      <div class="right">
        <button
          v-if="isResearch"
          class="new-btn"
          :class="{ 'new-btn--active': searchOpen }"
          @click="openResearchSearch"
        >
          {{ t('search.button') }}
        </button>
        <button v-if="isResearch" class="new-btn" @click="router.push('/research/tables')">
          {{ t('tables.entry') }}
        </button>
        <button class="new-btn" @click="newConversation">{{ t('learn.newChat') }}</button>
        <!-- 板块上下文徽章(未归类会话不显示标题) -->
        <span v-if="activeSession?.cat && activeSession.cat.key !== 'other'" class="session-chip">
          <span class="dot" :style="{ background: activeSession.cat.color }"></span>
          {{ catName(activeSession.cat.key) }}{{ t('learn.context') }}
        </span>
        <span v-else-if="!activeSession?.cat" class="session-chip session-chip--dim">{{ t('learn.newSession') }}</span>
        <button
          v-if="!isResearch"
          class="sum-btn"
          :class="{ 'sum-btn--on': activePanel === 'summary' }"
          @click="toggleSummaryPanel()"
        >
          {{ t('learn.archive') }}<span v-if="questionCount" class="sum-badge">{{ questionCount }}</span>
        </button>
        <span class="badge tech-label">{{ t(isResearch ? 'common.mgResearch' : 'common.mgLearn') }}</span>
        <button class="dots-btn" :title="t('common.settings')" @click="router.push('/settings')">···</button>
      </div>
    </header>

    <!-- 问题归纳面板:浮层形态,对齐「问题归纳」按钮,从按钮下方展开 -->
    <Transition name="cat-drop">
      <CategoryPanel
        v-if="!isResearch && activePanel === 'summary'"
        :items="summary"
        :total="questionCount"
        :left="panelAnchor?.left"
        :top="panelAnchor ? panelAnchor.top + 6 : undefined"
        :width="panelAnchor?.width"
        @close="activePanel = null"
        @jump="jumpTo"
        @delete="deleteHistory"
      />
    </Transition>


    <!-- 念法速查贴士(语音输入中点击麦克风旁的📓打开) -->
    <SpeechTips v-if="tipsOpen" @close="tipsOpen = false" />

    <!-- 对话区(当前会话) -->
    <div ref="workspaceBodyRef" class="workspace-body" :class="{ 'with-search': searchOpen, 'with-focus': focusDiagram }">
      <div class="chat-pane" @click="onChatPaneClick">
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
            <div v-if="m.paperImport" class="paper-imp">
              <div class="paper-imp-head">
                <span class="paper-imp-icon">📄</span>
                <span class="paper-imp-name" :title="m.paperImport.title">{{ m.paperImport.title }}</span>
                <span class="paper-imp-pages">{{ t('learn.paperPages', { n: m.paperImport.pages }) }}</span>
              </div>
              <p class="paper-imp-q">{{ m.content }}</p>
              <p v-if="m.paperImport.status !== 'pending'" class="paper-imp-state">
                {{ m.paperImport.status === 'imported' ? t('learn.paperImported') : t('learn.paperKept') }}
              </p>
            </div>
            <!-- 走 cmdName 而非裸键:契约键是中文,英文界面下会露出中文 -->
            <span v-if="m.role === 'user' && m.cmd" class="cmd-tag">{{ cmdName(m.cmd) }}</span>
            <span v-if="m.role === 'user' && activeSession.cat" class="cat-chip">
              <span class="cat-dot" :style="{ background: activeSession.cat.color }"></span>{{ catName(activeSession.cat.key) }}
            </span>
            <template v-if="m.role === 'assistant'">
              <span v-if="m.thinking" class="thinking">{{ t('learn.thinking') }}<span class="dots">···</span></span>
              <!-- 跨板块知识点:先选方向,再发请求 -->
              <div v-if="m.clarify" class="clarify">
                <p class="clarify-title">{{ t('clarify.title') }}</p>
                <p class="clarify-scope">{{ t('clarify.scope', { scope: clarifyScope(m.clarify.topicId) }) }}</p>
                <div class="clarify-options">
                  <button
                    v-for="(option, oi) in clarifyOptions(m.clarify.topicId)"
                    :key="`${option.key}-${oi}`"
                    class="clarify-opt"
                    type="button"
                    @click.stop="pickClarify(m, oi)"
                  >
                    <span class="co-label">{{ clarifyLabel(option) }}</span>
                    <span class="co-hint">{{ clarifyHint(option) }}</span>
                  </button>
                </div>
              </div>
              <div v-if="m.content && !m.paperImport" class="mg-blocks">
                <template v-for="block in messageBlocks(m)" :key="block.key">
                  <MathText v-if="block.kind === 'text'" :text="block.text || ''" />
                  <div
                    v-else-if="block.diagram"
                    class="diagram-embed"
                    :data-diagram-id="block.diagram.id"
                    tabindex="-1"
                    @click.stop
                    @dblclick.stop="openDiagramFocus(block.diagram, m.id)"
                    @pointerdown="onDiagramPointerDown"
                    @pointermove="onDiagramPointerMove"
                    @pointerup="onDiagramPointerUp($event, block.diagram, m.id)"
                    @pointercancel="onDiagramPointerCancel"
                  >
                    <Teleport
                      to="#mg-diagram-focus-stage"
                      :disabled="!isFocused(block.diagram)"
                    >
                      <DiagramBoundary
                        :title="block.diagram.spec.title"
                        :notes="block.diagram.spec.annotations.map((note) => note.text)"
                      >
                        <DiagramBlockView
                          :spec="block.diagram.spec"
                          :focused="isFocused(block.diagram)"
                        />
                      </DiagramBoundary>
                    </Teleport>
                    <div
                      v-if="isFocused(block.diagram)"
                      class="diagram-inline-placeholder"
                    >{{ t('diagram.focusOpened') }}</div>
                  </div>
                </template>
              </div>
              <div v-if="m.intuition" class="intuition-block">
                <div class="intuition-title">{{ t('intuition.title') }}</div>
                <MathText :text="m.intuition" />
              </div>
              <button
                v-if="m.content && !m.streaming && !m.paperImport
                  && previousQuestion(m) && !isChitchatTurn(m) && !hasDiagram(m)"
                class="diagram-btn"
                type="button"
                :disabled="diagramBusy === m.id"
                @click.stop="requestDiagram(m)"
              >{{ diagramBusy === m.id ? t('diagram.generating') : t('diagram.generate') }}</button>
              <button
                v-if="m.content && !m.streaming && !m.paperImport && previousQuestion(m) && !isChitchatTurn(m)"
                class="diagram-btn"
                type="button"
                :disabled="intuitionBusy === m.id"
                @click.stop="requestIntuitionFor(m)"
              >{{ intuitionBusy === m.id
                ? t('intuition.generating')
                : (m.intuition ? t('intuition.regenerate') : t('intuition.generate')) }}</button>
              <span v-if="m.streaming && !m.thinking" class="cursor">▍</span>
              <!-- 半截回答的标记:与完整回答同形,不点明用户看不出缺了一段 -->
              <span v-if="m.interrupted" class="cut-note">{{ t('learn.interrupted') }}</span>
              <!-- 研究综述的导出入口(仅后端标记过的研究消息显示) -->
              <template v-if="m.research && !m.streaming">
                <button
                  class="export-btn"
                  type="button"
                  :disabled="exportingMsg === m.id"
                  @click.stop="exportMenu = exportMenu === m.id ? null : m.id"
                >
                  {{ exportingMsg === m.id ? t('learn.exporting') : t('learn.exportPdf') }}
                </button>
                <div v-if="exportMenu === m.id" class="export-menu" @click.stop>
                  <span class="export-menu-title">{{ t('learn.exportLangTitle') }}</span>
                  <button type="button" @click="doExport(m, 'zh')">{{ t('learn.exportLangZh') }}</button>
                  <button type="button" @click="doExport(m, 'en')">{{ t('learn.exportLangEn') }}</button>
                </div>
              </template>
              <!-- 用户停止生成后的续写入口:右下角小按钮 -->
              <div v-if="m.stopped && m.content && !m.streaming" class="resume-row">
                <button class="resume-btn" type="button" :title="t('learn.resumeHint')" @click.stop="resumeReply(m)">
                  {{ t('learn.resume') }}
                </button>
              </div>
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
      <div v-if="isResearch && stagedPaper" class="context-chip">
        <span class="context-label">{{ t('chat.paperContext') }}</span>
        <span class="context-name" :title="stagedPaper.title">{{ stagedPaper.title }}</span>
        <button
          class="context-remove"
          :title="t('chat.removePaper')"
          @click="stagedPaper = null"
        >✕</button>
      </div>
      <div v-if="isResearch && tableContext" class="context-chip">
        <span class="context-label">{{ t('chat.tableContext') }}</span>
        <span class="context-name" :title="tableContext.title">{{ tableContext.title }}</span>
        <button
          class="context-remove"
          :title="t('chat.removeTable')"
          @click="tableContext = null"
        >✕</button>
      </div>
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
            @click="activePanel = null; tipsOpen = !tipsOpen"
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
          :placeholder="listening ? t('learn.listening') : (focusDiagram ? t('learn.placeholderFocus') : t('learn.placeholder'))"
          @input="autoGrow"
          @keydown.enter.exact.prevent="send()"
          @paste="onPaste"
        ></textarea>
        <!-- 生成中变为「停止生成」:可中断长回答,已生成内容保留 -->
        <button
          v-if="isResearch"
          class="diagram-toggle"
          :class="{ on: researchDiagrams }"
          :title="t('chat.diagramToggleHint')"
          @click="researchDiagrams = !researchDiagrams"
        >{{ t('chat.diagramToggle') }}</button>
        <button class="send" :class="{ 'is-stop': busy }" @click="busy ? stopGenerating() : send()">
          {{ busy ? t('learn.stop') : t('learn.send') }}
        </button>
      </div>
      <!-- 三个底部浮层面板:各包独立 Transition(Transition 要求恰好一个子元素);
           遮罩统一挂在页尾(见下),点任意暗处收起 -->
      <Transition name="nb-rise">
        <NotebookPanel
          v-if="activePanel === 'notebook'"
          :entries="notebooks.state.entries"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="activePanel = null"
          @pick="pickNotebookEntry"
        />
      </Transition>
      <Transition name="nb-rise">
        <FormulaPanel
          v-if="activePanel === 'formula'"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="activePanel = null"
          @pick="pickFormula"
        />
      </Transition>
      <Transition name="nb-rise">
        <ResearchScopePanel
          v-if="isResearch && activePanel === 'scope'"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="activePanel = null"
        />
      </Transition>
      <Transition name="nb-rise">
        <ResearchArchivePanel
          ref="archivePanelRef"
          v-if="isResearch && activePanel === 'archive'"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="closePanel"
          @open-doc="openPaperWorkspace"
        />
      </Transition>
      <Transition name="nb-rise">
        <TodoPanel
          v-if="activePanel === 'todo'"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="activePanel = null"
        />
      </Transition>
      <Transition name="nb-rise">
        <AnalysisPanel
          v-if="!isResearch && activePanel === 'analysis'"
          :left="panelAnchor?.left"
          :width="panelAnchor?.width"
          @close="activePanel = null"
          @analyze="runLearningAnalysis"
        />
      </Transition>

      <div class="commands">
        <span class="tech-label cmd-label">{{ t('learn.cmdLabel') }}</span>
        <button
          v-for="c in commands"
          :key="c.key"
          class="cmd"
          :class="{ 'cmd--active': c.key === '搜索范围' && !isAllSelected() }"
          :title="cmdHint(c.key)"
          :data-cmd="c.key"
          @click="runCommand(c.key)"
        >
          <span class="cmd-icon">{{ c.icon }}</span>{{ cmdName(c.key) }}
          <!-- 范围缩小到部分平台时常驻数字,提醒当前不是全平台检索 -->
          <span v-if="c.key === '搜索范围' && !isAllSelected()" class="cmd-badge">{{ selectedSources.length }}</span>
        </button>
        <span class="voice-toggle">
          <span class="voice-label">{{ t('learn.voiceLabel') }}</span>
          <MgSwitch
            size="sm"
            :model-value="settingsState.modelVoice"
            :title="t('learn.voiceHint')"
            @update:model-value="setModelVoice"
          />
          <span class="dev-badge">{{ t('common.tbd') }}</span>
        </span>
      </div>
    </footer>
      </div><!-- /chat-pane -->

      <div
        v-if="focusDiagram && !isNarrow"
        class="split-divider diagram-focus-divider"
        :class="{ dragging: diagramSplitResizing }"
        role="separator"
        aria-orientation="vertical"
        tabindex="0"
        @pointerdown="startDiagramSplitDrag"
        @click.stop
        @dblclick.stop="resetDiagramSplit"
        @keydown.left.prevent="nudgeDiagramSplit(0.02)"
        @keydown.right.prevent="nudgeDiagramSplit(-0.02)"
      ></div>
      <div
        v-if="focusDiagram && isNarrow"
        class="diagram-focus-backdrop"
        @click="closeDiagramFocus()"
      ></div>
      <aside
        ref="focusPaneEl"
        v-show="focusDiagram"
        class="diagram-focus-pane"
        :class="{
          'diagram-focus-pane--narrow': isNarrow,
          'diagram-focus-pane--fullscreen': isNarrow && focusPanel.fullscreen,
        }"
        :style="focusPaneStyle"
        :role="isNarrow ? 'dialog' : undefined"
        :aria-modal="isNarrow ? 'true' : undefined"
        :aria-label="focusDiagram?.spec.title || t('diagram.figure')"
      >
        <header
          class="diagram-focus-head"
          @pointerdown.stop="onFocusPointerDown"
          @pointermove.stop="onFocusPointerMove"
          @pointerup.stop="onFocusPointerUp"
          @pointercancel.stop="onFocusPointerCancel"
        >
          <span class="diagram-focus-title">{{ focusDiagram?.spec.title }}</span>
          <button
            ref="focusCloseEl"
            class="diagram-focus-close"
            type="button"
            :aria-label="t('common.close')"
            @pointerdown.stop
            @click="closeDiagramFocus()"
          >×</button>
        </header>
        <div
          v-for="side in ['left', 'right']"
          v-show="isNarrow && !focusPanel.fullscreen"
          :key="side"
          class="diagram-focus-edge"
          :class="`diagram-focus-edge--${side}`"
          aria-hidden="true"
          @pointerdown.stop="onFocusPointerDown"
          @pointermove.stop="onFocusPointerMove"
          @pointerup.stop="onFocusPointerUp"
          @pointercancel.stop="onFocusPointerCancel"
        ></div>
        <div
          id="mg-diagram-focus-stage"
          class="diagram-focus-stage"
        ></div>
      </aside>

      <div
        v-if="searchOpen && !focusDiagram"
        class="split-divider"
        :class="{ dragging: splitResizing }"
        role="separator"
        aria-orientation="vertical"
        tabindex="0"
        @pointerdown="startSplitDrag"
        @dblclick="resetSplit"
        @keydown.left.prevent="nudgeSplit(-0.02)"
        @keydown.right.prevent="nudgeSplit(0.02)"
      ></div>
      <aside
        v-if="searchOpen || searchWasOpen"
        v-show="searchOpen && !focusDiagram"
        class="search-pane"
        :style="{ width: `${splitRatio * 100}%` }"
      >
        <ResearchSearchView
          ref="searchPaneRef"
          embedded
          @ask="onSplitAsk"
          @paper-change="onPaperChange"
        />
      </aside>
    </div><!-- /workspace-body -->

    <!-- 浮层面板统一遮罩:压暗全屏,点任意暗处收起当前面板(收起后按钮才可点) -->
    <Transition name="mask-fade">
      <div v-if="activePanel" class="panel-overlay" @click="closePanel"></div>
    </Transition>

    <PaperImportPrompt
      v-if="importPromptOpen"
      :papers="stagedPapers"
      @confirm="confirmPaperChoices"
      @cancel="cancelPaperPrompt"
    />

    <!-- 论文工作台:研究档案「继续」进入,左对话右阅读器,第三栏结构/导图 -->
    <PaperWorkspace
      v-if="paperDocId"
      :doc-id="paperDocId"
      @close="paperDocId = null"
    />

    <!-- 生成文档:当前会话问答 / 问题归纳 / 独立要求 -->
    <DocModal
      v-if="docOpen"
      :messages="activeSession?.messages ?? []"
      :entries="notebooks.state.entries"
      :history-qa="docHistory"
      @close="docOpen = false"
    />

    <!-- 待办提醒:仅在学习辅助页挂载,满足“开场+登录+进入本页”后才提醒 -->
    <TodoReminder />
  </div>
</template>

<style scoped>
.learn {
  height: 100vh;
  /* iPad/手机 Safari 的 100vh 含工具栏区域,底部输入条会被切掉;dvh 跟随可见视口 */
  height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.workspace-body {
  flex: 1;
  min-height: 0;
  display: flex;
}

.chat-pane {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.split-divider {
  flex: none;
  width: 6px;
  cursor: col-resize;
  background: var(--line);
  position: relative;
  z-index: 3;
  touch-action: none;
}

.split-divider:hover,
.split-divider:focus-visible,
.split-divider.dragging {
  background: color-mix(in srgb, var(--cyan) 55%, transparent);
  outline: none;
}

.search-pane {
  flex: none;
  min-width: 0;
  height: 100%;
  overflow: hidden;
}

.diagram-embed {
  position: relative;
}

.diagram-inline-placeholder {
  min-height: 220px;
  margin: 12px 0 16px;
  border: 1px dashed var(--line);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-dim);
  font-size: 11px;
}

.diagram-focus-pane {
  flex: none;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #05070a;
  border-left: 1px solid var(--line);
  overflow: hidden;
  --bg-void: #05070a;
  --bg-panel: rgba(13, 18, 30, 0.92);
  --bg-card: #05070a;
  --text-hi: #e8f2ff;
  --text: #c2d2e4;
  --text-dim: #8b9bb0;
  --line: rgba(96, 165, 250, 0.18);
  --line-bright: rgba(96, 165, 250, 0.45);
  --cyan: #4dd6ff;
}

.diagram-focus-edge {
  position: absolute;
  top: 44px;
  bottom: 0;
  width: 14px;
  z-index: 1;
  touch-action: none;
}

.diagram-focus-edge--left { left: 0; }
.diagram-focus-edge--right { right: 0; }

.diagram-focus-pane--narrow {
  position: fixed;
  z-index: 45;
  border: 1px solid var(--line-bright);
  border-radius: 12px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6);
}

.diagram-focus-pane--fullscreen {
  border: 0;
  border-radius: 0;
}

.diagram-focus-pane--fullscreen .diagram-focus-head {
  padding-top: calc(8px + env(safe-area-inset-top));
}

.diagram-focus-backdrop {
  position: fixed;
  inset: 0;
  z-index: 44;
  background: rgba(3, 6, 12, 0.62);
  backdrop-filter: blur(2px);
}

.diagram-focus-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  color: var(--text);
  border-bottom: 1px solid var(--line);
  touch-action: none;
  cursor: grab;
}

.diagram-focus-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}

.diagram-focus-close {
  flex: none;
  width: 26px;
  height: 26px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-size: 18px;
  line-height: 1;
}

.diagram-focus-close:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.diagram-focus-stage {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
}

.diagram-focus-stage :deep(.diagram-block) {
  width: 100%;
  height: 100%;
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

.new-btn--active {
  background: color-mix(in srgb, var(--cyan) 18%, transparent);
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

/* 面板打开时保持高亮 */
.sum-btn--on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
  box-shadow: var(--glow-cyan);
}

/* 触屏设备没有 hover:默认样式一直偏暗,点按后才闪一下。
   iPad 等无悬停设备上常亮高亮,保留可发现性。 */
@media (hover: none) {
  .sum-btn {
    color: var(--cyan);
    border-color: var(--line-bright);
    background: color-mix(in srgb, var(--cyan) 8%, transparent);
  }
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

/* 跨板块澄清卡:给出范围 + 方向按钮 */
.clarify {
  width: min(500px, 100%);
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.clarify-title {
  margin: 0;
  color: var(--text-hi);
  font-size: 13.5px;
  line-height: 1.55;
}

.clarify-scope {
  margin: 0;
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.65;
}

.clarify-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 2px;
}

.clarify-opt {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 11px;
  text-align: left;
  color: var(--text);
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color var(--dur-fast), box-shadow var(--dur-fast);
}

.clarify-opt:hover,
.clarify-opt:focus-visible {
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
  outline: none;
}

.co-label {
  color: var(--cyan);
  font-size: 12.5px;
}

.co-hint {
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.55;
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

/* 中断标记:另起一行、弱化处理 —— 它是对这条回答的批注,不是回答本身 */
.cut-note {
  display: block;
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed var(--line);
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.5;
}

/* 停止生成后的续写入口:气泡右下角 */
.resume-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.resume-btn {
  padding: 3px 12px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  color: var(--cyan);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.resume-btn:hover {
  background: color-mix(in srgb, var(--cyan) 16%, transparent);
  box-shadow: var(--glow-cyan);
}

/* 研究综述导出:小按钮 + 语言选择菜单 */
.export-btn {
  display: inline-block;
  margin-top: 10px;
  padding: 4px 14px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  color: var(--cyan);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.export-btn:hover {
  box-shadow: var(--glow-cyan);
}

.export-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.diagram-btn {
  display: inline-block;
  margin-top: 8px;
  margin-left: 6px;
  padding: 3px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--text-dim);
  font-size: 10.5px;
  cursor: pointer;
}

.diagram-btn:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.intuition-block {
  margin-top: 10px;
  padding: 10px 12px;
  border-left: 2px solid var(--line-bright);
  background: color-mix(in srgb, var(--bg-card) 70%, transparent);
  border-radius: 0 8px 8px 0;
}

.intuition-title {
  margin-bottom: 4px;
  color: var(--cyan);
  font-size: 11px;
  letter-spacing: 0.04em;
}

.diagram-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.export-menu {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  margin-top: 6px;
  padding: 8px;
  width: fit-content;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.35);
}

.export-menu-title {
  font-size: 10.5px;
  color: var(--text-dim);
  padding: 0 6px 4px;
}

.export-menu button {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: 13px;
  padding: 5px 8px;
  border-radius: 5px;
  cursor: pointer;
}

.export-menu button:hover {
  background: rgba(96, 165, 250, 0.1);
  color: var(--cyan);
}

/* ---------- 输入区 ---------- */
.input-bar {
  position: relative; /* 问题记录面板与附件弹层以此为定位锚点 */
  border-top: 1px solid var(--line);
  background: var(--bg-panel);
  padding: 12px 22px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.workspace-body.with-focus .input-bar {
  padding: 8px 12px 10px;
  gap: 6px;
}

.workspace-body.with-focus .commands {
  flex-wrap: nowrap;
  overflow-x: auto;
  gap: 6px;
  scrollbar-width: none;
}

.workspace-body.with-focus .commands::-webkit-scrollbar {
  display: none;
}

.workspace-body.with-focus .cmd-label {
  display: none;
}

.workspace-body.with-focus .cmd {
  flex: none;
  padding: 4px 9px;
  font-size: 11px;
  white-space: nowrap;
}

.workspace-body.with-focus .input-row {
  gap: 8px;
}

.context-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  max-width: 100%;
  padding: 4px 10px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  background: color-mix(in srgb, var(--cyan) 7%, transparent);
  font-size: 11px;
}

.context-label {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 9.5px;
  letter-spacing: 0.06em;
}

.context-name {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-hi);
}

.context-remove {
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
  padding: 0 2px;
}

.context-remove:hover {
  color: var(--cyan);
}

/* 浮层面板统一全屏遮罩:压暗其余界面,面板浮在其上(两层效果),
   点任意暗处收起面板 —— 收起前其余按钮被遮罩拦截,不可点击 */
.panel-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  background: rgba(3, 6, 12, 0.55);
  backdrop-filter: blur(1.5px);
}

.mask-fade-enter-active,
.mask-fade-leave-active {
  transition: opacity 0.2s;
}

.mask-fade-enter-from,
.mask-fade-leave-to {
  opacity: 0;
}

/* 底部面板(问题记录):从下向上展开 / 从上向下收起 */
.nb-rise-enter-active {
  transition: transform 0.22s var(--ease-out), opacity 0.22s;
}

.nb-rise-leave-active {
  transition: transform 0.18s var(--ease-in), opacity 0.18s;
}

.nb-rise-enter-from,
.nb-rise-leave-to {
  transform: translateY(26px);
  opacity: 0;
}

/* 顶部面板(问题归纳):从按钮下方落下展开 / 向上收起 */
.cat-drop-enter-active {
  transition: transform 0.22s var(--ease-out), opacity 0.22s;
}

.cat-drop-leave-active {
  transition: transform 0.18s var(--ease-in), opacity 0.18s;
}

.cat-drop-enter-from,
.cat-drop-leave-to {
  transform: translateY(-12px);
  opacity: 0;
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

.diagram-toggle {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 11px 12px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
}

.diagram-toggle.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
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

/* 搜索范围已缩小到部分平台:常驻高亮 + 数量角标 */
.cmd--active {
  border-color: var(--line-bright);
  color: var(--cyan);
}

.cmd-badge {
  font-family: var(--font-tech);
  font-size: 10px;
  line-height: 1;
  padding: 2px 5px;
  border-radius: 999px;
  background: var(--cyan);
  color: #0b1220;
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

.paper-imp {
  min-width: 240px;
  margin-bottom: 6px;
  padding: 10px;
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  background: var(--bg-card);
}

.paper-imp-head {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.paper-imp-icon {
  flex: none;
}

.paper-imp-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-hi);
  font-size: 12.5px;
}

.paper-imp-pages {
  flex: none;
  color: var(--text-dim);
  font-size: 10.5px;
}

.paper-imp-q {
  margin: 7px 0 8px;
  color: var(--text);
  font-size: 12px;
  line-height: 1.55;
}

.paper-imp-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.paper-imp-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 5px;
  font-size: 11px;
  padding: 4px 8px;
  cursor: pointer;
}

.paper-imp-btn.primary {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

.paper-imp-btn:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
}

.paper-imp-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.paper-imp-state {
  margin: 0;
  color: var(--cyan);
  font-size: 11px;
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

.dev-badge {
  font-size: 10px;
  font-family: var(--font-tech);
  color: var(--magenta);
  border: 1px solid rgba(255, 77, 210, 0.4);
  border-radius: 999px;
  padding: 0 6px;
}

/* 窄屏(竖屏 iPad:768–834):默认字号的指令行放不下,「生成文档」会被挤到第二行。
   改为单行紧凑布局,放不下时横向滚动,不再换行。 */
@media (max-width: 900px) {
  .input-bar {
    padding: 10px 12px 12px;
  }

  .commands {
    flex-wrap: nowrap;
    overflow-x: auto;
    gap: 6px;
    scrollbar-width: none;
  }

  .commands::-webkit-scrollbar {
    display: none;
  }

  .cmd-label {
    display: none;
  }

  .cmd {
    flex: none;
    padding: 4px 9px;
    font-size: 11px;
    white-space: nowrap;
  }

  .voice-label {
    display: none;
  }
}
</style>
