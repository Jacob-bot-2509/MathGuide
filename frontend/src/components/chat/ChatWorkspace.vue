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
import PaperInsights from '@/components/research/PaperInsights.vue'
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
import { createResearchTable, getResearchTable } from '@/services/researchTableService'
import {
  compareResearchDocs,
  downloadResearchReport,
  generateResearchDocInsights,
  getResearchDocInsights,
  getResearchDocMeta,
  listResearchProjects,
  uploadTempPaper,
  type PaperAction,
  type PaperStructure,
  type ResearchDoc,
  type ResearchProject,
} from '@/services/researchService'
import { deletePaperHistory, importTempPaper } from '@/services/literatureService'
import { downloadBlob, exportSurveyPdf } from '@/services/docService'
import { CATEGORIES, DISPLAY_KEYS, FALLBACK_CATEGORY, categoryByKey, classifyQuestion, isChitchat } from '@/utils/classifier'
import { buildChapterMarkdown, chapterKey, locateChapter, sliceChapter, withRanges } from '@/utils/bookChapters'
import { getCachedGuide, getCachedToc, loadBook, saveGuide, saveToc, touchBook } from '@/utils/bookStore'
import { historyQa } from '@/utils/docHistory'
import { detectAmbiguous, topicById, type AmbiguousOption } from '@/utils/ambiguous'
import { usePaperChat } from '@/composables/usePaperChat'
import { settingsState } from '@/stores/settings'
import {
  clearCompareIds,
  compareIds,
  hasCompareId,
  toggleCompareId,
} from '@/stores/compareQueue'
import { activeProjectId, setActiveProjectId } from '@/stores/researchProject'
import { saveTask } from '@/stores/todo'
import { dateKeyOf, pad2 } from '@/utils/todoTime'
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
import { crossWorkspaceHref, hostWorkspace } from '@/utils/workspace'

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
/** 科研区显式独立双角色低温复核开关(真实二阶段复核,非提示词人设) */
const researchVerify = ref(false)
/** 由结构化工作流(如对比表→挖掘研究缺口)触发的一次性后端 profile */
const pendingProfileOnce = ref('')
/** 课题上下文透镜 */
const researchProjects = ref<ResearchProject[]>([])
const exportingReport = ref(false)

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
  if (stageOpen.value && stageTab.value === 'reader' && searchOpen.value) {
    stageOpen.value = false
    searchOpen.value = false
    return
  }
  stageTab.value = 'reader'
  stageOpen.value = true
  searchOpen.value = true
  nextTick(() => {
    splitRatio.value = clampSplit(
      splitRatio.value, workspaceBodyRef.value?.clientWidth ?? 0)
  })
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
    if (window.innerWidth < SPLIT_MIN_WIDTH) return
    stageTab.value = 'reader'
    stageOpen.value = true
    searchOpen.value = true
    for (let i = 0; i < 20 && !searchPaneRef.value; i += 1) {
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
  } else if (!stageOpen.value || stageTab.value !== 'reader') {
    stageTab.value = 'reader'
    stageOpen.value = true
    searchOpen.value = true
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

async function loadResearchProjects(): Promise<void> {
  if (!isResearch.value) return
  try {
    const list = await listResearchProjects()
    researchProjects.value = Array.isArray(list) ? list : []
  } catch {
    /* 离线/未登录时静默 */
  }
}

function onProjectSelect(e: Event): void {
  const val = (e.target as HTMLSelectElement).value
  setActiveProjectId(val)
}

async function exportActiveProjectReport(): Promise<void> {
  if (!activeProjectId.value || exportingReport.value) return
  exportingReport.value = true
  try {
    await downloadResearchReport(activeProjectId.value)
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('tables.exportFail'))
  } finally {
    exportingReport.value = false
  }
}

const activeReaderPaper = computed(() =>
  isResearch.value ? (currentPaper.value || stagedPaper.value) : null,
)
const readerInsightsOpen = ref(false)
const readerInsightsStructure = ref<PaperStructure | null>(null)
const readerInsightsLoading = ref(false)
const readerInsightsError = ref('')
const readerInsightCache = new Map<string, PaperStructure>()
let readerInsightsSeq = 0

async function loadReaderInsights(docId: string, refresh = false): Promise<void> {
  const seq = ++readerInsightsSeq
  if (!refresh) {
    const cached = readerInsightCache.get(docId)
    if (cached) {
      readerInsightsStructure.value = cached
      readerInsightsError.value = ''
      readerInsightsLoading.value = false
      return
    }
  }
  readerInsightsStructure.value = null
  readerInsightsError.value = ''
  readerInsightsLoading.value = true
  try {
    let data = refresh
      ? await generateResearchDocInsights(docId, true)
      : await getResearchDocInsights(docId)
    if (!data.cached || !data.structure) {
      data = await generateResearchDocInsights(docId, false)
    }
    if (seq !== readerInsightsSeq) return
    if (!data.structure) throw new Error(t('workspace.generateFail'))
    readerInsightsStructure.value = data.structure
    readerInsightCache.set(docId, data.structure)
  } catch (err) {
    if (seq !== readerInsightsSeq) return
    readerInsightsError.value = err instanceof Error && err.message
      ? err.message : t('workspace.generateFail')
  } finally {
    if (seq === readerInsightsSeq) readerInsightsLoading.value = false
  }
}

function toggleReaderInsights(): void {
  const paper = activeReaderPaper.value
  if (!paper) return
  readerInsightsOpen.value = !readerInsightsOpen.value
  if (readerInsightsOpen.value) void loadReaderInsights(paper.docId)
}

/** 阅读器快捷多论文对比清单(与全科研区共享唯一 5 篇待对比篮,复用 /api/research/literature/compare) */
const compareRunning = ref(false)
const isPaperInCompare = computed(() => {
  const id = activeReaderPaper.value?.docId
  return Boolean(id && hasCompareId(id))
})

function toggleComparePaper(): void {
  const id = activeReaderPaper.value?.docId
  if (!id) return
  if (!toggleCompareId(id)) {
    showToast(t('stage.compareHint'))
  }
}

async function runCompareQueue(): Promise<void> {
  if (compareRunning.value || compareIds.value.length < 2) return
  compareRunning.value = true
  try {
    const data = await compareResearchDocs(compareIds.value)
    const projectId = activeProjectId.value || null
    const created = await createResearchTable({
      title: data.title,
      columns: data.columns,
      rows: data.rows,
      formulas: {},
      rowLabels: data.rowLabels,
      merges: [],
      colWidths: data.columns.map(() => 160),
      rowHeights: data.rows.map(() => 30),
      projectId,
      rowSources: data.rowSources,
    })
    if (data.warnings.length) showToast(data.warnings[0])
    clearCompareIds()
    const query: Record<string, string> = { tableId: created.id }
    if (projectId) query.projectId = projectId
    await router.push({ path: '/research/tables', query })
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.compareFail'))
  } finally {
    compareRunning.value = false
  }
}

watch(() => activeReaderPaper.value?.docId, (nextId) => {
  if (!nextId) {
    readerInsightsOpen.value = false
    readerInsightsStructure.value = null
    return
  }
  if (readerInsightsOpen.value) void loadReaderInsights(nextId)
})

/* ---------- 左侧科研仪器栏(桌面宽屏展开,可折叠记忆) ---------- */
const RAIL_KEY = 'mg-rail-open'
function loadRailOpen(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) !== '0'
  } catch {
    return true
  }
}
const railOpen = ref(loadRailOpen())
const lockedHost = hostWorkspace()

function toggleRail(): void {
  railOpen.value = !railOpen.value
  try {
    localStorage.setItem(RAIL_KEY, railOpen.value ? '1' : '0')
  } catch {
    /* 忽略隐私模式存储限制 */
  }
}

function switchWorkspace(target: Workspace): void {
  if (target === props.workspace) return
  const path = target === 'research' ? '/research' : '/learn'
  const href = crossWorkspaceHref(target, path)
  if (href !== path) {
    window.location.assign(href)
    return
  }
  router.push(path)
}

function isCommandActive(key: string): boolean {
  if (key === '问题记录') return activePanel.value === 'notebook'
  if (key === '公式查询手册') return activePanel.value === 'formula'
  if (key === '待办清单') return activePanel.value === 'todo'
  if (key === '学习分析') return activePanel.value === 'analysis'
  if (key === '搜索范围') return activePanel.value === 'scope' || !isAllSelected()
  if (key === '研究档案') return activePanel.value === 'archive'
  if (key === '生成文档') return docOpen.value
  return false
}

/* ---------- 右侧可折叠多子窗科研演示台(Science Stage:单窗 / 上下双窗 / 多窗堆叠) ---------- */
type StageTab = 'figures' | 'files' | 'reader'
type StageLayout = 'single' | 'split' | 'stack'
const STAGE_KEY = 'mg-stage-open'
const STAGE_LAYOUT_KEY = 'mg-stage-layout'
const STAGE_PANES_KEY = 'mg-stage-panes'
const STAGE_ROW_SPLIT_KEY = 'mg-stage-row-split'
const VALID_TABS: StageTab[] = ['figures', 'files', 'reader']

function loadStageOpen(): boolean {
  try {
    return localStorage.getItem(STAGE_KEY) === '1'
  } catch {
    return false
  }
}

function loadStageLayout(): StageLayout {
  try {
    const raw = localStorage.getItem(STAGE_LAYOUT_KEY)
    if (raw === 'single' || raw === 'split' || raw === 'stack') return raw
  } catch {
    /* 忽略隐私模式限制 */
  }
  return 'split'
}

function loadStagePanes(): StageTab[] {
  try {
    const raw = localStorage.getItem(STAGE_PANES_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        const clean = parsed.filter((item): item is StageTab => VALID_TABS.includes(item as StageTab))
        if (clean.length) return Array.from(new Set(clean))
      }
    }
  } catch {
    /* 忽略损坏存档 */
  }
  return ['figures', 'files']
}

function clampRowRatio(v: number): number {
  if (!Number.isFinite(v)) return 0.52
  return Math.min(0.78, Math.max(0.22, v))
}

function loadStageRowRatio(): number {
  try {
    const raw = Number(localStorage.getItem(STAGE_ROW_SPLIT_KEY))
    return raw ? clampRowRatio(raw) : 0.52
  } catch {
    return 0.52
  }
}

const stageOpen = ref(loadStageOpen())
const stageTab = ref<StageTab>('figures')
const stageLayout = ref<StageLayout>(loadStageLayout())
const stageOpenPanes = ref<StageTab[]>(loadStagePanes())
const stageCollapsed = ref<Record<StageTab, boolean>>({
  figures: false,
  files: false,
  reader: false,
})
const stageMaximized = ref<StageTab | null>(null)
const stageRowRatio = ref(loadStageRowRatio())
const stageRowResizing = ref(false)
const stageDockRef = ref<HTMLElement | null>(null)
const activeFigureKey = ref('')
const activeFileKey = ref('')

const showRightStage = computed(() =>
  !focusDiagram.value && (stageOpen.value || (isResearch.value && searchOpen.value)),
)

/** 当前工作区允许打开的子窗口列表(学习区不含 reader) */
const allowedOpenPanes = computed<StageTab[]>(() => {
  const list = stageOpenPanes.value.filter((tab) => isResearch.value || tab !== 'reader')
  if (list.length) return list
  return ['figures']
})

/** 当前实际渲染在演示台中的子窗口有序列表 */
const visibleStagePanes = computed<StageTab[]>(() => {
  const allowed = allowedOpenPanes.value
  if (stageMaximized.value && (isResearch.value || stageMaximized.value !== 'reader')) {
    return [stageMaximized.value]
  }
  if (stageLayout.value === 'single') {
    const active = !isResearch.value && stageTab.value === 'reader' ? 'figures' : stageTab.value
    return [active]
  }
  if (stageLayout.value === 'split') {
    return allowed.slice(0, 2)
  }
  return allowed
})

/** 是否显示上下双窗之间的横向拖拽分隔条 */
const showStageRowDivider = computed(() =>
  stageLayout.value === 'split'
  && !stageMaximized.value
  && visibleStagePanes.value.length === 2
  && !stageCollapsed.value[visibleStagePanes.value[0]]
  && !stageCollapsed.value[visibleStagePanes.value[1]],
)

function isPaneVisible(tab: StageTab): boolean {
  return visibleStagePanes.value.includes(tab)
}

function isStageTabOn(tab: StageTab): boolean {
  return visibleStagePanes.value.includes(tab)
}

function paneFlexStyle(tab: StageTab): Record<string, string> {
  const idx = visibleStagePanes.value.indexOf(tab)
  if (idx < 0) return {}
  // 留出 order: 1 给双窗横向拖拽分隔条
  const order = showStageRowDivider.value ? (idx === 0 ? '0' : '2') : String(idx)
  if (stageCollapsed.value[tab] && visibleStagePanes.value.length > 1) {
    return { order, flex: '0 0 auto' }
  }
  if (showStageRowDivider.value) {
    return idx === 0
      ? { order, flex: `0 0 calc(${(stageRowRatio.value * 100).toFixed(2)}% - 3px)` }
      : { order, flex: '1 1 0%' }
  }
  return { order, flex: '1 1 0%' }
}

function saveStageOpen(val: boolean): void {
  try {
    localStorage.setItem(STAGE_KEY, val ? '1' : '0')
  } catch {
    /* 忽略隐私模式限制 */
  }
}

function saveStageLayout(layout: StageLayout): void {
  try {
    localStorage.setItem(STAGE_LAYOUT_KEY, layout)
  } catch {
    /* 忽略隐私模式限制 */
  }
}

function saveStagePanes(panes: StageTab[]): void {
  try {
    localStorage.setItem(STAGE_PANES_KEY, JSON.stringify(panes))
  } catch {
    /* 忽略隐私模式限制 */
  }
}

function saveStageRowRatio(): void {
  try {
    localStorage.setItem(STAGE_ROW_SPLIT_KEY, String(stageRowRatio.value))
  } catch {
    /* 忽略隐私模式限制 */
  }
}

function ensurePaneOpen(tab: StageTab, promote = false): void {
  if (tab === 'reader' && !isResearch.value) return
  let next = [...stageOpenPanes.value]
  if (!next.includes(tab)) {
    next = promote ? [tab, ...next] : [...next, tab]
  } else if (promote && stageLayout.value === 'split' && next.indexOf(tab) >= 2) {
    next = [tab, ...next.filter((item) => item !== tab)]
  }
  stageOpenPanes.value = next
  stageCollapsed.value[tab] = false
  saveStagePanes(next)
}

function setStageLayout(layout: StageLayout): void {
  stageLayout.value = layout
  stageMaximized.value = null
  saveStageLayout(layout)
  if (layout !== 'single' && allowedOpenPanes.value.length < 2) {
    const fallback: StageTab = allowedOpenPanes.value[0] === 'figures' ? 'files' : 'figures'
    ensurePaneOpen(fallback)
  }
}

function selectStageTab(tab: StageTab): void {
  if (tab === 'reader' && !isResearch.value) return
  stageTab.value = tab
  stageOpen.value = true
  stageMaximized.value = null
  saveStageOpen(true)
  ensurePaneOpen(tab, true)
  if (tab === 'reader') {
    if (window.innerWidth <= 960) {
      router.push('/research/search')
      return
    }
    searchOpen.value = true
  }
}

function togglePaneCollapse(tab: StageTab): void {
  stageCollapsed.value[tab] = !stageCollapsed.value[tab]
}

function togglePaneMaximize(tab: StageTab): void {
  stageMaximized.value = stageMaximized.value === tab ? null : tab
  stageCollapsed.value[tab] = false
}

function closeSubPane(tab: StageTab): void {
  if (stageMaximized.value === tab) stageMaximized.value = null
  const remaining = allowedOpenPanes.value.filter((item) => item !== tab)
  if (stageLayout.value === 'single' || !remaining.length) {
    closeStage()
    return
  }
  stageOpenPanes.value = remaining
  saveStagePanes(remaining)
  if (stageTab.value === tab) stageTab.value = remaining[0]
  if (tab === 'reader') searchOpen.value = false
}

function startStageRowDrag(e: PointerEvent): void {
  const dock = stageDockRef.value
  if (!dock) return
  e.preventDefault()
  stageRowResizing.value = true
  const rect = dock.getBoundingClientRect()
  const move = (ev: PointerEvent) => {
    if (!rect.height) return
    stageRowRatio.value = clampRowRatio((ev.clientY - rect.top) / rect.height)
  }
  const up = () => {
    stageRowResizing.value = false
    window.removeEventListener('pointermove', move)
    window.removeEventListener('pointerup', up)
    saveStageRowRatio()
  }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', up)
}

function nudgeStageRow(delta: number): void {
  stageRowRatio.value = clampRowRatio(stageRowRatio.value + delta)
  saveStageRowRatio()
}

function resetStageRow(): void {
  stageRowRatio.value = 0.52
  saveStageRowRatio()
}

function closeStage(): void {
  stageOpen.value = false
  stageMaximized.value = null
  searchOpen.value = false
  saveStageOpen(false)
}

function stageLabel(zh: string, en: string): string {
  return settingsState.language === 'en' ? en : zh
}

// 窄屏关闭分栏时保持同步
watch(searchOpen, (open) => {
  if (open && isResearch.value) {
    stageOpen.value = true
    stageTab.value = 'reader'
    stageMaximized.value = null
    ensurePaneOpen('reader', true)
  }
})


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

/** 量取按钮位置(优先寻找当前可见触发源;桌面左栏触发时底部指令隐藏 → 返回 null 居中悬浮) */
function anchorTo(selector: string, panelWidth = 560, containerSelector = '.input-bar') {
  const btn = Array.from(document.querySelectorAll<HTMLElement>(selector))
    .find((el) => el.offsetParent !== null) ?? null
  const root = document.querySelector<HTMLElement>(containerSelector)
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
function isWelcomeMessage(msg: ChatMsg): boolean {
  if (msg.role !== 'assistant') return false
  return Boolean(msg.welcome)
    || /^\*\*(欢迎回到|Welcome (?:back )?to) MATHGUIDE/.test(msg.content.trim())
}

const welcomeText = computed(() =>
  t(isResearch.value ? 'learn.welcomeResearch' : 'learn.welcome'))

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
  const content = isWelcomeMessage(msg) ? welcomeText.value : msg.content
  splitMessageBlocks(content, msg.diagrams).forEach((segment, si) => {
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
  const onceProfile = pendingProfileOnce.value
  pendingProfileOnce.value = ''
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
    profile: onceProfile || undefined,
    verify: isResearch.value && researchVerify.value ? true : undefined,
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
    if (!settingsState.personalized) {
      showToast(t('learn.personalOff'))
      return
    }
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
  const text = t('analysis.askPrompt') || cmdDefault('学习分析') || '分析我的学习进度'
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
  anchorTo('.sum-btn', 320, '.learn')
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

/* ---------- 右侧科研演示台数据汇总(依赖 activeSession 与 fmtSize) ---------- */
interface StageFigureItem {
  key: string
  msgId: number
  diagram: DiagramBlock
  title: string
}

interface StageFileItem {
  key: string
  kind: 'image' | 'book' | 'file' | 'paper' | 'table'
  msgId?: number
  title: string
  subtitle: string
  url?: string
  preview?: string
  bookId?: string
  docId?: string
  tableId?: string
}

/** 当前会话全部数学图解(2D/3D/GeoGebra),按时间倒序方便优先查看最新成果 */
const sessionDiagrams = computed<StageFigureItem[]>(() => {
  const session = activeSession.value
  if (!session) return []
  const items: StageFigureItem[] = []
  for (const m of session.messages) {
    if (!m.diagrams?.length) continue
    for (const diagram of m.diagrams) {
      items.push({
        key: `${m.id}-${diagram.id}`,
        msgId: m.id,
        diagram,
        title: diagram.spec.title || t('diagram.figure'),
      })
    }
  }
  return items.reverse()
})

/** 当前会话全部文件、图片、教材与科研上下文(论文/实验表) */
const sessionFiles = computed<StageFileItem[]>(() => {
  const session = activeSession.value
  const items: StageFileItem[] = []
  if (isResearch.value && tableContext.value) {
    items.push({
      key: `table-${tableContext.value.id}`,
      kind: 'table',
      title: tableContext.value.title,
      subtitle: tableContext.value.regression
        ? `Regression · ${tableContext.value.regression.model.toUpperCase()}`
        : t('chat.tableContext'),
      tableId: tableContext.value.id,
    })
  }
  if (isResearch.value && stagedPapers.value.length) {
    for (const p of [...stagedPapers.value].reverse()) {
      items.push({
        key: `paper-${p.docId}`,
        kind: 'paper',
        msgId: p.msgId,
        title: p.title,
        subtitle: t('learn.paperPages', { n: p.pages }),
        docId: p.docId,
      })
    }
  }
  if (session) {
    for (const m of [...session.messages].reverse()) {
      if (!m.attachment) continue
      const att = m.attachment
      if (att.kind === 'image') {
        items.push({
          key: `img-${m.id}`,
          kind: 'image',
          msgId: m.id,
          title: att.name,
          subtitle: fmtSize(att.size),
          url: att.url,
        })
      } else if (att.bookId) {
        items.push({
          key: `book-${m.id}`,
          kind: 'book',
          msgId: m.id,
          title: att.name,
          subtitle: `${att.bookPages ? `${att.bookPages}p · ` : ''}${fmtSize(att.size)}`,
          bookId: att.bookId,
          preview: att.text,
        })
      } else {
        items.push({
          key: `file-${m.id}`,
          kind: 'file',
          msgId: m.id,
          title: att.name,
          subtitle: fmtSize(att.size),
          preview: att.text,
        })
      }
    }
  }
  return items
})

const stageArtifactCount = computed(() => sessionDiagrams.value.length + sessionFiles.value.length)

const activeStageFigure = computed(() =>
  sessionDiagrams.value.find((item) => item.key === activeFigureKey.value)
  ?? sessionDiagrams.value[0]
  ?? null,
)

const activeStageFile = computed(() =>
  sessionFiles.value.find((item) => item.key === activeFileKey.value)
  ?? sessionFiles.value[0]
  ?? null,
)

function toggleStage(preferredTab?: StageTab): void {
  if (focusDiagram.value) {
    closeDiagramFocus({ restoreSearch: false })
  }
  if (preferredTab) {
    if (stageOpen.value && stageTab.value === preferredTab) {
      stageOpen.value = false
      searchOpen.value = false
      saveStageOpen(false)
      return
    }
    stageTab.value = preferredTab
    stageOpen.value = true
    if (preferredTab === 'reader' && isResearch.value) searchOpen.value = true
    saveStageOpen(true)
    return
  }
  const next = !showRightStage.value
  stageOpen.value = next
  saveStageOpen(next)
  if (!next) {
    searchOpen.value = false
    return
  }
  if (stageTab.value === 'reader' && !isResearch.value) {
    stageTab.value = sessionDiagrams.value.length ? 'figures' : 'files'
  } else if (stageTab.value === 'figures' && !sessionDiagrams.value.length && sessionFiles.value.length) {
    stageTab.value = 'files'
  } else if (stageTab.value === 'reader' && isResearch.value) {
    searchOpen.value = true
  }
  nextTick(() => {
    splitRatio.value = clampSplit(
      splitRatio.value, workspaceBodyRef.value?.clientWidth ?? 0)
  })
}

// 演示台已展开时,新生成图解或新导入文件自动唤醒对应子窗口(多窗模式下不挤掉阅读器)
watch(() => sessionDiagrams.value[0]?.key, (nextKey, prevKey) => {
  if (nextKey && nextKey !== prevKey) {
    activeFigureKey.value = nextKey
    if (stageOpen.value) {
      if (stageLayout.value === 'single') {
        if (stageTab.value !== 'reader') stageTab.value = 'figures'
      } else {
        ensurePaneOpen('figures', true)
      }
    }
  }
})

watch(() => sessionFiles.value[0]?.key, (nextKey, prevKey) => {
  if (nextKey && nextKey !== prevKey) {
    activeFileKey.value = nextKey
    if (stageOpen.value) {
      if (stageLayout.value === 'single') {
        if (stageTab.value !== 'reader') stageTab.value = 'files'
      } else {
        ensurePaneOpen('files', true)
      }
    }
  }
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
  const reply: ChatMsg = { id: nextMsgId(), role: 'assistant', content: '', streaming: true, thinking: true, welcome: true }
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

/** 以研促学:把科研区里难懂的推导或定理带入学习辅助做教学级拆解与图解,不污染原科研上下文 */
function studyPrerequisites(msg: ChatMsg): void {
  const q = previousQuestion(msg)
  const excerpt = msg.content.replace(/\s+/g, ' ').trim().slice(0, 280)
  const prompt = settingsState.language === 'en'
    ? `I encountered a challenging derivation in my research and want to reinforce the prerequisite mathematical theory step by step with intuition and diagrams.\n\nResearch question: ${q}\nDerivation excerpt: ${excerpt}`
    : `我在科研推演中遇到了较难理解的定理/推导，请帮我夯实其中的前置基础数学理论，并用教学级步骤与图解讲透：\n\n科研原问题：${q}\n相关推导摘录：${excerpt}`
  const originLabel = (currentPaper.value?.title || stagedPaper.value?.title || q).slice(0, 60)
  try {
    sessionStorage.setItem('mg-learn-seed', prompt)
    sessionStorage.setItem('mg-learn-origin', JSON.stringify({
      workspace: 'research',
      sessionId: activeSession.value?.id || 0,
      docId: currentPaper.value?.docId || stagedPaper.value?.docId || undefined,
      label: originLabel,
    }))
  } catch {
    /* 忽略隐私模式限制 */
  }
  const href = crossWorkspaceHref('learn', '/learn')
  if (href !== '/learn') {
    window.location.assign(href)
    return
  }
  void router.push('/learn')
}

/** 创新 4:将科研推演中的发现/待验证点一键 Pin 到科研区独立待办桶(带现场还原锚点) */
function pinReplyToTodo(msg: ChatMsg): void {
  const q = previousQuestion(msg)
  const paper = currentPaper.value || stagedPaper.value
  const tbl = tableContext.value
  const next = new Date(Date.now() + 60 * 60 * 1000)
  next.setSeconds(0, 0)
  const anchor = paper
    ? { kind: 'paper' as const, id: paper.docId, label: paper.title }
    : tbl
      ? { kind: 'table' as const, id: tbl.id, label: tbl.title }
      : { kind: 'session' as const, id: String(activeSession.value?.id || 0), label: (q || t('research.title')).slice(0, 48) }
  saveTask({
    content: `${q || msg.content.slice(0, 80)}`.slice(0, 280),
    date: dateKeyOf(next),
    time: `${pad2(next.getHours())}:${pad2(next.getMinutes())}`,
    repeat: 'once',
    weekdays: [],
    anchor,
  })
  showToast(t('research.pinnedTodo'))
}

/** 补课完成后一键返回原科研会话(只传会话引用,不破坏双区存档隔离) */
function returnToOriginSession(): void {
  const origin = activeSession.value?.origin
  if (!origin) return
  try {
    sessionStorage.setItem('mg-jump-session', JSON.stringify(origin))
  } catch {
    /* 忽略隐私模式限制 */
  }
  const targetPath = origin.workspace === 'research' ? '/research' : '/learn'
  const href = crossWorkspaceHref(origin.workspace, targetPath)
  if (href !== targetPath) {
    window.location.assign(href)
    return
  }
  void router.push(targetPath)
}

function openQuickPalette(): void {
  window.dispatchEvent(new Event('mg:open-palette'))
}

function applySessionJump(payload: {
  workspace?: string
  sessionId?: number
  docId?: string
  docTitle?: string
  label?: string
} | null): boolean {
  if (!payload) return false
  if (payload.workspace && payload.workspace !== props.workspace) return false
  let jumped = false
  if (typeof payload.sessionId === 'number' && payload.sessionId > 0) {
    const found = sessions.value.find((s) => s.id === payload.sessionId)
    if (found) {
      activeId.value = found.id
      jumped = true
      scrollBottom()
    }
  }
  if (isResearch.value && payload.docId) {
    const docId = payload.docId
    const title = payload.docTitle || payload.label || docId
    stagedPaper.value = { docId, title }
    if (window.innerWidth >= 960) {
      selectStageTab('reader')
      void nextTick(() => {
        void searchPaneRef.value?.openDocForActions(docId, title, [], '')
      })
    }
    jumped = true
  }
  return jumped
}

function onJumpSessionEvent(e: Event): void {
  const detail = (e as CustomEvent<{ workspace?: string; sessionId?: number; docId?: string }>).detail
  if (!detail) return
  try { sessionStorage.removeItem('mg-jump-session') } catch { /* ignore */ }
  applySessionJump(detail)
}

onMounted(() => {
  // 每次进入页面都开启全新对话;旧会话自动归档到相应板块
  // (会话档案由 stores/sessions 在应用启动时恢复)
  sessions.value = sessions.value.filter((s) => s.cat
    || s.messages.some((m) => m.role === 'user' || m.paperImport))
  restoreStagedPapers()
  let jumpedToExisting = false
  try {
    const rawJump = sessionStorage.getItem('mg-jump-session')
    if (rawJump) {
      const parsed = JSON.parse(rawJump) as { workspace?: string; sessionId?: number; docId?: string }
      if (!parsed.workspace || parsed.workspace === props.workspace) {
        sessionStorage.removeItem('mg-jump-session')
        jumpedToExisting = applySessionJump(parsed)
      }
    }
  } catch {
    /* 忽略损坏数据 */
  }
  if (!jumpedToExisting || !activeSession.value) {
    createSession()
    greet()
  }
  consumePointLink()
  // 科研区「夯实前置理论」桥接:消费一次种子提问后立即清理,开启独立学习推演
  if (!isResearch.value) {
    const learnSeed = sessionStorage.getItem('mg-learn-seed')
    const rawOrigin = sessionStorage.getItem('mg-learn-origin')
    if (rawOrigin) sessionStorage.removeItem('mg-learn-origin')
    if (learnSeed) {
      sessionStorage.removeItem('mg-learn-seed')
      if (rawOrigin && activeSession.value) {
        try {
          const parsed = JSON.parse(rawOrigin) as { workspace?: string; sessionId?: number; docId?: string; label?: string }
          if (parsed.workspace === 'research' || parsed.workspace === 'learn') {
            activeSession.value.origin = {
              workspace: parsed.workspace,
              sessionId: typeof parsed.sessionId === 'number' ? parsed.sessionId : 0,
              docId: typeof parsed.docId === 'string' ? parsed.docId : undefined,
              label: typeof parsed.label === 'string' ? parsed.label : undefined,
            }
            persistSessions()
          }
        } catch {
          /* 忽略格式错误 */
        }
      }
      nextTick(() => send(learnSeed))
    }
  }
  // 文献检索页「基于这些结果提问」/ 知识图谱「查前沿论文」/ 对比表「挖掘研究缺口」:进科研区后直接发送
  if (isResearch.value) {
    const onceProfile = sessionStorage.getItem('mg-research-profile-once')
    if (onceProfile) {
      sessionStorage.removeItem('mg-research-profile-once')
      pendingProfileOnce.value = onceProfile
    }
    const seed = sessionStorage.getItem('mg-research-seed')
    if (seed) {
      sessionStorage.removeItem('mg-research-seed')
      nextTick(() => send(seed))
    }
    void loadTableContext()
    void loadResearchProjects()
  }
  window.addEventListener('resize', onWorkspaceResize)
  window.addEventListener('beforeunload', warnPendingPapers)
  window.addEventListener('mg:jump-session', onJumpSessionEvent)
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
  window.removeEventListener('mg:jump-session', onJumpSessionEvent)
  stopAllStreams()
  disposeSpeech()
  if (flashTimer) clearTimeout(flashTimer)
})
</script>

<template>
  <div
    class="learn"
    :class="[isResearch ? 'ws-research' : 'ws-learn', { 'rail-open': railOpen, 'stage-open': showRightStage }]"
    @click="onRootClick"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDropFiles"
  >
    <header class="chat-header">
      <button
        class="rail-toggle"
        type="button"
        :aria-expanded="railOpen"
        aria-label="Toggle sidebar"
        @click="toggleRail"
      >◧</button>
      <button class="back" @click="router.push('/home')">{{ t('common.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t(isResearch ? 'research.title' : 'learn.title') }}</span>
        <span class="tech-label sub">{{ isResearch ? 'DISCOVERY WORKBENCH' : 'STUDY STUDIO' }}</span>
      </div>
      <div class="right">
        <button
          v-if="isResearch"
          class="new-btn header-dup"
          :class="{ 'new-btn--active': showRightStage && stageTab === 'reader' }"
          @click="openResearchSearch"
        >
          {{ t('search.button') }}
        </button>
        <button v-if="isResearch" class="new-btn header-dup" @click="router.push('/research/tables')">
          {{ t('tables.entry') }}
        </button>
        <button class="new-btn header-dup" @click="newConversation">{{ t('learn.newChat') }}</button>
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
        <button
          class="stage-toggle"
          type="button"
          :class="{ 'stage-toggle--on': showRightStage }"
          :aria-expanded="showRightStage"
          :title="stageLabel('切换右侧科研演示台（图表 / 文件 / 文献）', 'Toggle Science Stage (Figures / Files / Reader)')"
          @click="toggleStage()"
        >
          <span class="stage-toggle-ico" aria-hidden="true">◨</span>
          <span class="stage-toggle-label">{{ stageLabel('演示台', 'Stage') }}</span>
          <span v-if="stageArtifactCount" class="stage-toggle-badge">{{ stageArtifactCount }}</span>
        </button>
        <button
          type="button"
          class="palette-trigger"
          :title="t('palette.openHint')"
          @click="openQuickPalette"
        >⌘K</button>
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

    <!-- 三栏科研工作台主区:左仪器栏 + 中文档流 + 右文献/图解检查器 -->
    <div ref="workspaceBodyRef" class="workspace-body" :class="{ 'with-search': searchOpen, 'with-focus': focusDiagram }">
      <!-- 左侧可折叠科研仪器栏(宽屏桌面自动展示,窄屏/移动端优雅退回底部指令条) -->
      <aside v-show="railOpen" class="sci-rail" aria-label="Workspace Instruments">
        <div v-if="!lockedHost" class="rail-seg" role="tablist">
          <button
            type="button"
            class="rail-seg-btn"
            :class="{ on: !isResearch }"
            @click="switchWorkspace('learn')"
          >{{ t('home.learnTitle') }}</button>
          <button
            type="button"
            class="rail-seg-btn"
            :class="{ on: isResearch }"
            @click="switchWorkspace('research')"
          >{{ t('home.researchTitle') }}</button>
        </div>

        <div class="rail-section">
          <div class="rail-heading tech-label">{{ isResearch ? 'RESEARCH LAB' : 'STUDIO TOOLS' }}</div>
          <div v-if="isResearch && researchProjects.length" class="rail-project">
            <select
              class="rail-project-select"
              :value="activeProjectId"
              :aria-label="t('research.projectAll')"
              @change="onProjectSelect"
            >
              <option value="">{{ t('research.projectAll') }}</option>
              <option v-for="p in researchProjects" :key="p.id" :value="p.id">{{ p.title }}</option>
            </select>
            <button
              v-if="activeProjectId"
              type="button"
              class="rail-report-btn"
              :disabled="exportingReport"
              @click="exportActiveProjectReport"
            >{{ exportingReport ? '…' : t('research.exportReport') }}</button>
          </div>
          <button
            v-if="isResearch"
            type="button"
            class="rail-item"
            :class="{ 'rail-item--on': showRightStage && stageTab === 'reader' }"
            @click="openResearchSearch"
          >
            <span class="rail-icon">⌕</span>
            <span class="rail-text">{{ t('search.button') }}</span>
          </button>
          <button
            v-if="isResearch"
            type="button"
            class="rail-item"
            @click="router.push('/research/tables')"
          >
            <span class="rail-icon">⊞</span>
            <span class="rail-text">{{ t('tables.entry') }}</span>
          </button>
          <button
            v-for="c in commands"
            :key="`rail-${c.key}`"
            type="button"
            class="rail-item"
            :class="{ 'rail-item--on': isCommandActive(c.key) }"
            :title="cmdHint(c.key)"
            @click="runCommand(c.key)"
          >
            <span class="rail-icon">{{ c.icon }}</span>
            <span class="rail-text">{{ cmdName(c.key) }}</span>
            <span v-if="c.key === '搜索范围' && !isAllSelected()" class="rail-badge">{{ selectedSources.length }}</span>
            <span v-else-if="c.key === '问题记录' && notebooks.state.entries.length" class="rail-tag">{{ notebooks.state.entries.length }}</span>
          </button>
        </div>

        <div class="rail-foot">
          <button type="button" class="rail-new" @click="newConversation">{{ t('learn.newChat') }}</button>
          <div v-if="!isResearch" class="rail-voice">
            <span class="rail-voice-label">{{ t('learn.voiceLabel') }}</span>
            <MgSwitch
              size="sm"
              :model-value="settingsState.modelVoice"
              :title="t('learn.voiceHint')"
              @update:model-value="setModelVoice"
            />
          </div>
        </div>
      </aside>

      <div class="chat-pane" @click="onChatPaneClick">
        <div ref="listEl" class="chat-list" @scroll="onListScroll" @click="onListClick">
      <div v-if="activeSession" class="chat-stream">
        <div v-if="!isResearch && activeSession.origin" class="origin-banner">
          <span class="origin-meta">
            {{ t('bridge.fromResearch') }}<template v-if="activeSession.origin.label"> · {{ activeSession.origin.label }}</template>
          </span>
          <button type="button" class="origin-back" @click="returnToOriginSession">
            ← {{ t('bridge.returnResearch') }}
          </button>
        </div>
        <div
          v-for="m in activeSession.messages"
          :key="m.id"
          class="msg"
          :class="[m.role, { flash: m.id === flashMsgId }]"
          :data-msg-id="m.id"
        >
          <div class="bubble">
            <!-- 消息元信息抬头:将对话从社交气泡升级为科研推演/综述文档单元 -->
            <div v-if="m.role === 'user'" class="cell-meta cell-meta--user">
              <span class="cell-role tech-label">PROMPT</span>
              <span v-if="m.cmd" class="cmd-tag">{{ cmdName(m.cmd) }}</span>
              <span v-if="activeSession.cat" class="cat-chip">
                <span class="cat-dot" :style="{ background: activeSession.cat.color }"></span>{{ catName(activeSession.cat.key) }}
              </span>
            </div>
            <div v-else class="cell-meta cell-meta--assistant">
              <span class="cell-role tech-label">{{ isResearch ? 'MATHGUIDE · RESEARCH' : 'MATHGUIDE · PROOF & STUDY' }}</span>
              <span v-if="m.research" class="cell-pill cell-pill--cite tech-label">SYNTHESIS</span>
            </div>

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
              <span v-if="m.streaming && !m.thinking" class="cursor">▍</span>
              <!-- 半截回答的标记:与完整回答同形,不点明用户看不出缺了一段 -->
              <span v-if="m.interrupted" class="cut-note">{{ t('learn.interrupted') }}</span>
              <!-- 统一操作栏:图解 / 直观解释 / 综述导出 / 停止后续写 -->
              <div
                v-if="m.content && !m.streaming && !m.paperImport && ((previousQuestion(m) && !isChitchatTurn(m)) || m.research || m.stopped)"
                class="msg-actions"
              >
                <button
                  v-if="previousQuestion(m) && !isChitchatTurn(m) && !hasDiagram(m)"
                  class="diagram-btn"
                  type="button"
                  :disabled="diagramBusy === m.id"
                  @click.stop="requestDiagram(m)"
                >{{ diagramBusy === m.id ? t('diagram.generating') : t('diagram.generate') }}</button>
                <button
                  v-if="previousQuestion(m) && !isChitchatTurn(m)"
                  class="diagram-btn"
                  type="button"
                  :disabled="intuitionBusy === m.id"
                  @click.stop="requestIntuitionFor(m)"
                >{{ intuitionBusy === m.id
                  ? t('intuition.generating')
                  : (m.intuition ? t('intuition.regenerate') : t('intuition.generate')) }}</button>
                <button
                  v-if="isResearch && previousQuestion(m) && !isChitchatTurn(m)"
                  class="diagram-btn prereq-btn"
                  type="button"
                  :title="t('research.studyPrereqHint')"
                  @click.stop="studyPrerequisites(m)"
                >{{ t('research.studyPrereq') }}</button>
                <button
                  v-if="isResearch && previousQuestion(m) && !isChitchatTurn(m)"
                  class="diagram-btn"
                  type="button"
                  @click.stop="pinReplyToTodo(m)"
                >{{ t('research.pinTodo') }}</button>
                <template v-if="m.research">
                  <button
                    class="export-btn"
                    type="button"
                    :disabled="exportingMsg === m.id"
                    @click.stop="exportMenu = exportMenu === m.id ? null : m.id"
                  >
                    {{ exportingMsg === m.id ? t('learn.exporting') : t('learn.exportPdf') }}
                  </button>
                </template>
                <button
                  v-if="m.stopped"
                  class="resume-btn"
                  type="button"
                  :title="t('learn.resumeHint')"
                  @click.stop="resumeReply(m)"
                >
                  {{ t('learn.resume') }}
                </button>
              </div>
              <div v-if="m.research && !m.streaming && exportMenu === m.id" class="export-menu" @click.stop>
                <span class="export-menu-title">{{ t('learn.exportLangTitle') }}</span>
                <button type="button" @click="doExport(m, 'zh')">{{ t('learn.exportLangZh') }}</button>
                <button type="button" @click="doExport(m, 'en')">{{ t('learn.exportLangEn') }}</button>
              </div>
            </template>
            <div v-else class="user-text">{{ m.content }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 拖拽导入遮罩(电脑端):pointer-events 穿透,事件仍落在 .learn 上 -->
    <div v-if="dragging" class="drop-mask">
      <div class="drop-box">📂 {{ t('learn.dropHint') }}</div>
    </div>

    <!-- 一体化科研输入工作台 -->
    <footer class="input-bar">
      <div class="composer-card">
      <div v-if="isResearch" class="ai4s-tools-bar">
        <button
          type="button"
          class="ai4s-pill"
          :class="{ active: researchVerify }"
          :aria-pressed="researchVerify"
          data-ai4s-tool="verify"
          :title="t('research.verifyToggleHint')"
          @click="researchVerify = !researchVerify"
        >✓ {{ t('research.verifyToggle') }}</button>
        <button
          type="button"
          class="ai4s-pill"
          :class="{ active: researchDiagrams }"
          :aria-pressed="researchDiagrams"
          data-ai4s-tool="diagrams"
          :title="t('chat.diagramToggleHint')"
          @click="researchDiagrams = !researchDiagrams"
        >◈ {{ t('chat.diagramToggle') }}</button>
      </div>
      <div v-if="(isResearch && stagedPaper) || (isResearch && tableContext)" class="context-bar">
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
        <button class="send" :class="{ 'is-stop': busy }" @click="busy ? stopGenerating() : send()">
          {{ busy ? t('learn.stop') : t('learn.send') }}
        </button>
      </div>
      </div><!-- /composer-card -->
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
        v-if="showRightStage"
        class="split-divider stage-divider"
        :class="{ dragging: splitResizing }"
        role="separator"
        aria-orientation="vertical"
        tabindex="0"
        @pointerdown="startSplitDrag"
        @dblclick="resetSplit"
        @keydown.left.prevent="nudgeSplit(-0.02)"
        @keydown.right.prevent="nudgeSplit(0.02)"
      ></div>
      <div
        v-if="showRightStage"
        class="stage-backdrop"
        @click="closeStage"
      ></div>
      <aside
        v-if="showRightStage || (isResearch && (searchOpen || searchWasOpen))"
        v-show="showRightStage"
        class="stage-pane"
        :class="`stage-pane--${stageLayout}`"
        :style="{ width: `${splitRatio * 100}%` }"
        aria-label="Science Stage"
      >
        <header class="stage-head">
          <div class="stage-tabs" role="tablist">
            <button
              type="button"
              class="stage-tab"
              :class="{ on: isStageTabOn('figures'), active: stageTab === 'figures' }"
              @click="selectStageTab('figures')"
            >
              <span>{{ stageLabel('图解', 'Figures') }}</span>
              <span v-if="sessionDiagrams.length" class="stage-tab-count">{{ sessionDiagrams.length }}</span>
            </button>
            <button
              type="button"
              class="stage-tab"
              :class="{ on: isStageTabOn('files'), active: stageTab === 'files' }"
              @click="selectStageTab('files')"
            >
              <span>{{ stageLabel('文件与资料', 'Files') }}</span>
              <span v-if="sessionFiles.length" class="stage-tab-count">{{ sessionFiles.length }}</span>
            </button>
            <button
              v-if="isResearch"
              type="button"
              class="stage-tab"
              :class="{ on: isStageTabOn('reader'), active: stageTab === 'reader' }"
              @click="selectStageTab('reader')"
            >
              <span>{{ stageLabel('文献阅读', 'Reader') }}</span>
            </button>
          </div>
          <div class="stage-head-right">
            <!-- 多子窗布局切换器:单窗 / 上下双窗 / 多窗堆叠 -->
            <div class="stage-layout-switch" role="group" :aria-label="stageLabel('子窗口排版', 'Stage Layout')">
              <button
                type="button"
                class="layout-btn"
                :class="{ on: stageLayout === 'single' }"
                :title="stageLabel('单窗聚焦', 'Single Pane')"
                data-layout="single"
                @click="setStageLayout('single')"
              >▢</button>
              <button
                type="button"
                class="layout-btn"
                :class="{ on: stageLayout === 'split' }"
                :title="stageLabel('上下双窗分屏', 'Dual Split')"
                data-layout="split"
                @click="setStageLayout('split')"
              >⊟</button>
              <button
                type="button"
                class="layout-btn"
                :class="{ on: stageLayout === 'stack' }"
                :title="stageLabel('多子窗平铺堆叠', 'Multi-Pane Stack')"
                data-layout="stack"
                @click="setStageLayout('stack')"
              >▤</button>
            </div>
            <button
              class="stage-close"
              type="button"
              :aria-label="t('common.close')"
              @click="closeStage"
            >✕</button>
          </div>
        </header>

        <!-- 多子窗口停靠工作区 -->
        <div ref="stageDockRef" class="stage-dock">
          <!-- 双窗模式下可拖拽横向分隔条(通过 CSS order 精准置于两子窗之间) -->
          <div
            v-if="showStageRowDivider"
            class="stage-h-divider"
            :class="{ dragging: stageRowResizing }"
            role="separator"
            aria-orientation="horizontal"
            tabindex="0"
            @pointerdown="startStageRowDrag"
            @dblclick="resetStageRow"
            @keydown.up.prevent="nudgeStageRow(-0.04)"
            @keydown.down.prevent="nudgeStageRow(0.04)"
          ></div>

          <!-- 子窗口 1: 数学图解与 2D/3D/GeoGebra 画布 -->
          <section
            v-show="isPaneVisible('figures')"
            class="subwin"
            :class="{ 'subwin--focused': stageTab === 'figures', 'subwin--collapsed': stageCollapsed.figures && visibleStagePanes.length > 1 }"
            :style="paneFlexStyle('figures')"
            data-subwin="figures"
            @pointerdown="stageTab = 'figures'"
          >
            <header class="subwin-head">
              <span class="subwin-dot subwin-dot--primary"></span>
              <span class="subwin-title">{{ stageLabel('图解画布', 'Figures') }}</span>
              <span v-if="sessionDiagrams.length" class="subwin-count">{{ sessionDiagrams.length }}</span>
              <div class="subwin-tools">
                <button
                  v-if="visibleStagePanes.length > 1"
                  type="button"
                  class="subwin-btn subwin-collapse"
                  :title="stageCollapsed.figures ? stageLabel('展开子窗', 'Expand') : stageLabel('折叠子窗', 'Collapse')"
                  @click.stop="togglePaneCollapse('figures')"
                >{{ stageCollapsed.figures ? '+' : '−' }}</button>
                <button
                  v-if="visibleStagePanes.length > 1 || stageMaximized === 'figures'"
                  type="button"
                  class="subwin-btn subwin-max"
                  :title="stageMaximized === 'figures' ? stageLabel('还原分屏', 'Restore') : stageLabel('最大化子窗', 'Maximize')"
                  @click.stop="togglePaneMaximize('figures')"
                >{{ stageMaximized === 'figures' ? '⤡' : '⤢' }}</button>
                <button
                  type="button"
                  class="subwin-btn subwin-close"
                  :title="stageLabel('关闭子窗', 'Close Pane')"
                  @click.stop="closeSubPane('figures')"
                >✕</button>
              </div>
            </header>
            <div v-show="!stageCollapsed.figures || visibleStagePanes.length === 1" class="stage-body">
              <template v-if="activeStageFigure">
                <div v-if="sessionDiagrams.length > 1" class="stage-strip">
                  <button
                    v-for="(item, idx) in sessionDiagrams"
                    :key="item.key"
                    type="button"
                    class="stage-pill"
                    :class="{ on: activeStageFigure.key === item.key }"
                    @click="activeFigureKey = item.key"
                  >
                    <span class="stage-pill-idx">{{ String(sessionDiagrams.length - idx).padStart(2, '0') }}</span>
                    <span class="stage-pill-name">{{ item.title }}</span>
                  </button>
                </div>
                <div class="stage-card-head">
                  <div class="stage-card-meta">
                    <span class="tech-label stage-kicker">FIGURE · INTERACTIVE CANVAS</span>
                    <h3 class="stage-card-title">{{ activeStageFigure.title }}</h3>
                  </div>
                  <div class="stage-card-actions">
                    <button
                      type="button"
                      class="stage-action-btn"
                      @click="jumpTo(activeStageFigure.msgId)"
                    >{{ stageLabel('定位消息', 'Jump') }}</button>
                    <button
                      type="button"
                      class="stage-action-btn stage-action-btn--primary"
                      @click="openDiagramFocus(activeStageFigure.diagram, activeStageFigure.msgId)"
                    >{{ stageLabel('全幅聚焦', 'Focus') }}</button>
                  </div>
                </div>
                <div class="stage-figure-canvas">
                  <DiagramBoundary
                    :title="activeStageFigure.diagram.spec.title"
                    :notes="activeStageFigure.diagram.spec.annotations.map((note) => note.text)"
                  >
                    <DiagramBlockView :spec="activeStageFigure.diagram.spec" />
                  </DiagramBoundary>
                </div>
              </template>
              <div v-else class="stage-empty">
                <div class="stage-empty-glyph" aria-hidden="true">∫</div>
                <p class="stage-empty-title">{{ stageLabel('尚未生成数学图解', 'No figures in this session yet') }}</p>
                <p class="stage-empty-desc">
                  {{ stageLabel('在对话中提出几何、函数或矩阵问题，或点击回答下方的「生成图解」，2D/3D 与 GeoGebra 交互图表会自动汇聚到此子窗口。', 'Ask a geometry, calculus, or matrix question—or click Generate Diagram on any reply—to inspect 2D/3D and GeoGebra figures here.') }}
                </p>
              </div>
            </div>
          </section>

          <!-- 子窗口 2: 文件、图片、教材与科研数据表 -->
          <section
            v-show="isPaneVisible('files')"
            class="subwin"
            :class="{ 'subwin--focused': stageTab === 'files', 'subwin--collapsed': stageCollapsed.files && visibleStagePanes.length > 1 }"
            :style="paneFlexStyle('files')"
            data-subwin="files"
            @pointerdown="stageTab = 'files'"
          >
            <header class="subwin-head">
              <span class="subwin-dot subwin-dot--proof"></span>
              <span class="subwin-title">{{ stageLabel('文件与资料', 'Files & Context') }}</span>
              <span v-if="sessionFiles.length" class="subwin-count">{{ sessionFiles.length }}</span>
              <div class="subwin-tools">
                <button
                  v-if="visibleStagePanes.length > 1"
                  type="button"
                  class="subwin-btn subwin-collapse"
                  :title="stageCollapsed.files ? stageLabel('展开子窗', 'Expand') : stageLabel('折叠子窗', 'Collapse')"
                  @click.stop="togglePaneCollapse('files')"
                >{{ stageCollapsed.files ? '+' : '−' }}</button>
                <button
                  v-if="visibleStagePanes.length > 1 || stageMaximized === 'files'"
                  type="button"
                  class="subwin-btn subwin-max"
                  :title="stageMaximized === 'files' ? stageLabel('还原分屏', 'Restore') : stageLabel('最大化子窗', 'Maximize')"
                  @click.stop="togglePaneMaximize('files')"
                >{{ stageMaximized === 'files' ? '⤡' : '⤢' }}</button>
                <button
                  type="button"
                  class="subwin-btn subwin-close"
                  :title="stageLabel('关闭子窗', 'Close Pane')"
                  @click.stop="closeSubPane('files')"
                >✕</button>
              </div>
            </header>
            <div v-show="!stageCollapsed.files || visibleStagePanes.length === 1" class="stage-body">
              <template v-if="activeStageFile">
                <div v-if="sessionFiles.length > 1" class="stage-strip">
                  <button
                    v-for="file in sessionFiles"
                    :key="file.key"
                    type="button"
                    class="stage-pill"
                    :class="{ on: activeStageFile.key === file.key }"
                    @click="activeFileKey = file.key"
                  >
                    <span class="stage-pill-idx">{{ file.kind.toUpperCase() }}</span>
                    <span class="stage-pill-name">{{ file.title }}</span>
                  </button>
                </div>
                <div class="stage-card-head">
                  <div class="stage-card-meta">
                    <span class="tech-label stage-kicker">{{ activeStageFile.kind.toUpperCase() }} · {{ activeStageFile.subtitle }}</span>
                    <h3 class="stage-card-title">{{ activeStageFile.title }}</h3>
                  </div>
                  <div class="stage-card-actions">
                    <button
                      v-if="activeStageFile.msgId"
                      type="button"
                      class="stage-action-btn"
                      @click="jumpTo(activeStageFile.msgId)"
                    >{{ stageLabel('定位消息', 'Jump') }}</button>
                    <button
                      v-if="activeStageFile.kind === 'book'"
                      type="button"
                      class="stage-action-btn stage-action-btn--primary"
                      @click="runCommand('章节知识导航')"
                    >{{ cmdName('章节知识导航') }}</button>
                    <button
                      v-if="activeStageFile.kind === 'table'"
                      type="button"
                      class="stage-action-btn stage-action-btn--primary"
                      @click="router.push('/research/tables')"
                    >{{ t('tables.entry') }}</button>
                    <button
                      v-if="activeStageFile.kind === 'paper' && isResearch"
                      type="button"
                      class="stage-action-btn stage-action-btn--primary"
                      @click="selectStageTab('reader')"
                    >{{ stageLabel('打开阅读器', 'Open Reader') }}</button>
                  </div>
                </div>

                <div v-if="activeStageFile.kind === 'image' && activeStageFile.url" class="stage-img-wrap">
                  <img :src="activeStageFile.url" :alt="activeStageFile.title" class="stage-img" />
                </div>
                <div v-else-if="activeStageFile.preview" class="stage-doc-preview">
                  <div class="tech-label stage-preview-label">{{ stageLabel('文本节选预览', 'EXCERPT PREVIEW') }}</div>
                  <pre class="stage-preview-text">{{ activeStageFile.preview.slice(0, 2400) }}{{ activeStageFile.preview.length > 2400 ? '\n…' : '' }}</pre>
                </div>
                <div v-else class="stage-meta-card">
                  <p class="stage-meta-note">
                    {{ activeStageFile.kind === 'book'
                      ? stageLabel('教材已载入本地书库，点击上方「章节知识导航」可按目录切片精读。', 'Textbook cached locally. Click Chapter Navigation above to inspect by section.')
                      : activeStageFile.kind === 'paper'
                        ? stageLabel('论文已绑定为当前对话上下文，可直接追问定理细节或切到「文献阅读」对照全文。', 'Paper is active as conversation context. Ask about theorems directly or open Reader.')
                        : activeStageFile.kind === 'table'
                          ? stageLabel('实验数据表已接入科研推演上下文，提问时会自动携带结构化数据与回归模型。', 'Experimental table is linked to this session context along with its regression model.')
                          : stageLabel('文件已关联至当前会话，可直接围绕内容提问。', 'File is attached to this session and ready for follow-up questions.') }}
                  </p>
                </div>
              </template>
              <div v-else class="stage-empty">
                <div class="stage-empty-glyph" aria-hidden="true">◫</div>
                <p class="stage-empty-title">{{ stageLabel('当前会话暂无文件或资料', 'No files or attachments yet') }}</p>
                <p class="stage-empty-desc">
                  {{ stageLabel('拖入教材 PDF、题目照片、科研论文，或从数据表带入实验记录，即可在右侧实时对照查看。', 'Drop a textbook PDF, problem image, paper, or linked table to inspect side by side.') }}
                </p>
                <div class="stage-empty-actions">
                  <button type="button" class="stage-action-btn stage-action-btn--primary" @click="pickFile()">
                    ＋ {{ t('learn.attachFile') }}
                  </button>
                  <button type="button" class="stage-action-btn" @click="pickAlbum()">
                    {{ t('learn.attachAlbum') }}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <!-- 子窗口 3 (科研区): 文献全文检索与联动 PDF 阅读器 -->
          <section
            v-if="isResearch && (isPaneVisible('reader') || searchOpen || searchWasOpen)"
            v-show="isPaneVisible('reader')"
            class="subwin"
            :class="{ 'subwin--focused': stageTab === 'reader', 'subwin--collapsed': stageCollapsed.reader && visibleStagePanes.length > 1 }"
            :style="paneFlexStyle('reader')"
            data-subwin="reader"
            @pointerdown="stageTab = 'reader'"
          >
            <header class="subwin-head">
              <span class="subwin-dot subwin-dot--cite"></span>
              <span class="subwin-title">{{ stageLabel('文献检索与阅读', 'Literature Reader') }}</span>
              <div class="subwin-tools">
                <button
                  v-if="activeReaderPaper"
                  type="button"
                  class="subwin-pill-btn"
                  :class="{ on: isPaperInCompare }"
                  :title="t('stage.compareHint')"
                  @click.stop="toggleComparePaper"
                >{{ isPaperInCompare ? t('stage.inCompare') : t('stage.addCompare') }}</button>
                <button
                  v-if="compareIds.length >= 2"
                  type="button"
                  class="subwin-pill-btn on"
                  :disabled="compareRunning"
                  @click.stop="runCompareQueue"
                >{{ compareRunning ? '…' : t('stage.runCompare', { n: compareIds.length }) }}</button>
                <button
                  v-if="activeReaderPaper"
                  type="button"
                  class="subwin-pill-btn"
                  :class="{ on: readerInsightsOpen }"
                  :title="t('workspace.structure')"
                  @click.stop="toggleReaderInsights"
                >{{ t('workspace.structureToggle') }}</button>
                <button
                  v-if="visibleStagePanes.length > 1"
                  type="button"
                  class="subwin-btn subwin-collapse"
                  :title="stageCollapsed.reader ? stageLabel('展开子窗', 'Expand') : stageLabel('折叠子窗', 'Collapse')"
                  @click.stop="togglePaneCollapse('reader')"
                >{{ stageCollapsed.reader ? '+' : '−' }}</button>
                <button
                  v-if="visibleStagePanes.length > 1 || stageMaximized === 'reader'"
                  type="button"
                  class="subwin-btn subwin-max"
                  :title="stageMaximized === 'reader' ? stageLabel('还原分屏', 'Restore') : stageLabel('最大化子窗', 'Maximize')"
                  @click.stop="togglePaneMaximize('reader')"
                >{{ stageMaximized === 'reader' ? '⤡' : '⤢' }}</button>
                <button
                  type="button"
                  class="subwin-btn subwin-close"
                  :title="stageLabel('关闭子窗', 'Close Pane')"
                  @click.stop="closeSubPane('reader')"
                >✕</button>
              </div>
            </header>
            <div v-show="!stageCollapsed.reader || visibleStagePanes.length === 1" class="stage-reader">
              <div v-if="readerInsightsOpen && activeReaderPaper" class="stage-insights-wrap">
                <PaperInsights
                  :structure="readerInsightsStructure"
                  :loading="readerInsightsLoading"
                  :error="readerInsightsError"
                  :title="activeReaderPaper.title"
                  @refresh="loadReaderInsights(activeReaderPaper.docId, true)"
                />
              </div>
              <ResearchSearchView
                v-show="!readerInsightsOpen"
                ref="searchPaneRef"
                embedded
                @ask="onSplitAsk"
                @paper-change="onPaperChange"
              />
            </div>
          </section>
        </div>
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
  --ws-accent: var(--accent-primary);
  height: 100vh;
  /* iPad/手机 Safari 的 100vh 含工具栏区域,底部输入条会被切掉;dvh 跟随可见视口 */
  height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--bg-void);
}

.learn.ws-research {
  --ws-accent: var(--accent-cite);
}

.workspace-body {
  flex: 1;
  min-height: 0;
  display: flex;
}

/* ---------- 左侧可折叠科研仪器栏(宽屏桌面展示) ---------- */
.sci-rail {
  flex: none;
  width: 224px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 12px calc(14px + env(safe-area-inset-bottom));
  border-right: 1px solid var(--line);
  background: var(--surface-1);
  overflow-y: auto;
}

.rail-seg {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-0);
}

.rail-seg-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 500;
  padding: 6px 4px;
  border-radius: 6px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.rail-seg-btn:hover {
  color: var(--text-hi);
}

.rail-seg-btn.on {
  background: var(--bg-card);
  color: var(--text-hi);
  box-shadow: var(--shadow-sm);
}

.rail-section {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.rail-heading {
  font-size: 10px;
  padding: 2px 8px 4px;
  color: var(--text-dim);
}

.rail-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.rail-item:hover {
  background: var(--bg-card);
  color: var(--text-hi);
}

.rail-item--on {
  background: color-mix(in srgb, var(--ws-accent) 13%, var(--bg-card));
  border-color: color-mix(in srgb, var(--ws-accent) 34%, var(--line));
  color: var(--ws-accent);
  font-weight: 500;
}

.rail-icon {
  width: 18px;
  text-align: center;
  font-size: 12.5px;
  color: var(--ws-accent);
  flex: none;
}

.rail-text {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rail-tag {
  font-family: var(--font-tech);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-0);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.rail-badge {
  font-family: var(--font-tech);
  font-size: 10px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--ws-accent);
  color: #ffffff;
  font-variant-numeric: tabular-nums;
}

.rail-foot {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.rail-new {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
  color: var(--text-hi);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}

.rail-new:hover {
  border-color: var(--line-bright);
  color: var(--ws-accent);
}

.rail-voice {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 4px;
}

.rail-voice-label {
  font-size: 11.5px;
  color: var(--text-dim);
}

.rail-toggle {
  width: 32px;
  height: 32px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
  flex: none;
  transition: border-color var(--dur-fast), color var(--dur-fast), background-color var(--dur-fast);
}

.rail-toggle:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
  background: var(--bg-card);
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

.stage-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 11px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all var(--dur-fast) var(--ease-out);
}

.stage-toggle:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
  background: var(--bg-card);
}

.stage-toggle--on {
  color: var(--ws-accent);
  border-color: color-mix(in srgb, var(--ws-accent) 48%, var(--line));
  background: color-mix(in srgb, var(--ws-accent) 12%, var(--bg-card));
}

.stage-toggle-ico {
  font-size: 14px;
  line-height: 1;
}

.stage-toggle-badge {
  display: inline-grid;
  place-items: center;
  min-width: 17px;
  height: 17px;
  padding: 0 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ws-accent) 18%, var(--surface-0));
  color: var(--ws-accent);
  font-family: var(--font-tech);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}

/* ---------- 右侧可折叠科研演示台(AI for Science Stage) ---------- */
.stage-backdrop {
  display: none;
}

.stage-pane {
  flex: none;
  min-width: 300px;
  max-width: 60%;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-left: 1px solid var(--line);
  overflow: hidden;
}

.stage-head {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-1);
}

.stage-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-0);
}

.stage-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 500;
  padding: 5px 10px;
  border-radius: 6px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--dur-fast) var(--ease-out);
}

.stage-tab:hover {
  color: var(--text-hi);
}

.stage-tab.on {
  background: var(--bg-card);
  color: var(--text-hi);
  box-shadow: var(--shadow-sm);
}

.stage-tab-count {
  font-family: var(--font-tech);
  font-size: 10px;
  padding: 0 5px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--ws-accent) 16%, transparent);
  color: var(--ws-accent);
  font-variant-numeric: tabular-nums;
}

.stage-head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: none;
}

.stage-layout-switch {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-0);
}

.layout-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all var(--dur-fast) var(--ease-out);
}

.layout-btn:hover {
  color: var(--text-hi);
}

.layout-btn.on {
  background: var(--bg-card);
  color: var(--ws-accent);
  box-shadow: var(--shadow-sm);
}

/* ---------- 多子窗口停靠容器与子窗外壳 ---------- */
.stage-dock {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 8px;
  gap: 8px;
  overflow: hidden;
  background: var(--surface-0);
}

.stage-pane--split .stage-dock {
  gap: 0;
}

.stage-h-divider {
  order: 1;
  flex: none;
  height: 8px;
  cursor: row-resize;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
}

.stage-h-divider::before {
  content: "";
  width: 44px;
  height: 3px;
  border-radius: 999px;
  background: var(--line);
  transition: background-color var(--dur-fast), width var(--dur-fast);
}

.stage-h-divider:hover::before,
.stage-h-divider:focus-visible::before,
.stage-h-divider.dragging::before {
  width: 68px;
  background: var(--ws-accent);
}

.stage-h-divider:focus-visible {
  outline: none;
}

.subwin {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-1);
  overflow: hidden;
  transition: border-color var(--dur-fast) var(--ease-out);
}

.subwin--focused {
  border-color: color-mix(in srgb, var(--ws-accent) 42%, var(--line));
}

.subwin--collapsed {
  flex: 0 0 auto !important;
}

.subwin-head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-card);
  user-select: none;
}

.subwin--collapsed .subwin-head {
  border-bottom: none;
}

.subwin-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}

.subwin-dot--primary {
  background: var(--accent-primary);
}

.subwin-dot--proof {
  background: var(--accent-proof);
}

.subwin-dot--cite {
  background: var(--accent-cite);
}

.subwin-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-hi);
  letter-spacing: 0.01em;
}

.subwin-count {
  font-family: var(--font-tech);
  font-size: 10px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--surface-0);
  border: 1px solid var(--line);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}

.subwin-tools {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.subwin-btn {
  width: 22px;
  height: 22px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all var(--dur-fast) var(--ease-out);
}

.subwin-btn:hover {
  color: var(--text-hi);
  border-color: var(--line);
  background: var(--surface-1);
}

.subwin-pill-btn {
  height: 22px;
  padding: 0 8px;
  border: 1px solid var(--line);
  border-radius: 5px;
  background: var(--surface-1);
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--dur-fast) var(--ease-out);
}

.subwin-pill-btn:hover,
.subwin-pill-btn.on {
  color: var(--accent-cite);
  border-color: color-mix(in srgb, var(--accent-cite) 48%, var(--line));
  background: color-mix(in srgb, var(--accent-cite) 12%, var(--surface-1));
}

.stage-insights-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
}

.stage-insights-wrap :deep(.pi) {
  width: 100%;
  min-width: 0;
  border-left: none;
  background: var(--surface-1);
}

.prereq-btn {
  color: var(--accent-primary);
  border-color: color-mix(in srgb, var(--accent-primary) 40%, var(--line));
}

.prereq-btn:hover {
  color: var(--accent-primary);
  background: color-mix(in srgb, var(--accent-primary) 12%, var(--surface-1));
}

.stage-close {
  flex: none;
  width: 28px;
  height: 28px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 13px;
  display: grid;
  place-items: center;
  transition: all var(--dur-fast) var(--ease-out);
}

.stage-close:hover {
  color: var(--text-hi);
  border-color: var(--line);
  background: var(--bg-card);
}

.stage-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.stage-strip {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 2px;
  scrollbar-width: thin;
}

.stage-pill {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 190px;
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-0);
  color: var(--text-dim);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.stage-pill:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
}

.stage-pill.on {
  color: var(--ws-accent);
  border-color: color-mix(in srgb, var(--ws-accent) 50%, var(--line));
  background: color-mix(in srgb, var(--ws-accent) 10%, var(--bg-card));
}

.stage-pill-idx {
  font-family: var(--font-tech);
  font-size: 10px;
  opacity: 0.78;
}

.stage-pill-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stage-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
}

.stage-card-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.stage-kicker {
  font-size: 10px;
  color: var(--ws-accent);
}

.stage-card-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 15px;
  font-weight: 600;
  color: var(--text-hi);
  line-height: 1.35;
  word-break: break-word;
}

.stage-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex: none;
}

.stage-action-btn {
  padding: 5px 10px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--surface-1);
  color: var(--text);
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--dur-fast) var(--ease-out);
}

.stage-action-btn:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
}

.stage-action-btn--primary {
  background: color-mix(in srgb, var(--ws-accent) 14%, var(--surface-1));
  border-color: color-mix(in srgb, var(--ws-accent) 45%, var(--line));
  color: var(--ws-accent);
  font-weight: 500;
}

.stage-figure-canvas {
  flex: 1;
  min-height: 280px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background-color: var(--surface-0);
  background-image:
    linear-gradient(to right, color-mix(in srgb, var(--line) 42%, transparent) 1px, transparent 1px),
    linear-gradient(to bottom, color-mix(in srgb, var(--line) 42%, transparent) 1px, transparent 1px);
  background-size: 28px 28px;
  padding: 10px;
  overflow: auto;
}

.stage-img-wrap {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface-0);
  padding: 12px;
  display: grid;
  place-items: center;
}

.stage-img {
  max-width: 100%;
  max-height: 58vh;
  max-height: 58dvh;
  border-radius: 6px;
  object-fit: contain;
}

.stage-doc-preview {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
  padding: 12px 14px;
}

.stage-preview-label {
  font-size: 10px;
  color: var(--text-dim);
}

.stage-preview-text {
  margin: 0;
  flex: 1;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-ui);
  font-size: 12.5px;
  line-height: 1.72;
  color: var(--text);
}

.stage-meta-card {
  border: 1px solid var(--line);
  border-left: 2px solid var(--ws-accent);
  border-radius: 0 10px 10px 0;
  background: var(--bg-card);
  padding: 14px 16px;
}

.stage-meta-note {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
}

.stage-empty {
  flex: 1;
  min-height: 240px;
  border: 1px dashed var(--line);
  border-radius: 12px;
  background: color-mix(in srgb, var(--surface-0) 60%, transparent);
  padding: 28px 22px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 8px;
}

.stage-empty-glyph {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--bg-card);
  color: var(--ws-accent);
  font-family: var(--font-serif);
  font-size: 22px;
  display: grid;
  place-items: center;
  margin-bottom: 4px;
}

.stage-empty-title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: 15.5px;
  font-weight: 500;
  color: var(--text-hi);
}

.stage-empty-desc {
  margin: 0;
  max-width: 34ch;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-dim);
}

.stage-empty-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}

.stage-reader {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.stage-reader > :deep(*) {
  flex: 1;
  min-height: 0;
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
  background: var(--surface-1);
  border-left: 1px solid var(--line);
  overflow: hidden;
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
  gap: 12px;
  padding: calc(10px + env(safe-area-inset-top)) 20px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-1);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 6px 13px;
  cursor: pointer;
  border-radius: 7px;
  font-size: 12.5px;
  transition: all var(--dur-fast) var(--ease-out);
}

.back:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
  background: var(--bg-card);
}

.title-box {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.title {
  color: var(--text-hi);
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.sub {
  font-size: 10px;
  color: var(--ws-accent);
}

.right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}

@media (min-width: 961px) {
  /* 宽屏左栏展开时,检索/数据表/新建对话已在左栏常驻,隐藏顶栏重复按钮 */
  .learn.rail-open .header-dup {
    display: none;
  }

  /* 三栏同时展开时适度收紧中间阅读列左右内边距,保留宽裕阅读空间 */
  .learn.stage-open .chat-list {
    padding: 20px 18px 24px;
  }

  .learn.stage-open .input-bar {
    padding-left: 16px;
    padding-right: 16px;
  }
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

/* ---------- 出版级对话与证明文档流 ---------- */
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px 28px;
}

.chat-stream {
  width: 100%;
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.origin-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent-cite) 10%, var(--bg-panel));
  border: 1px solid color-mix(in srgb, var(--accent-cite) 30%, var(--line));
}
.origin-meta {
  font-size: 12px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}
.origin-back {
  flex: none;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid color-mix(in srgb, var(--accent-cite) 45%, var(--line));
  background: var(--bg-card);
  color: var(--accent-cite);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}
.origin-back:hover {
  background: color-mix(in srgb, var(--accent-cite) 14%, var(--bg-card));
}

.msg {
  display: flex;
  width: 100%;
  scroll-margin: 20px 0;
}

.msg.user {
  justify-content: flex-start;
}

.bubble {
  width: 100%;
  max-width: 100%;
  font-size: 14.5px;
  line-height: 1.82;
}

.cell-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.cell-role {
  font-size: 10px;
  letter-spacing: 0.12em;
  color: var(--text-dim);
}

.cell-meta--assistant .cell-role {
  color: var(--ws-accent);
}

.cell-pill {
  font-size: 9.5px;
  padding: 1px 7px;
  border-radius: 999px;
  border: 1px solid var(--line);
}

.cell-pill--cite {
  color: var(--accent-cite);
  border-color: color-mix(in srgb, var(--accent-cite) 38%, var(--line));
  background: color-mix(in srgb, var(--accent-cite) 10%, transparent);
}

.user-text {
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-hi);
}

.msg.user .bubble {
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 13px 18px;
  color: var(--text-hi);
}

.msg.assistant .bubble {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-left: 2.5px solid var(--ws-accent);
  border-radius: 10px;
  padding: 16px 20px;
  box-shadow: var(--shadow-sm);
}

.msg-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--line);
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

/* 停止生成后的续写按钮(统一收拢在 .msg-actions 内) */
.resume-btn {
  padding: 4px 12px;
  border: 1px solid var(--line-bright);
  border-radius: 7px;
  background: color-mix(in srgb, var(--ws-accent) 10%, transparent);
  color: var(--ws-accent);
  font-size: 11.5px;
  cursor: pointer;
  margin-left: auto;
  transition: all var(--dur-fast) var(--ease-out);
}

.resume-btn:hover {
  background: color-mix(in srgb, var(--ws-accent) 18%, transparent);
}

/* 研究综述导出:小按钮 + 语言选择菜单 */
.export-btn {
  display: inline-block;
  padding: 4px 12px;
  border: 1px solid color-mix(in srgb, var(--accent-cite) 45%, var(--line));
  border-radius: 7px;
  background: color-mix(in srgb, var(--accent-cite) 10%, transparent);
  color: var(--accent-cite);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.export-btn:hover {
  background: color-mix(in srgb, var(--accent-cite) 18%, transparent);
}

.export-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}

.diagram-btn {
  display: inline-block;
  padding: 4px 11px;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-1);
  color: var(--text-dim);
  font-size: 11.5px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.diagram-btn:hover {
  color: var(--text-hi);
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

/* ---------- 一体化科研输入工作台 ---------- */
.input-bar {
  position: relative; /* 问题记录面板与附件弹层以此为定位锚点 */
  border-top: 1px solid var(--line);
  background: var(--surface-0);
  padding: 12px 24px calc(14px + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.composer-card {
  width: 100%;
  max-width: 1080px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 8px 12px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
}

.composer-card:focus-within {
  border-color: var(--line-bright);
  box-shadow: var(--focus-ring);
}

.context-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 2px;
}

.ai4s-tools-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 2px 4px;
  border-bottom: 1px solid color-mix(in srgb, var(--line) 65%, transparent);
  overflow-x: auto;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
}
.ai4s-tools-bar::-webkit-scrollbar { display: none; }
.ai4s-pill {
  flex: none;
  height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-dim);
  font-size: 11.5px;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.ai4s-pill:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
}
.ai4s-pill.active {
  color: var(--ws-accent);
  background: color-mix(in srgb, var(--ws-accent) 13%, var(--bg-panel));
  border-color: color-mix(in srgb, var(--ws-accent) 42%, var(--line));
  font-weight: 500;
}

.rail-project {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 6px;
}
.rail-project-select {
  width: 100%;
  min-width: 0;
  padding: 6px 8px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--bg-card);
  color: var(--text-hi);
  font-size: 12px;
}
.rail-report-btn {
  width: 100%;
  padding: 5px 8px;
  border-radius: 7px;
  border: 1px solid color-mix(in srgb, var(--ws-accent) 40%, var(--line));
  background: color-mix(in srgb, var(--ws-accent) 10%, var(--bg-card));
  color: var(--ws-accent);
  font-size: 11.5px;
  cursor: pointer;
}
.rail-report-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.workspace-body.with-focus .input-bar {
  padding: 8px 12px calc(10px + env(safe-area-inset-bottom));
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
  gap: 8px;
}

.input {
  flex: 1;
  min-width: 0;
  resize: none;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-hi);
  font-family: var(--font-ui);
  font-size: 14px;
  line-height: 1.6;
  padding: 9px 8px;
  outline: none;
  max-height: 160px;
}

.input::placeholder {
  color: var(--text-dim);
}

.diagram-toggle {
  background: var(--surface-1);
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 9px 11px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  white-space: nowrap;
  transition: all var(--dur-fast) var(--ease-out);
}

.diagram-toggle.on {
  color: var(--ws-accent);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--ws-accent) 12%, var(--surface-1));
}

.send {
  background: var(--ws-accent);
  border: 1px solid var(--ws-accent);
  color: #ffffff;
  padding: 9px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  transition: filter var(--dur-fast) var(--ease-out), opacity var(--dur-fast);
}

.send:hover:not(:disabled) {
  filter: brightness(1.08);
}

.send:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

/* 停止生成态:暖黄色警示,点击中断当前回答 */
.send.is-stop {
  color: var(--warn);
  border-color: color-mix(in srgb, var(--warn) 55%, transparent);
  background: color-mix(in srgb, var(--warn) 12%, transparent);
}

.send.is-stop:hover {
  background: color-mix(in srgb, var(--warn) 20%, transparent);
  filter: none;
}

/* ---------- 指令栏(窄屏或左栏收起时显示;宽屏左栏展开时自动让位给阅读区) ---------- */
.commands {
  width: 100%;
  max-width: 1080px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

@media (min-width: 961px) {
  .learn.rail-open .commands {
    display: none;
  }
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
  background: var(--ws-accent);
  color: #ffffff;
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
  min-width: 0;
  max-width: 100%;
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
.palette-trigger {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 5px 8px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 11.5px;
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
  transition: all var(--dur-fast) var(--ease-out);
}
.palette-trigger:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

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
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: var(--surface-1);
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
  width: 38px;
  height: 38px;
  border-radius: 8px;
  background: var(--surface-1);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
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
  color: var(--accent-cite);
  border: 1px solid color-mix(in srgb, var(--accent-cite) 38%, var(--line));
  border-radius: 999px;
  padding: 0 6px;
}

/* 窄屏(平板竖屏/手机 ≤960px):自动隐藏桌面左侧仪器栏,无缝回落到底部单行指令条;
   右侧科研演示台改为贴边抽屉浮层,不挤占主阅读区 */
@media (max-width: 960px) {
  .sci-rail,
  .rail-toggle,
  .stage-divider {
    display: none;
  }

  .stage-backdrop {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 44;
    background: rgba(3, 6, 12, 0.45);
    backdrop-filter: blur(2px);
  }

  .stage-pane {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 45;
    width: min(480px, calc(100% - 24px)) !important;
    min-width: 0;
    max-width: none;
    height: 100vh;
    height: 100dvh;
    padding-top: env(safe-area-inset-top);
    padding-bottom: env(safe-area-inset-bottom);
    box-shadow: var(--shadow-lg);
  }

  .stage-toggle-label,
  .stage-layout-switch,
  .stage-h-divider,
  .subwin-collapse,
  .subwin-max {
    display: none;
  }

  .stage-tabs {
    overflow-x: auto;
    scrollbar-width: none;
    max-width: calc(100% - 36px);
  }

  .stage-tabs::-webkit-scrollbar {
    display: none;
  }

  .stage-card-head {
    flex-wrap: wrap;
  }

  /* 窄屏抽屉空间有限,多子窗退回为聚焦子窗单页浏览 */
  .stage-dock .subwin:not(.subwin--focused) {
    display: none;
  }

  .stage-dock .subwin.subwin--focused {
    flex: 1 1 auto !important;
  }

  .input-bar {
    padding: 10px 12px calc(12px + env(safe-area-inset-bottom));
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

@media (max-width: 600px) {
  .chat-header {
    flex-wrap: wrap;
    gap: 8px;
    padding: calc(8px + env(safe-area-inset-top)) 10px 8px;
  }

  .chat-header .sub {
    display: none;
  }

  .title {
    font-size: 13px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .right {
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .session-chip {
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .stage-pane {
    width: 100% !important;
    padding-left: env(safe-area-inset-left);
    padding-right: env(safe-area-inset-right);
    border-left: none;
  }

  .stage-dock {
    padding: 6px;
  }

  .stage-toggle {
    padding: 0 8px;
  }

  .chat-list {
    padding: 14px 12px;
  }

  .msg.user .bubble,
  .msg.assistant .bubble {
    padding: 12px 14px;
  }

  .input-bar {
    padding: 10px 10px calc(10px + env(safe-area-inset-bottom));
  }

  .composer-card {
    padding: 6px 8px;
  }

  .input-row {
    gap: 6px;
  }

  .diagram-toggle {
    padding: 9px 8px;
  }

  .send {
    padding: 9px 14px;
  }
}
</style>
