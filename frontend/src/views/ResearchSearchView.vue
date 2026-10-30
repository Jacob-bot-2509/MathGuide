<script setup lang="ts">
/**
 * 科研文献检索(search-first):先检索自己的论文全文,再基于命中片段提问。
 * 检索在服务端完成:BM25 + embedding 混合排序,章节树先筛节点;
 * 命中带论文名、章节与页码,可直接作为提问依据。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import {
  createTempPaper,
  deletePaperHistory,
  importTempPaper,
  listPaperHistory,
  listPaperTrash,
  relatedLiterature,
  resolveLiteratureOa,
  restorePaperHistory,
  searchLiterature,
  type HistoryItem,
  type LiteratureItem,
} from '@/services/literatureService'
import { listAnnotations } from '@/services/researchAnnotationService'
import DocumentViewer from '@/components/research/DocumentViewer.vue'
import {
  clearResearchDocs,
  compareResearchDocs,
  deleteResearchDoc,
  listResearchDocs,
  listResearchProjects,
  locatePaperPassages,
  searchResearch,
  uploadResearchDoc,
  type ResearchDoc,
  type ResearchHit,
  type ResearchProject,
} from '@/services/researchService'
import { createResearchTable } from '@/services/researchTableService'

const props = defineProps<{ embedded?: boolean }>()
const emit = defineEmits<{
  ask: [prompt: string]
  'paper-change': [paper: { docId: string; title: string } | null]
}>()

type SearchMode = 'local' | 'web'
const SEARCH_MODE_KEY = 'mg-search-mode'

const router = useRouter()
const route = useRoute()
const docs = ref<ResearchDoc[]>([])
const projects = ref<ResearchProject[]>([])
const query = ref('')
const hits = ref<ResearchHit[]>([])
const searched = ref(false)
const loading = ref(false)
const uploading = ref(false)
const uploadEl = ref<HTMLInputElement | null>(null)
const selectedDocIds = ref<string[]>([])
const comparing = ref(false)
const knownDocIds = new Set<string>()
const activeProject = ref('')
const useTree = ref(false)
const mode = ref('')
const elapsed = ref(0)
const searchMode = ref<SearchMode>(loadSearchMode())
const authorFilter = ref('')
const yearFrom = ref('')
const yearTo = ref('')
const litField = ref<'general' | 'math' | 'physics' | 'chemistry' | 'biology'>('general')
const peerOnly = ref(true)
const includePreprints = ref(false)
const oaOnly = ref(false)
const resolvingOa = ref('')
const advancedOpen = ref(false)
const litItems = ref<LiteratureItem[]>([])
const litLoading = ref(false)
const litSearched = ref(false)
const litWarnings = ref<string[]>([])
const litIdentifier = ref<{ type: string; value: string } | null>(null)
const openingPdf = ref('')
const importingDoc = ref('')
const historyOpen = ref(false)
const historyTab = ref<'active' | 'trash'>('active')
const historyItems = ref<HistoryItem[]>([])
const trashItems = ref<HistoryItem[]>([])
const historyLoading = ref(false)
let litSeq = 0

const hasDocs = computed(() => docs.value.length > 0)
const busy = computed(() =>
  searchMode.value === 'local' ? loading.value : litLoading.value)

/** 输入框里出现 DOI / arXiv / PMCID / PMID 时提示将按编号精确检索 */
const identifierHint = computed(() => {
  const text = query.value
  const doi = text.match(/\b10\.\d{4,9}\/[^\s"'<>]+/i)
  if (doi) return { type: 'DOI', value: doi[0].replace(/[.,;)\]}]+$/, '') }
  const arxiv = text.match(/(?:arxiv:\s*)?(\d{4}\.\d{4,5})(?:v\d+)?\b/i)
  if (arxiv) return { type: 'arXiv', value: arxiv[1] }
  const pmcid = text.match(/\b(PMC\d{6,})\b/i)
  if (pmcid) return { type: 'PMCID', value: pmcid[1].toUpperCase() }
  const pmid = text.match(/\bPMID[:\s]*(\d{6,9})\b/i)
  if (pmid) return { type: 'PMID', value: pmid[1] }
  return null
})

function loadSearchMode(): SearchMode {
  try {
    return localStorage.getItem(SEARCH_MODE_KEY) === 'web' ? 'web' : 'local'
  } catch {
    return 'local'
  }
}

function setSearchMode(value: SearchMode): void {
  searchMode.value = value
  if (value === 'local') historyOpen.value = false
  try {
    localStorage.setItem(SEARCH_MODE_KEY, value)
  } catch {
    /* 忽略 */
  }
}

/** 新导入的论文默认勾选;用户取消后不会被后续刷新重新选上 */
function syncSelection(): void {
  const ids = docs.value.map((d) => d.id)
  const selected = new Set(selectedDocIds.value.filter((id) => ids.includes(id)))
  for (const id of ids) {
    if (!knownDocIds.has(id)) selected.add(id)
  }
  knownDocIds.clear()
  ids.forEach((id) => knownDocIds.add(id))
  selectedDocIds.value = ids.filter((id) => selected.has(id))
}

function toggleDoc(id: string): void {
  const set = new Set(selectedDocIds.value)
  if (set.has(id)) set.delete(id)
  else set.add(id)
  selectedDocIds.value = docs.value.map((d) => d.id).filter((x) => set.has(x))
}

function selectAllDocs(): void {
  selectedDocIds.value = docs.value.map((d) => d.id)
}

function clearSelectedDocs(): void {
  selectedDocIds.value = []
}

/** 勾选 2~6 篇 → 模型逐篇抽取 → 建对比表并打开 */
async function compareSelected(): Promise<void> {
  if (comparing.value || selectedDocIds.value.length < 2) return
  comparing.value = true
  try {
    const data = await compareResearchDocs(selectedDocIds.value)
    const selectedProjects = new Set(
      docs.value
        .filter((d) => selectedDocIds.value.includes(d.id) && d.projectId)
        .map((d) => d.projectId as string),
    )
    const projectId = activeProject.value
      || (selectedProjects.size === 1 ? [...selectedProjects][0] : null)
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
    const query: Record<string, string> = { tableId: created.id }
    if (projectId) query.projectId = projectId
    await router.push({ path: '/research/tables', query })
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.compareFail'))
  } finally {
    comparing.value = false
  }
}

/** 外部文献发现:只取元数据/摘要,不下载全文;seq 保证只认最后一次查询 */
async function searchExternal(qArg?: string): Promise<void> {
  const q = (qArg ?? query.value).trim()
  if (q.length < 2) return
  historyOpen.value = false
  const seq = ++litSeq
  litLoading.value = true
  try {
    const res = await searchLiterature(q, {
      limit: 20,
      author: authorFilter.value.trim() || undefined,
      yearFrom: Number(yearFrom.value) || null,
      yearTo: Number(yearTo.value) || null,
      field: litField.value,
      peerReviewed: peerOnly.value,
      includePreprints: includePreprints.value,
      oaOnly: oaOnly.value,
    })
    if (seq !== litSeq) return
    litItems.value = res.results
    litWarnings.value = res.warnings
    litIdentifier.value = res.identifier ?? null
    litSearched.value = true
  } catch (err) {
    if (seq !== litSeq) return
    showToast(err instanceof Error && err.message ? err.message : t('search.litFail'))
  } finally {
    if (seq === litSeq) litLoading.value = false
  }
}

/** 以库内论文为种子找相关论文 */
async function findRelated(doc: ResearchDoc): Promise<void> {
  const seq = ++litSeq
  litLoading.value = true
  try {
    const res = await relatedLiterature({ doi: doc.doi, title: doc.title || doc.name })
    if (seq !== litSeq) return
    litItems.value = res.results
    litWarnings.value = res.warnings
    litSearched.value = true
    document.querySelector('.lit')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch (err) {
    if (seq !== litSeq) return
    showToast(err instanceof Error && err.message ? err.message : t('search.litFail'))
  } finally {
    if (seq === litSeq) litLoading.value = false
  }
}

interface ViewerState {
  docId: string
  title: string
  kind: 'pdf' | 'text'
  page?: number
  projectId?: string | null
}

const viewer = ref<ViewerState | null>(null)
const viewerRef = ref<{ showPassages: (items: { page: number; quote: string }[]) => Promise<void> } | null>(null)

/** 对话提问时定位当前论文的命中段落,交给阅读器高亮 */
async function locateForQuestion(question: string): Promise<void> {
  if (!viewer.value) return
  try {
    const res = await locatePaperPassages(viewer.value.docId, question)
    await viewerRef.value?.showPassages(res.passages)
  } catch {
    /* 定位失败不影响回答 */
  }
}

watch(viewer, (value) => {
  emit('paper-change', value ? { docId: value.docId, title: value.title } : null)
})

defineExpose({ locateForQuestion })

/** 打开出版社落地页;不经过服务端代理 */
function openLanding(item: LiteratureItem): void {
  const url = item.landingUrl || item.url
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function openFreeCopy(item: LiteratureItem): void {
  if (item.oaUrl) {
    window.open(item.oaUrl, '_blank', 'noopener,noreferrer')
    return
  }
  if (item.pdfUrl) void openExternalPaper(item)
}

/** 按 DOI 查 Unpaywall/OpenAlex;找到合法 OA 地址后打开 */
async function findFreeCopy(item: LiteratureItem): Promise<void> {
  if (!item.doi || resolvingOa.value === item.doi) return
  resolvingOa.value = item.doi
  try {
    const res = await resolveLiteratureOa(item.doi)
    if (res.error) {
      showToast(t('search.oaFail'))
    } else if (res.isOa && res.oaUrl) {
      item.oaUrl = res.oaUrl
      item.oaStatus = res.oaStatus
      if (res.license) item.license = res.license
      window.open(res.oaUrl, '_blank', 'noopener,noreferrer')
    } else {
      showToast(t('search.noFree'))
    }
  } catch {
    showToast(t('search.oaFail'))
  } finally {
    resolvingOa.value = ''
  }
}

function pdfReaderAllowed(url: string): boolean {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.toLowerCase()
    return parsed.protocol === 'https:' && (
      host === 'arxiv.org' || host.endsWith('.arxiv.org') ||
      host === 'europepmc.org' || host.endsWith('.europepmc.org') ||
      host === 'ebi.ac.uk' || host.endsWith('.ebi.ac.uk') ||
      host === 'ncbi.nlm.nih.gov' || host.endsWith('.ncbi.nlm.nih.gov')
    )
  } catch {
    return false
  }
}

function tempMeta(item: LiteratureItem) {
  return {
    title: item.title,
    issn: item.issn,
    publisher: item.publisher,
    articleType: item.articleType,
    peerReviewed: item.peerReviewed,
    oaStatus: item.oaStatus,
    license: item.license,
    landingUrl: item.landingUrl || item.url,
    retractionStatus: item.retractionStatus,
    versionOf: item.versionOf,
    accessSource: item.oaStatus && !['unknown', 'closed'].includes(item.oaStatus)
      ? 'oa' : undefined,
  }
}

/** 外部论文:先临时入库,再在覆盖层阅读;已入库直接读本地文件 */
async function openExternalPaper(item: LiteratureItem): Promise<void> {
  if (!item.pdfUrl || openingPdf.value) return
  // 非白名单 PDF(出版社 OA 等)只外跳,不经过服务端下载
  if (!pdfReaderAllowed(item.pdfUrl)) {
    window.open(item.pdfUrl, '_blank', 'noopener,noreferrer')
    return
  }
  if (item.imported && item.docId) {
    viewer.value = {
      docId: item.docId, title: item.title, kind: 'pdf',
      projectId: activeProject.value || null,
    }
    return
  }
  if (item.tempDocId) {
    viewer.value = {
      docId: item.tempDocId, title: item.title, kind: 'pdf',
      projectId: activeProject.value || null,
    }
    return
  }
  openingPdf.value = item.pdfUrl
  try {
    const res = await createTempPaper(item.pdfUrl, tempMeta(item))
    item.tempDocId = res.docId
    viewer.value = {
      docId: res.docId,
      title: item.title || res.title || 'PDF',
      kind: 'pdf',
      projectId: activeProject.value || null,
    }
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.pdfFail'))
  } finally {
    openingPdf.value = ''
  }
}

/** 导入外部论文:有批注时先问是否保留 */
async function importPaper(item: LiteratureItem): Promise<void> {
  if (!item.pdfUrl || importingDoc.value) return
  if (item.imported && item.docId) {
    showToast(t('search.alreadyImported'))
    return
  }
  importingDoc.value = item.pdfUrl
  try {
    let docId = item.tempDocId || ''
    if (!docId) {
      const temp = await createTempPaper(item.pdfUrl, tempMeta(item))
      docId = temp.docId
      item.tempDocId = docId
    }
    let keep = true
    try {
      const notes = await listAnnotations(docId)
      if (notes.length) {
        keep = window.confirm(t('search.keepAnnotations', { n: notes.length }))
      }
    } catch {
      /* 读取批注失败时按保留处理 */
    }
    const res = await importTempPaper(docId, activeProject.value || undefined, keep)
    item.imported = true
    item.docId = docId
    item.tempDocId = ''
    await loadDocs()
    showToast(res.duplicate ? t('search.alreadyImported') : t('search.imported'))
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.importFail'))
  } finally {
    importingDoc.value = ''
  }
}

/** 我的论文:按原文件类型选 PDF 或文本阅读器 */
function openLocalPaper(doc: ResearchDoc, startPage = 0): void {
  viewer.value = {
    docId: doc.id,
    title: doc.title || doc.name,
    kind: /\.pdf$/i.test(doc.name) ? 'pdf' : 'text',
    page: startPage || undefined,
    projectId: doc.projectId ?? null,
  }
}

/** 从数据表来源跳转:?docId=...&page=... 打开对应论文页 */
function openDocFromQuery(): void {
  const docId = typeof route.query.docId === 'string' ? route.query.docId : ''
  if (!docId) return
  const rawPage = typeof route.query.page === 'string' ? Number(route.query.page) : 0
  const startPage = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 0
  const doc = docs.value.find((d) => d.id === docId)
  if (doc) {
    openLocalPaper(doc, startPage)
    return
  }
  // 表格来源可能来自尚未导入的临时论文:不在「我的论文」列表里,但仍可按 docId 打开
  const title = typeof route.query.title === 'string' ? route.query.title : 'PDF'
  viewer.value = { docId, title, kind: 'pdf', page: startPage || undefined }
}

function closeViewer(): void {
  viewer.value = null
}

async function loadHistory(): Promise<void> {
  historyLoading.value = true
  try {
    const [active, trash] = await Promise.all([listPaperHistory(), listPaperTrash()])
    historyItems.value = active
    trashItems.value = trash
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('history.fail'))
  } finally {
    historyLoading.value = false
  }
}

async function toggleHistory(): Promise<void> {
  if (searchMode.value !== 'web') return
  historyOpen.value = !historyOpen.value
  if (historyOpen.value) await loadHistory()
}

function openHistoryItem(item: HistoryItem): void {
  viewer.value = { docId: item.id, title: item.title, kind: 'pdf' }
}

async function removeHistory(item: HistoryItem): Promise<void> {
  if (!window.confirm(t('history.deleteConfirm'))) return
  try {
    await deletePaperHistory(item.id)
    await loadHistory()
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('history.fail'))
  }
}

async function restoreHistory(item: HistoryItem): Promise<void> {
  try {
    await restorePaperHistory(item.id)
    await loadHistory()
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('history.fail'))
  }
}

function fmtHistoryDate(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleDateString()
}

/** 命中片段高亮:先转义再包 <mark>,查询按空格拆词(至少 2 字符) */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function highlight(text: string, q: string): string {
  const escaped = escapeHtml(text)
  const terms = q.trim().split(/\s+/).filter((x) => x.length >= 2)
  if (!terms.length) return escaped
  const pattern = terms
    .map((x) => escapeHtml(x).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    .join('|')
  try {
    return escaped.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>')
  } catch {
    return escaped
  }
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadDocs(): Promise<void> {
  try {
    const [ds, ps] = await Promise.all([listResearchDocs(), listResearchProjects()])
    docs.value = ds
    projects.value = ps
    syncSelection()
  } catch {
    /* 未登录/后端不可达时不打断页面,检索时会再报 */
  }
}

function pickFile(): void {
  uploadEl.value?.click()
}

async function onFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (uploading.value) return
  uploading.value = true
  try {
    const res = await uploadResearchDoc(file)
    if (res.duplicate) {
      showToast(t('search.duplicate'))
    } else {
      showToast(t('search.uploaded', { n: res.pages ?? 0, c: res.chunks ?? 0 }))
    }
    await loadDocs()
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.uploadFail'))
  } finally {
    uploading.value = false
  }
}

async function doSearch(): Promise<void> {
  const q = query.value.trim()
  if (!q) return
  if (searchMode.value === 'web') {
    if (litLoading.value) return
    await searchExternal(q)
    return
  }
  if (loading.value) return
  if (!selectedDocIds.value.length) {
    showToast(t('search.selectDocs'))
    return
  }
  loading.value = true
  searched.value = true
  try {
    const res = await searchResearch(q, {
      docIds: selectedDocIds.value,
      projectId: activeProject.value || undefined,
      tree: useTree.value,
    })
    hits.value = res.hits
    mode.value = res.mode
    elapsed.value = res.elapsed
  } catch {
    hits.value = []
    showToast(t('search.searchFail'))
  } finally {
    loading.value = false
  }
}

async function removeDoc(doc: ResearchDoc): Promise<void> {
  if (!window.confirm(t('search.deleteConfirm'))) return
  try {
    await deleteResearchDoc(doc.id)
    selectedDocIds.value = selectedDocIds.value.filter((id) => id !== doc.id)
    await loadDocs()
  } catch {
    showToast(t('search.deleteFail'))
  }
}

async function clearAll(): Promise<void> {
  if (!window.confirm(t('search.clearConfirm'))) return
  try {
    const removed = await clearResearchDocs()
    selectedDocIds.value = []
    hits.value = []
    searched.value = false
    await loadDocs()
    showToast(t('search.cleared', { n: removed }))
  } catch {
    showToast(t('search.clearFail'))
  }
}

/** 把命中片段作为证据带进科研对话:检索决定材料,模型只组织回答 */
function askFromResults(): void {
  if (!hits.value.length) return
  const evidence = hits.value
    .slice(0, 6)
    .map((h) => `[${h.docName} · ${h.section} · 第 ${h.pageStart}-${h.pageEnd} 页]\n${h.snippet}`)
    .join('\n\n')
    .slice(0, 6000)
  const prompt = `请只依据以下检索资料回答问题;资料不足时明确说明,不要补充资料以外的内容。\n\n问题:${query.value.trim()}\n\n${evidence}`
  if (props.embedded) {
    emit('ask', prompt)
    return
  }
  sessionStorage.setItem('mg-research-seed', prompt)
  router.push('/research')
}

onMounted(async () => {
  await loadDocs()
  openDocFromQuery()
})
</script>

<template>
  <div class="rs" :class="{ embedded }">
    <header v-if="!embedded" class="rs-head">
      <button class="back" @click="router.push('/research')">{{ t('search.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t('search.title') }}</span>
        <span class="tech-label sub">MODULE 02 · SEARCH</span>
      </div>
      <div class="head-right">
        <button class="act" :disabled="uploading" @click="pickFile">
          {{ uploading ? t('search.uploading') : t('search.upload') }}
        </button>
        <button class="act ghost" @click="router.push('/research')">{{ t('search.toChat') }}</button>
      </div>
    </header>

    <input
      ref="uploadEl"
      type="file"
      hidden
      accept=".pdf,.docx,.epub,.html,.htm,.xml,.rtf,.txt,.md,.markdown,.tex,.csv,.json,text/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/epub+zip,application/rtf"
      @change="onFile"
    />

    <div v-if="embedded" class="rs-embed-bar">
      <span class="tech-label">{{ t('search.title') }}</span>
      <span class="embed-spacer"></span>
      <button class="act" :disabled="uploading" @click="pickFile">
        {{ uploading ? t('search.uploading') : t('search.upload') }}
      </button>
      <button class="act ghost" @click="router.push('/research/search')">
        {{ t('search.openPage') }}
      </button>
    </div>

    <main class="rs-main" :class="{ embedded }">
      <!-- 论文库:勾选参与文内检索的论文 -->
      <section v-if="searchMode === 'local'" class="panel">
        <div class="panel-head">
          <span class="tech-label">{{ t('search.docs') }}</span>
          <span class="count">{{ docs.length }}</span>
          <span class="doc-selected">{{ t('search.selectedDocs', { n: selectedDocIds.length, total: docs.length }) }}</span>
          <button v-if="hasDocs" class="pick-all" @click="selectAllDocs">{{ t('search.selectAll') }}</button>
          <button v-if="hasDocs" class="pick-all" @click="clearSelectedDocs">{{ t('search.selectNone') }}</button>
          <button
            v-if="hasDocs"
            class="compare-btn"
            :disabled="selectedDocIds.length < 2 || comparing"
            :title="t('search.compareHint')"
            @click="compareSelected"
          >{{ comparing ? t('search.comparing') : t('search.compare') }}</button>
          <button v-if="hasDocs" class="clear-all" @click="clearAll">{{ t('search.clearDocs') }}</button>
        </div>
        <p v-if="!hasDocs" class="empty">{{ t('search.noDocs') }}</p>
        <ul v-else class="doc-list">
          <li v-for="d in docs" :key="d.id" class="doc-item">
            <label class="doc-check">
              <input
                type="checkbox"
                :checked="selectedDocIds.includes(d.id)"
                @change="toggleDoc(d.id)"
              />
            </label>
            <button class="doc-name" :title="t('viewer.open')" @click="openLocalPaper(d)">
              {{ d.title || d.name }}
            </button>
            <span class="doc-meta">
              {{ fmtSize(d.size) }} · {{ d.pages }} 页<span v-if="d.year"> · {{ d.year }}</span><span v-if="d.doi"> · {{ d.doi }}</span>
            </span>
            <button class="rel" :title="t('search.related')" @click="findRelated(d)">
              {{ t('search.relatedShort') }}
            </button>
            <button class="del" :title="t('search.delete')" @click="removeDoc(d)">✕</button>
          </li>
        </ul>
        <p class="hint">{{ t('search.uploadHint') }}</p>
      </section>

      <!-- 检索区:文内 / 文外两种方向互不干扰 -->
      <section class="search-box">
        <div class="mode-row">
          <button
            class="mode-btn"
            :class="{ on: searchMode === 'local' }"
            @click="setSearchMode('local')"
          >{{ t('search.modeLocal') }}</button>
          <button
            class="mode-btn"
            :class="{ on: searchMode === 'web' }"
            @click="setSearchMode('web')"
          >{{ t('search.modeWeb') }}</button>
          <span class="mode-hint">
            {{ searchMode === 'local' ? t('search.modeLocalHint') : t('search.modeWebHint') }}
          </span>
        </div>
        <div class="search-row">
          <input
            v-model="query"
            class="search-input"
            :placeholder="searchMode === 'local' ? t('search.placeholderLocal') : t('search.placeholderWeb')"
            @keydown.enter="doSearch"
          />
          <button class="search-btn" :disabled="busy || !query.trim()" @click="doSearch">
            {{ busy
              ? t('search.loading')
              : searchMode === 'local' ? t('search.searchLocal') : t('search.searchWeb') }}
          </button>
        </div>
        <p v-if="identifierHint && searchMode === 'web'" class="id-hint">
          {{ t('search.identifierHint', { type: identifierHint.type, value: identifierHint.value }) }}
        </p>
        <div v-if="searchMode === 'web'" class="adv">
          <button class="adv-toggle" @click="advancedOpen = !advancedOpen">
            {{ advancedOpen ? '− ' : '+ ' }}{{ t('search.advanced') }}
          </button>
          <div v-if="advancedOpen" class="adv-fields">
            <input v-model="authorFilter" class="adv-input" :placeholder="t('search.author')" />
            <input v-model="yearFrom" class="adv-input year" inputmode="numeric" :placeholder="t('search.yearFrom')" />
            <span class="adv-dash">–</span>
            <input v-model="yearTo" class="adv-input year" inputmode="numeric" :placeholder="t('search.yearTo')" />
          </div>
        </div>
        <div v-if="searchMode === 'web'" class="lit-filters">
          <select v-model="litField" class="adv-input field-select">
            <option value="general">{{ t('search.fieldGeneral') }}</option>
            <option value="math">{{ t('search.fieldMath') }}</option>
            <option value="physics">{{ t('search.fieldPhysics') }}</option>
            <option value="chemistry">{{ t('search.fieldChemistry') }}</option>
            <option value="biology">{{ t('search.fieldBiology') }}</option>
          </select>
          <label class="opt">
            <input v-model="peerOnly" type="checkbox" />
            {{ t('search.peerOnly') }}
          </label>
          <label class="opt">
            <input v-model="includePreprints" type="checkbox" />
            {{ t('search.includePreprints') }}
          </label>
          <label class="opt">
            <input v-model="oaOnly" type="checkbox" />
            {{ t('search.oaOnly') }}
          </label>
        </div>
        <div v-if="searchMode === 'local'" class="opts">
          <select v-model="activeProject" class="project-filter">
            <option value="">{{ t('search.allProjects') }}</option>
            <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
          </select>
          <label class="opt">
            <input v-model="useTree" type="checkbox" />
            {{ t('search.tree') }}
          </label>
          <span v-if="searched && !loading" class="stat">
            {{ t('search.stat', { n: hits.length, mode: mode === 'hybrid' ? t('search.modeHybrid') : t('search.modeBm25'), s: elapsed }) }}
          </span>
        </div>
      </section>

      <!-- 文内结果 -->
      <section v-if="searchMode === 'local'" class="results">
        <p v-if="searched && !loading && !hits.length" class="empty">{{ t('search.empty') }}</p>
        <article v-for="(h, i) in hits" :key="h.docId + h.nodeId + i" class="hit">
          <div class="hit-head">
            <span class="hit-idx tech-label">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="hit-doc">{{ h.docName }}</span>
            <span class="hit-page">{{ t('search.page', { a: h.pageStart, b: h.pageEnd }) }}</span>
            <span class="hit-score tech-label">{{ h.score.toFixed(4) }}</span>
          </div>
          <div class="hit-section">{{ h.section }}</div>
          <p class="hit-text" v-html="highlight(h.snippet, query)"></p>
        </article>
        <button v-if="hits.length" class="ask-btn" @click="askFromResults">
          {{ t('search.askResults') }}
        </button>
      </section>

      <!-- 外部文献发现 -->
      <section v-if="searchMode === 'web'" class="lit">
        <div class="lit-head">
          <span class="tech-label">
            {{ t('search.litTitle') }}<template v-if="litItems.length"> · {{ litItems.length }}</template>
          </span>
          <button
            class="lit-btn"
            :disabled="litLoading || query.trim().length < 2"
            @click="searchExternal()"
          >
            {{ litLoading ? t('search.litLoading') : t('search.litSearch') }}
          </button>
          <button
            class="lit-btn"
            :class="{ on: historyOpen }"
            @click="toggleHistory"
          >
            {{ historyOpen ? t('history.backResults') : t('history.title') }}
            <template v-if="!historyOpen && historyItems.length"> · {{ historyItems.length }}</template>
          </button>
        </div>
        <p class="hint">{{ t('search.litHint') }}</p>

        <section v-if="historyOpen" class="history">
          <div class="hist-head">
            <button
              class="hist-tab"
              :class="{ on: historyTab === 'active' }"
              @click="historyTab = 'active'"
            >{{ t('history.active') }} · {{ historyItems.length }}</button>
            <button
              class="hist-tab"
              :class="{ on: historyTab === 'trash' }"
              @click="historyTab = 'trash'"
            >{{ t('history.trash') }} · {{ trashItems.length }}</button>
            <span class="hist-loading" v-if="historyLoading">{{ t('viewer.loading') }}</span>
          </div>
          <template v-if="historyTab === 'active'">
            <p v-if="!historyItems.length" class="empty">{{ t('history.empty') }}</p>
            <div v-for="item in historyItems" :key="item.id" class="hist-item">
              <button class="hist-title" @click="openHistoryItem(item)">
                {{ item.title }}
              </button>
              <span class="hist-meta">
                {{ t('history.pages', { n: item.pages }) }} ·
                {{ t('history.notes', { n: item.annotations }) }}
                <template v-if="item.lastViewedAt"> · {{ fmtHistoryDate(item.lastViewedAt) }}</template>
              </span>
              <button class="hist-action" @click="removeHistory(item)">{{ t('history.delete') }}</button>
            </div>
          </template>
          <template v-else>
            <p v-if="!trashItems.length" class="empty">{{ t('history.trashEmpty') }}</p>
            <div v-for="item in trashItems" :key="item.id" class="hist-item">
              <span class="hist-title static">{{ item.title }}</span>
              <span class="hist-meta">{{ t('history.daysLeft', { n: item.daysLeft ?? 0 }) }}</span>
              <button class="hist-action" @click="restoreHistory(item)">{{ t('history.restore') }}</button>
            </div>
          </template>
        </section>

        <template v-if="!historyOpen">
        <p v-if="litIdentifier" class="id-hint">
          {{ t('search.identified', {
            type: litIdentifier.type.toUpperCase(),
            value: litIdentifier.value,
            n: litItems.length,
          }) }}
        </p>
        <p v-if="litSearched && !litLoading && !litItems.length" class="empty">
          {{ t('search.litEmpty') }}
        </p>
        <p v-if="litWarnings.length" class="lit-warn">
          {{ t('search.litPartial', { s: litWarnings.join(' / ') }) }}
        </p>
        <article v-for="(item, i) in litItems" :key="(item.doi || item.title) + i" class="lit-item">
          <div class="lit-top">
            <a
              v-if="item.url"
              class="lit-title"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
            >{{ item.title }}</a>
            <span v-else class="lit-title">{{ item.title }}</span>
            <span v-if="item.year" class="lit-year">{{ item.year }}</span>
          </div>
          <p v-if="item.authors || item.venue" class="lit-meta">
            {{ item.authors }}<span v-if="item.venue"> · {{ item.venue }}</span>
          </p>
          <p class="lit-badges">
            <span v-if="item.venueTier" class="lit-badge tier" :class="`t-${item.venueTier}`">
              {{ item.venueTier }} · {{ item.venueLabel || item.venue || item.sources.join(' · ') }}
            </span>
            <span v-if="item.peerReviewed" class="lit-badge peer">{{ t('search.peerReviewed') }}</span>
            <span v-else-if="item.articleType === 'preprint'" class="lit-badge preprint">
              {{ t('search.preprint') }}
            </span>
            <span v-if="item.retractionStatus === 'retracted'" class="lit-badge retracted">
              {{ t('search.retracted') }}
            </span>
            <span
              v-if="item.oaStatus && !['unknown', 'closed'].includes(item.oaStatus)"
              class="lit-badge oa"
            >{{ t('search.freeFullText') }}</span>
          </p>
          <p v-if="item.abstract" class="lit-abstract">{{ item.abstract }}</p>
          <p class="lit-foot">
            <span v-if="item.doi" class="lit-doi">{{ item.doi }}</span>
            <span v-if="item.citations" class="lit-cite">
              {{ t('search.litCited', { n: item.citations }) }}
            </span>
            <span class="lit-src">{{ item.sources.join(' · ') }}</span>
            <button v-if="item.landingUrl || item.url" class="lit-pdf" @click="openLanding(item)">
              {{ t('search.viewSource') }}
            </button>
            <button
              v-if="item.oaUrl && !item.pdfUrl"
              class="lit-pdf free"
              @click="openFreeCopy(item)"
            >{{ t('search.freeFullText') }}</button>
            <button
              v-else-if="item.doi && !item.pdfUrl"
              class="lit-pdf"
              :disabled="resolvingOa === item.doi"
              @click="findFreeCopy(item)"
            >{{ resolvingOa === item.doi ? t('search.oaSearching') : t('search.findFree') }}</button>
            <button
              v-if="item.pdfUrl"
              class="lit-pdf"
              :disabled="openingPdf === item.pdfUrl"
              @click="openExternalPaper(item)"
            >
              {{ openingPdf === item.pdfUrl ? t('search.openingPdf') : t('search.viewPdf') }}
            </button>
            <button
              v-if="item.pdfUrl && !item.imported"
              class="lit-import"
              :disabled="importingDoc === item.pdfUrl"
              @click="importPaper(item)"
            >
              {{ importingDoc === item.pdfUrl ? t('search.importing') : t('search.importPaper') }}
            </button>
            <button v-else-if="item.imported" class="lit-import done" disabled>
              {{ t('search.imported') }}
            </button>
          </p>
        </article>
        </template>
      </section>
    </main>

    <DocumentViewer
      v-if="viewer"
      ref="viewerRef"
      :doc-id="viewer.docId"
      :title="viewer.title"
      :kind="viewer.kind"
      :start-page="viewer.page"
      :project-id="viewer.projectId ?? (activeProject || null)"
      @close="closeViewer"
    />
  </div>
</template>

<style scoped>
.rs {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.rs.embedded {
  min-height: 0;
  height: 100%;
  width: 100%;
  border-left: 1px solid var(--line);
  background: var(--bg);
  overflow: hidden;
}

.rs-embed-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  flex: none;
}

.embed-spacer {
  flex: 1;
}

.rs-main.embedded {
  width: 100%;
  margin: 0;
  padding: 14px 16px 28px;
  min-height: 0;
  overflow-y: auto;
}

.rs.embedded .panel {
  max-height: 160px;
  overflow-y: auto;
}

.rs-main.embedded .search-box {
  order: -1;
}

.rs-head {
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
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
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

.head-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
}

.act {
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
}

.act:disabled {
  opacity: 0.55;
  cursor: wait;
}

.act.ghost {
  background: transparent;
  color: var(--text-dim);
  border-color: var(--line);
}

.rs-main {
  flex: 1;
  width: min(980px, calc(100% - 44px));
  margin: 0 auto;
  padding: 22px 0 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel,
.search-box,
.hit {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.panel {
  padding: 14px 16px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--cyan);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.count {
  font-family: var(--font-tech);
  color: var(--text-dim);
}

.clear-all {
  background: transparent;
  border: 1px solid rgba(255, 138, 138, 0.35);
  color: #ff8a8a;
  border-radius: 6px;
  padding: 3px 9px;
  font-size: 10.5px;
  cursor: pointer;
}

.clear-all:hover {
  background: rgba(255, 138, 138, 0.08);
}

.doc-filter {
  margin-left: auto;
  max-width: 45%;
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
}

.doc-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow-y: auto;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
}

.doc-item:hover {
  background: color-mix(in srgb, var(--cyan) 5%, transparent);
}

.doc-name {
  flex: 1;
  min-width: 0;
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: transparent;
  border: none;
  padding: 0;
  text-align: left;
  cursor: pointer;
}

.doc-name:hover {
  color: var(--cyan);
}

.doc-meta {
  color: var(--text-dim);
  font-size: 10.5px;
}

.del {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
}

.rel {
  flex: none;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 10.5px;
  cursor: pointer;
}

.rel:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.del:hover {
  color: #ff8a8a;
}

.hint {
  margin: 10px 0 0;
  color: var(--text-dim);
  font-size: 11px;
}

.search-box {
  padding: 14px 16px;
}

.search-row {
  display: flex;
  gap: 10px;
}

.search-input {
  flex: 1;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  padding: 11px 14px;
  font-size: 14px;
  outline: none;
}

.search-input:focus {
  border-color: var(--line-bright);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cyan) 10%, transparent);
}

.search-btn {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 0 26px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.opts {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
}

.lit-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  margin-top: 8px;
}

.lit-filters .adv-input.field-select {
  width: 130px;
}

.opt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 11.5px;
}

.project-filter {
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11.5px;
  max-width: 220px;
}

.stat {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 11px;
  font-family: var(--font-tech);
}

.results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hit {
  padding: 13px 16px;
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hit-idx {
  color: var(--cyan);
  font-size: 10px;
}

.hit-doc {
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-page {
  color: var(--text-dim);
  font-size: 10.5px;
}

.hit-score {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10px;
}

.hit-section {
  margin-top: 4px;
  color: var(--cyan);
  font-size: 11px;
}

.hit-text {
  margin: 7px 0 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.hit-text :deep(mark) {
  background: color-mix(in srgb, var(--cyan) 28%, transparent);
  color: var(--text-hi);
  border-radius: 2px;
  padding: 0 1px;
}

.empty {
  color: var(--text-dim);
  font-size: 12.5px;
  line-height: 1.7;
  text-align: center;
  padding: 26px 8px;
}

.ask-btn {
  align-self: flex-start;
  margin-top: 4px;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 7px 18px;
  font-size: 12.5px;
  cursor: pointer;
}

.ask-btn:hover {
  box-shadow: var(--glow-cyan);
}

.lit {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px 22px 30px;
  border-top: 1px solid var(--line);
}

.lit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.lit-btn {
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 6px 16px;
  font-size: 12px;
  cursor: pointer;
}

.lit-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.lit-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

.lit-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--bg-panel) 85%, transparent);
}

.lit-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}

.lit-title {
  color: var(--text-hi);
  font-size: 13.5px;
  line-height: 1.45;
  text-decoration: none;
}

.lit-title:hover {
  color: var(--cyan);
}

.lit-year {
  flex: none;
  color: var(--text-dim);
  font-size: 11px;
}

.lit-meta {
  color: var(--text-dim);
  font-size: 11.5px;
}

.lit-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
}

.lit-badge {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 9.5px;
  color: var(--text-dim);
}

.lit-badge.tier {
  display: inline-block;
  vertical-align: middle;
  max-width: min(520px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--cyan);
  border-color: var(--line-bright);
}

.lit-badge.tier.t-T0,
.lit-badge.tier.t-T1 {
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

.lit-badge.peer {
  color: #7ee787;
  border-color: color-mix(in srgb, #7ee787 40%, transparent);
}

.lit-badge.preprint {
  color: #f6c85f;
  border-color: color-mix(in srgb, #f6c85f 40%, transparent);
}

.lit-badge.retracted {
  color: #ff8a8a;
  border-color: color-mix(in srgb, #ff8a8a 45%, transparent);
}

.lit-badge.oa {
  color: #7ee787;
  border-color: color-mix(in srgb, #7ee787 40%, transparent);
}

.lit-abstract {
  color: var(--text);
  font-size: 12px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.lit-foot {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: var(--text-dim);
  font-size: 10.5px;
}

.lit-src {
  margin-left: auto;
}

.lit-doi {
  color: var(--cyan);
  word-break: break-all;
}

.lit-pdf {
  margin-left: 0;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 10.5px;
  cursor: pointer;
}

.lit-pdf.free {
  background: color-mix(in srgb, #7ee787 10%, transparent);
  border-color: color-mix(in srgb, #7ee787 45%, transparent);
  color: #7ee787;
}

.lit-pdf:disabled {
  opacity: 0.5;
  cursor: default;
}

.lit-import {
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 10.5px;
  cursor: pointer;
}

.lit-import:disabled {
  opacity: 0.55;
  cursor: default;
}

.lit-import.done {
  border-color: var(--line);
  color: var(--text-dim);
}

.lit-warn {
  color: #ffd166;
  font-size: 11px;
}

.mode-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.mode-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 11.5px;
  cursor: pointer;
}

.mode-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

.mode-hint {
  color: var(--text-dim);
  font-size: 10.5px;
}

.id-hint {
  margin-top: 8px;
  color: var(--cyan);
  font-size: 11px;
}

.adv {
  margin-top: 10px;
}

.adv-toggle {
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
}

.adv-toggle:hover {
  color: var(--cyan);
}

.adv-fields {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
}

.adv-input {
  flex: 1;
  min-width: 0;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  padding: 5px 8px;
  font-size: 11.5px;
}

.adv-input.year {
  flex: none;
  width: 76px;
}

.adv-dash {
  color: var(--text-dim);
}

.doc-check {
  display: flex;
  align-items: center;
  flex: none;
}

.doc-check input {
  accent-color: var(--cyan);
  cursor: pointer;
}

.doc-selected {
  color: var(--text-dim);
  font-size: 10.5px;
}

.pick-all {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 10px;
  cursor: pointer;
}

.pick-all:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.compare-btn {
  background: color-mix(in srgb, var(--cyan) 9%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 10px;
  cursor: pointer;
}

.compare-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.compare-btn:not(:disabled):hover {
  box-shadow: var(--glow-cyan);
}

.history {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px 14px;
}

.hist-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-bottom: 6px;
}

.hist-tab {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 10.5px;
  cursor: pointer;
}

.hist-tab.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.hist-loading {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10.5px;
}

.hist-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 4px;
  border-top: 1px solid var(--line);
}

.hist-title {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  color: var(--text-hi);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 0;
}

.hist-title:hover {
  color: var(--cyan);
}

.hist-title.static {
  cursor: default;
}

.hist-meta {
  flex: none;
  color: var(--text-dim);
  font-size: 10.5px;
}

.hist-action {
  flex: none;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 999px;
  padding: 1px 9px;
  font-size: 10px;
  cursor: pointer;
}

.hist-action:hover {
  color: #ff8a8a;
  border-color: #ff8a8a66;
}
</style>
