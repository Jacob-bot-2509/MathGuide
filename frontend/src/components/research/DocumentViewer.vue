<script setup lang="ts">
/**
 * 论文阅读器覆盖层:PDF 用 PDF.js 渲染,非 PDF 用文本分页接口。
 * 支持选中文本建批注;批注先存本地草稿,关闭时统一决定是否保存。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import { getToken } from '@/stores/user'
import {
  getResearchDocMeta,
  type ResearchDoc,
} from '@/services/researchService'
import {
  deleteAnnotation,
  listAnnotations,
  saveAnnotation,
  type Annotation,
  type AnnotationInput,
} from '@/services/researchAnnotationService'
import { explainRegion, extractPaperTable, type ExtractedPaperTable } from '@/services/researchService'
import TableExtractDialog from '@/components/research/TableExtractDialog.vue'

const props = withDefaults(defineProps<{
  docId: string
  title: string
  kind: 'pdf' | 'text'
  startPage?: number
  projectId?: string | null
  /** 连续下拉阅读:PDF 全部页面纵向堆叠,不显示翻页与页码跳转 */
  scrollMode?: boolean
}>(), { scrollMode: false })
const emit = defineEmits<{ close: []; pageChange: [page: number] }>()

/* 来源元数据:失败不阻塞阅读,只少一行徽标。 */
const docMeta = ref<ResearchDoc | null>(null)
const hasMeta = computed(() => {
  const meta = docMeta.value
  if (!meta) return false
  return Boolean(
    meta.venue || meta.peerReviewed || meta.articleType === 'preprint'
    || meta.license
    || meta.retractionStatus === 'retracted' || meta.landingUrl
    || (meta.oaStatus && meta.oaStatus !== 'unknown' && meta.oaStatus !== 'closed'),
  )
})

async function loadDocMeta(): Promise<void> {
  const docId = props.docId
  docMeta.value = null
  try {
    const meta = await getResearchDocMeta(docId)
    if (docId === props.docId) docMeta.value = meta
  } catch {
    if (docId === props.docId) docMeta.value = null
  }
}

onMounted(loadDocMeta)

const fileUrl = computed(() =>
  `/api/research/docs/${encodeURIComponent(props.docId)}/file`)
const textUrl = computed(() =>
  `/api/research/docs/${encodeURIComponent(props.docId)}/text`)

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

const canvasEl = ref<HTMLCanvasElement | null>(null)
const textLayerEl = ref<HTMLDivElement | null>(null)
const bodyEl = ref<HTMLElement | null>(null)
const page = ref(props.startPage && props.startPage > 0 ? props.startPage : 1)
watch(page, (value) => emit('pageChange', value))
const scrollPdf = computed(() => props.scrollMode && props.kind === 'pdf')
const total = ref(0)
const scale = ref(1.2)
const expanded = ref(false)
const loading = ref(true)
const error = ref('')
const textBody = ref('')
const autoFit = ref(true)
const displayText = computed(() => textBody.value.replace(/^#{1,6}\s+/gm, ''))

/* ---------- 批注 ---------- */
type PendingOp =
  | { kind: 'save'; tempId: string; input: AnnotationInput }
  | { kind: 'delete'; id: string }

const annotations = ref<Annotation[]>([])
const pendingOps = ref<PendingOp[]>([])
const dirty = computed(() => pendingOps.value.length > 0)
const pageAnnotations = computed(() =>
  annotations.value.filter((a) => a.page === page.value))
const notesOpen = ref(false)
const confirmClose = ref(false)
const saving = ref(false)

interface SelectionDraft {
  quote: string
  rects: number[][]
  page: number
  x: number
  y: number
}
const selection = ref<SelectionDraft | null>(null)
const noteText = ref('')
const editing = ref<Annotation | null>(null)
const editNote = ref('')
const editColor = ref('yellow')
const ANNOT_COLORS = ['yellow', 'cyan', 'green', 'red']

/* ---------- 区域解释(图表/公式) ---------- */
const regionMode = ref(false)
const region = ref<{ x: number; y: number; w: number; h: number } | null>(null)
const regionShot = ref<{ mime: string; data: string } | null>(null)
const regionQuestion = ref('')
const regionAnswer = ref('')
const regionLoading = ref(false)
let regionStart: { x: number; y: number } | null = null

function pagePoint(e: MouseEvent, pageNumber?: number): { x: number; y: number } | null {
  const canvas = pageNumber ? canvasEls.get(pageNumber) : canvasEl.value
  const wrap = canvas?.parentElement
  if (!canvas || !wrap) return null
  const rect = wrap.getBoundingClientRect()
  return {
    x: Math.max(0, Math.min(rect.width, e.clientX - rect.left)),
    y: Math.max(0, Math.min(rect.height, e.clientY - rect.top)),
  }
}

function toggleRegion(): void {
  regionMode.value = !regionMode.value
  region.value = null
  if (regionMode.value) clearSelection()
}

function onRegionDown(e: MouseEvent, pageNumber?: number): void {
  if (!regionMode.value || props.kind !== 'pdf') return
  const targetPage = pageNumber ?? page.value
  const point = pagePoint(e, pageNumber)
  if (!point) return
  e.preventDefault()
  page.value = targetPage
  regionPage.value = targetPage
  regionStart = point
  region.value = { x: point.x, y: point.y, w: 0, h: 0 }
  // 原生文本选择会吞掉后续 mouseover,拖拽改用窗口级事件
  window.addEventListener('mousemove', onRegionMove)
  window.addEventListener('mouseup', onRegionUp, { once: true })
}

function onRegionMove(e: MouseEvent): void {
  if (!regionStart || !region.value) return
  const point = pagePoint(e, regionPage.value)
  if (!point) return
  region.value = {
    x: Math.min(regionStart.x, point.x),
    y: Math.min(regionStart.y, point.y),
    w: Math.abs(point.x - regionStart.x),
    h: Math.abs(point.y - regionStart.y),
  }
}

function onRegionUp(): void {
  window.removeEventListener('mousemove', onRegionMove)
  if (!regionStart || !region.value) return
  regionStart = null
  const area = region.value
  if (area.w < 10 || area.h < 10) {
    region.value = null
    return
  }
  const canvas = canvasEl.value
  if (!canvas) return
  const shown = canvas.getBoundingClientRect()
  if (!shown.width || !shown.height) return
  const factor = canvas.width / shown.width
  const out = document.createElement('canvas')
  out.width = Math.max(1, Math.min(1600, Math.round(area.w * factor)))
  out.height = Math.max(1, Math.min(1600, Math.round(area.h * factor)))
  const ctx = out.getContext('2d')
  if (!ctx) return
  ctx.drawImage(
    canvas,
    area.x * factor, area.y * factor, area.w * factor, area.h * factor,
    0, 0, out.width, out.height,
  )
  const url = out.toDataURL('image/png')
  regionShot.value = { mime: 'image/png', data: url.split(',')[1] || '' }
  regionMode.value = false
  regionQuestion.value = ''
  regionAnswer.value = ''
}

async function askRegion(): Promise<void> {
  if (!regionShot.value || regionLoading.value) return
  regionLoading.value = true
  try {
    const res = await explainRegion(
      props.docId, regionShot.value,
      regionQuestion.value.trim() || t('viewer.regionDefaultAsk'))
    regionAnswer.value = res.answer
    regionShot.value = null
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('viewer.regionFail'))
  } finally {
    regionLoading.value = false
  }
}

/* ---------- 区域表格转录 ---------- */
const tableLoading = ref(false)
const tablePreview = ref<{
  preview: ExtractedPaperTable
  docId: string
  docName: string
  page: number
} | null>(null)

async function extractRegionTable(): Promise<void> {
  if (!regionShot.value || tableLoading.value) return
  tableLoading.value = true
  try {
    const res = await extractPaperTable(props.docId, regionShot.value, page.value)
    tablePreview.value = {
      preview: res.table,
      docId: res.docId,
      docName: props.title || res.docName,
      page: res.page || page.value,
    }
    regionShot.value = null
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('viewer.extractFail'))
  } finally {
    tableLoading.value = false
  }
}
const hits = ref<{ page: number; rects: number[][] }[]>([])
const pageHits = computed(() => hits.value.filter((h) => h.page === page.value))
const textHits = ref<{ start: number; end: number }[]>([])

function buildTextMap(root: HTMLElement): { nodes: { node: Text; start: number }[]; full: string } {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const nodes: { node: Text; start: number }[] = []
  let full = ''
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent || ''
    if (!text) continue
    nodes.push({ node: node as Text, start: full.length })
    full += text
  }
  return { nodes, full }
}

/** 归一化空白后按整段引文定位;跨 span 时返回覆盖整段的 Range */
function findQuoteRange(root: HTMLElement, quote: string): Range | null {
  const { nodes, full } = buildTextMap(root)
  if (!full) return null

  let norm = ''
  const back: number[] = []
  let lastSpace = false
  for (let i = 0; i < full.length; i++) {
    const ch = full[i]
    const isSpace = /\s/.test(ch)
    if (isSpace) {
      if (lastSpace) continue
      norm += ' '
      back.push(i)
      lastSpace = true
    } else {
      norm += ch.toLowerCase()
      back.push(i)
      lastSpace = false
    }
  }
  const target = quote.replace(/\s+/g, ' ').trim().toLowerCase()
  let matchLength = target.length
  let index = target ? norm.indexOf(target) : -1
  if (index < 0 && target.length > 60) {
    matchLength = 60
    index = norm.indexOf(target.slice(0, matchLength))
  }
  if (index < 0) {
    // 退回最长词,避免整段空白差异导致完全不画框
    const words = quote.match(/[\p{L}\p{N}]{4,}/gu) || []
    words.sort((a, b) => b.length - a.length)
    const word = (words[0] || quote.trim().slice(0, 12)).toLowerCase()
    index = norm.indexOf(word)
    matchLength = word.length
  }
  if (index < 0 || !matchLength) return null
  const startOrig = back[index]
  const endOrig = back[Math.min(back.length - 1, index + matchLength - 1)] + 1
  const startNode = [...nodes].reverse().find((n) => n.start <= startOrig)
  const endNode = [...nodes].reverse().find((n) => n.start < endOrig)
  if (!startNode || !endNode) return null
  const range = document.createRange()
  range.setStart(startNode.node, Math.min(startOrig - startNode.start, startNode.node.length))
  range.setEnd(endNode.node, Math.min(endOrig - endNode.start, endNode.node.length))
  return range
}

/** 对话提问后:翻到命中页,把引文定位成高亮框 */
async function showPassages(items: { page: number; quote: string }[]): Promise<void> {
  hits.value = []
  textHits.value = []
  const usable = items.filter((i) => i.quote && i.page > 0)
  if (!usable.length) return
  const first = usable[0]
  if (scrollPdf.value) {
    page.value = first.page
    scrollToPage(first.page)
    await nextTick()
    let firstRect: DOMRect | null = null
    for (const item of usable.slice(0, 4)) {
      await renderScrollPage(item.page)
      const layer = textLayerEls.get(item.page)
      const wrap = pageEls.get(item.page)
      if (!layer || !wrap) continue
      const range = findQuoteRange(layer, item.quote)
      if (!range) continue
      const base = wrap.getBoundingClientRect()
      if (!base.width || !base.height) continue
      const rects: number[][] = []
      for (const rect of Array.from(range.getClientRects()).slice(0, 40)) {
        if (!rect.width || !rect.height) continue
        rects.push([
          Math.max(0, (rect.left - base.left) / base.width),
          Math.max(0, (rect.top - base.top) / base.height),
          Math.min(1, rect.width / base.width),
          Math.min(1, rect.height / base.height),
        ].map((n) => Number(n.toFixed(5))))
      }
      if (!rects.length) continue
      hits.value.push({ page: item.page, rects })
      if (!firstRect) firstRect = range.getBoundingClientRect()
    }
    await nextTick()
    if (firstRect && bodyEl.value) {
      const box = bodyEl.value.getBoundingClientRect()
      if (firstRect.top < box.top || firstRect.bottom > box.bottom) {
        bodyEl.value.scrollTop += firstRect.top - box.top - 80
      }
    }
    return
  }
  if (first.page !== page.value) {
    page.value = first.page
    await (props.kind === 'pdf' ? renderPdfPage() : loadTextPage())
  }
  await nextTick()
  if (props.kind !== 'pdf') {
    const raw = displayText.value
    for (const item of usable.slice(0, 4)) {
      const span = findTextSpan(raw, item.quote)
      if (!span) continue
      textHits.value.push(span)
    }
    await nextTick()
    document.querySelector('.v-hit-text')?.scrollIntoView({ block: 'center' })
    return
  }
  const layer = textLayerEl.value
  const wrap = layer?.parentElement
  if (!layer || !wrap) return
  const base = wrap.getBoundingClientRect()
  if (!base.width || !base.height) return
  let firstRect: DOMRect | null = null
  for (const item of usable.slice(0, 4)) {
    if (item.page !== page.value) continue
    const range = findQuoteRange(layer, item.quote)
    if (!range) continue
    const rects: number[][] = []
    for (const rect of Array.from(range.getClientRects()).slice(0, 40)) {
      if (!rect.width || !rect.height) continue
      rects.push([
        Math.max(0, (rect.left - base.left) / base.width),
        Math.max(0, (rect.top - base.top) / base.height),
        Math.min(1, rect.width / base.width),
        Math.min(1, rect.height / base.height),
      ].map((n) => Number(n.toFixed(5))))
    }
    if (!rects.length) continue
    hits.value.push({ page: item.page, rects })
    if (!firstRect) firstRect = range.getBoundingClientRect()
  }
  await nextTick()
  if (firstRect && bodyEl.value) {
    const box = bodyEl.value.getBoundingClientRect()
    if (firstRect.top < box.top || firstRect.bottom > box.bottom) {
      bodyEl.value.scrollTop += firstRect.top - box.top - 80
    }
  }
}

async function flushPending(): Promise<boolean> {
  if (!dirty.value) return true
  return flush()
}

function hasPending(): boolean {
  return dirty.value
}

defineExpose({ showPassages, requestClose, flushPending, hasPending })

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function findTextSpan(raw: string, quote: string): { start: number; end: number } | null {
  let norm = ''
  const back: number[] = []
  let lastSpace = false
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i]
    if (/\s/.test(ch)) {
      if (lastSpace) continue
      norm += ' '
      back.push(i)
      lastSpace = true
    } else {
      norm += ch.toLowerCase()
      back.push(i)
      lastSpace = false
    }
  }
  const target = quote.replace(/\s+/g, ' ').trim().toLowerCase()
  let length = target.length
  let index = norm.indexOf(target)
  if (index < 0 && target.length > 60) {
    length = 60
    index = norm.indexOf(target.slice(0, length))
  }
  if (index < 0) {
    const words = (quote.match(/[\p{L}\p{N}]{4,}/gu) || []).sort(
      (a, b) => b.length - a.length)
    const word = (words[0] || '').toLowerCase()
    if (!word) return null
    index = norm.indexOf(word)
    length = word.length
  }
  if (index < 0) return null
  return {
    start: back[index],
    end: back[Math.min(back.length - 1, index + length - 1)] + 1,
  }
}

/** 文本阅读器:批注与提问命中都按引文位置包成 mark;全部转义后再拼 HTML */
const textHtml = computed(() => {
  const raw = displayText.value
  const marks: { start: number; end: number; cls: string; title: string }[] = []
  for (const a of pageAnnotations.value) {
    if (!a.quote) continue
    const index = raw.indexOf(a.quote)
    if (index < 0) continue
    marks.push({ start: index, end: index + a.quote.length, cls: `v-mark c-${a.color || 'yellow'}`, title: a.note })
  }
  for (const hit of textHits.value) {
    marks.push({ start: hit.start, end: hit.end, cls: 'v-hit-text', title: '' })
  }
  marks.sort((a, b) => a.start - b.start)
  let cursor = 0
  const parts: string[] = []
  for (const mark of marks) {
    if (mark.start < cursor) continue
    parts.push(escapeHtml(raw.slice(cursor, mark.start)))
    parts.push(
      `<mark class="${mark.cls}" title="${escapeHtml(mark.title)}">` +
      `${escapeHtml(raw.slice(mark.start, mark.end))}</mark>`)
    cursor = mark.end
  }
  parts.push(escapeHtml(raw.slice(cursor)))
  return parts.join('')
})

function rectStyle(rect: number[]): Record<string, string> {
  return {
    left: `${rect[0] * 100}%`,
    top: `${rect[1] * 100}%`,
    width: `${rect[2] * 100}%`,
    height: `${rect[3] * 100}%`,
  }
}

function clearSelection(): void {
  selection.value = null
  noteText.value = ''
}

function onMouseUp(e: MouseEvent, pageNumber?: number): void {
  if (regionMode.value || region.value) return
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) return
  const quote = sel.toString().trim()
  if (!quote) return
  const container = (e.currentTarget as HTMLElement) || null
  if (!container) return
  const range = sel.getRangeAt(0)
  if (!container.contains(range.commonAncestorContainer)) return
  const base = container.getBoundingClientRect()
  if (!base.width || !base.height) return
  const rects: number[][] = []
  for (const rect of Array.from(range.getClientRects()).slice(0, 80)) {
    if (!rect.width || !rect.height) continue
    rects.push([
      Math.max(0, Math.min(1, (rect.left - base.left) / base.width)),
      Math.max(0, Math.min(1, (rect.top - base.top) / base.height)),
      Math.max(0, Math.min(1, rect.width / base.width)),
      Math.max(0, Math.min(1, rect.height / base.height)),
    ].map((n) => Number(n.toFixed(5))))
  }
  const targetPage = pageNumber ?? page.value
  page.value = targetPage
  selection.value = {
    quote: quote.slice(0, 2000),
    rects,
    page: targetPage,
    x: Math.min(e.clientX, window.innerWidth - 300),
    y: Math.min(e.clientY + 12, window.innerHeight - 190),
  }
  noteText.value = ''
}

function addAnnotation(): void {
  if (!selection.value) return
  const tempId = `local-${Date.now()}-${annotations.value.length}`
  const input: AnnotationInput = {
    page: selection.value.page,
    quote: selection.value.quote,
    rects: selection.value.rects,
    note: noteText.value.trim(),
    color: 'yellow',
  }
  annotations.value.push({
    id: tempId, docId: props.docId, page: input.page, quote: input.quote,
    rects: input.rects, note: input.note || '', color: 'yellow',
  })
  pendingOps.value.push({ kind: 'save', tempId, input })
  clearSelection()
  window.getSelection()?.removeAllRanges()
}

function removeAnnotation(id: string): void {
  annotations.value = annotations.value.filter((a) => a.id !== id)
  if (editing.value?.id === id) editing.value = null
  if (id.startsWith('local-')) {
    pendingOps.value = pendingOps.value.filter(
      (op) => !(op.kind === 'save' && op.tempId === id))
  } else {
    pendingOps.value.push({ kind: 'delete', id })
  }
}

function beginEdit(item: Annotation): void {
  editing.value = item
  editNote.value = item.note
  editColor.value = item.color || 'yellow'
  selection.value = null
}

function saveEdit(): void {
  const item = editing.value
  if (!item) return
  const note = editNote.value.trim().slice(0, 4000)
  const color = editColor.value
  item.note = note
  item.color = color
  if (item.id.startsWith('local-')) {
    const op = pendingOps.value.find(
      (entry) => entry.kind === 'save' && entry.tempId === item.id)
    if (op && op.kind === 'save') {
      op.input = { ...op.input, note, color }
    }
  } else {
    pendingOps.value.push({
      kind: 'save', tempId: item.id,
      input: {
        id: item.id, page: item.page, quote: item.quote,
        rects: item.rects, note, color,
      },
    })
  }
  editing.value = null
}

async function flush(): Promise<boolean> {
  saving.value = true
  try {
    const ops = [...pendingOps.value]
    for (const op of ops) {
      if (op.kind === 'save') {
        await saveAnnotation(props.docId, op.input)
      } else {
        await deleteAnnotation(props.docId, op.id)
      }
    }
    pendingOps.value = []
    return true
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('viewer.saveFail'))
    return false
  } finally {
    saving.value = false
  }
}

function requestClose(): void {
  if (dirty.value) {
    confirmClose.value = true
    return
  }
  emit('close')
}

async function confirmSaveClose(): Promise<void> {
  if (saving.value) return
  if (await flush()) emit('close')
}

function discardClose(): void {
  pendingOps.value = []
  annotations.value = []
  emit('close')
}

async function loadAnnotations(): Promise<void> {
  try {
    annotations.value = await listAnnotations(props.docId)
  } catch {
    annotations.value = []
  }
  pendingOps.value = []
}

function annotationsFor(pageNumber: number): Annotation[] {
  return annotations.value.filter((a) => a.page === pageNumber)
}

function hitsFor(pageNumber: number): { page: number; rects: number[][] }[] {
  return hits.value.filter((h) => h.page === pageNumber)
}

function setPageEl(pageNumber: number, el: unknown): void {
  if (el instanceof HTMLElement) pageEls.set(pageNumber, el)
  else pageEls.delete(pageNumber)
}

function setCanvasEl(pageNumber: number, el: unknown): void {
  if (el instanceof HTMLCanvasElement) canvasEls.set(pageNumber, el)
  else canvasEls.delete(pageNumber)
}

function setTextLayerEl(pageNumber: number, el: unknown): void {
  if (el instanceof HTMLDivElement) textLayerEls.set(pageNumber, el)
  else textLayerEls.delete(pageNumber)
}

/* ---------- PDF ---------- */
let pdfDoc: any = null
let pdfjs: any = null
let renderTask: any = null
let loadSeq = 0

/* 连续阅读模式的页面 DOM 与懒渲染状态 */
const pageEls = new Map<number, HTMLElement>()
const canvasEls = new Map<number, HTMLCanvasElement>()
const textLayerEls = new Map<number, HTMLDivElement>()
const renderedPages = new Set<number>()
const renderTasks = new Map<number, any>()
let pageObserver: IntersectionObserver | null = null
const regionPage = ref(1)

function fail(message: string): void {
  error.value = message
  loading.value = false
}

async function renderPdfPage(): Promise<void> {
  if (!pdfDoc || !canvasEl.value) return
  loading.value = true
  error.value = ''
  try {
    if (renderTask) {
      renderTask.cancel()
      renderTask = null
    }
    const pdfPage = await pdfDoc.getPage(page.value)
    const base = pdfPage.getViewport({ scale: 1 })
    if (autoFit.value) {
      const width = (bodyEl.value?.clientWidth ?? 0) - 28
      if (width > 0) {
        scale.value = Number(
          Math.min(2, Math.max(0.4, width / base.width)).toFixed(3))
      }
    }
    const viewport = pdfPage.getViewport({ scale: scale.value })
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const canvas = canvasEl.value
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    const context = canvas.getContext('2d')
    if (!context) throw new Error('canvas unavailable')
    renderTask = pdfPage.render({
      canvasContext: context,
      viewport,
      transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
    })
    await renderTask.promise
    renderTask = null
    await nextTick()
    const layer = textLayerEl.value
    if (layer && pdfjs) {
      layer.replaceChildren()
      layer.style.setProperty('--scale-factor', String(scale.value))
      layer.style.width = `${viewport.width}px`
      layer.style.height = `${viewport.height}px`
      const content = await pdfPage.getTextContent()
      const textLayer = new pdfjs.TextLayer({
        textContentSource: content,
        container: layer,
        viewport,
      })
      await textLayer.render()
    }
    loading.value = false
  } catch (err) {
    if ((err as { name?: string })?.name === 'RenderingCancelledException') return
    fail(err instanceof Error ? err.message : t('viewer.loadFail'))
  }
}

async function renderScrollPage(pageNumber: number): Promise<void> {
  if (!pdfDoc || renderedPages.has(pageNumber)) return
  const pending = renderTasks.get(pageNumber)
  if (pending) {
    try {
      await pending.promise
    } catch {
      /* 已取消或失败 */
    }
    return
  }
  const canvas = canvasEls.get(pageNumber)
  const layer = textLayerEls.get(pageNumber)
  if (!canvas) return
  try {
    const pdfPage = await pdfDoc.getPage(pageNumber)
    const base = pdfPage.getViewport({ scale: 1 })
    if (autoFit.value) {
      const width = (bodyEl.value?.clientWidth ?? 0) - 28
      if (width > 0) {
        scale.value = Number(
          Math.min(2, Math.max(0.4, width / base.width)).toFixed(3))
      }
    }
    const viewport = pdfPage.getViewport({ scale: scale.value })
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.floor(viewport.width * dpr)
    canvas.height = Math.floor(viewport.height * dpr)
    canvas.style.width = `${viewport.width}px`
    canvas.style.height = `${viewport.height}px`
    const context = canvas.getContext('2d')
    if (!context) throw new Error('canvas unavailable')
    const task = pdfPage.render({
      canvasContext: context,
      viewport,
      transform: dpr === 1 ? undefined : [dpr, 0, 0, dpr, 0, 0],
    })
    renderTasks.set(pageNumber, task)
    await task.promise
    renderedPages.add(pageNumber)
    if (layer && pdfjs) {
      layer.replaceChildren()
      layer.style.setProperty('--scale-factor', String(scale.value))
      layer.style.width = `${viewport.width}px`
      layer.style.height = `${viewport.height}px`
      const content = await pdfPage.getTextContent()
      const textLayer = new pdfjs.TextLayer({
        textContentSource: content,
        container: layer,
        viewport,
      })
      await textLayer.render()
    }
  } catch (err) {
    if ((err as { name?: string })?.name !== 'RenderingCancelledException') {
      console.warn('[viewer] page render failed', pageNumber, err)
    }
  } finally {
    renderTasks.delete(pageNumber)
  }
}

function resetScrollPages(): void {
  pageObserver?.disconnect()
  pageObserver = null
  for (const task of renderTasks.values()) {
    try {
      task.cancel()
    } catch {
      /* 已结束 */
    }
  }
  renderTasks.clear()
  renderedPages.clear()
}

function clearScrollDom(): void {
  resetScrollPages()
  pageEls.clear()
  canvasEls.clear()
  textLayerEls.clear()
}

async function setupScrollPages(): Promise<void> {
  await nextTick()
  pageObserver?.disconnect()
  if (typeof IntersectionObserver === 'undefined') {
    for (let n = 1; n <= total.value; n += 1) void renderScrollPage(n)
    return
  }
  pageObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      const n = Number((entry.target as HTMLElement).dataset.page || 0)
      if (n > 0) void renderScrollPage(n)
    }
  }, { root: bodyEl.value, rootMargin: '900px 0px' })
  for (const [n, el] of pageEls) {
    el.dataset.page = String(n)
    pageObserver.observe(el)
  }
  const start = Math.max(1, page.value)
  for (let n = start; n <= Math.min(total.value, start + 2); n += 1) {
    void renderScrollPage(n)
  }
}

async function rerenderScrollPages(): Promise<void> {
  resetScrollPages()
  await nextTick()
  await setupScrollPages()
}

function scrollToPage(pageNumber: number): void {
  const el = pageEls.get(pageNumber)
  if (el) el.scrollIntoView({ block: 'start' })
}

function onScroll(): void {
  if (!scrollPdf.value) return
  const body = bodyEl.value
  if (!body) return
  const top = body.getBoundingClientRect().top + 12
  let current = page.value
  for (const [n, el] of pageEls) {
    if (el.getBoundingClientRect().bottom > top) {
      current = n
      break
    }
  }
  if (current !== page.value) page.value = current
}

async function loadPdf(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    pdfjs = await import('pdfjs-dist')
    const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default
    pdfDoc = await pdfjs.getDocument({
      url: fileUrl.value,
      httpHeaders: authHeaders(),
      withCredentials: true,
    }).promise
    if (seq !== loadSeq) return
    total.value = pdfDoc.numPages
    page.value = Math.min(Math.max(1, page.value), total.value)
    if (scrollPdf.value) {
      await nextTick()
      await setupScrollPages()
      loading.value = false
    } else {
      await renderPdfPage()
    }
  } catch (err) {
    fail(err instanceof Error ? err.message : t('viewer.loadFail'))
  }
}

async function loadTextPage(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`${textUrl.value}?page=${page.value}`, {
      headers: authHeaders(),
      credentials: 'include',
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json() as { text: string; total: number; page: number }
    if (seq !== loadSeq) return
    textBody.value = data.text || ''
    total.value = data.total || 1
    page.value = data.page || 1
    loading.value = false
  } catch (err) {
    fail(err instanceof Error ? err.message : t('viewer.loadFail'))
  }
}

async function load(): Promise<void> {
  await loadAnnotations()
  if (props.kind === 'pdf') await loadPdf()
  else await loadTextPage()
}

function go(delta: number): void {
  const next = page.value + delta
  if (next < 1 || (total.value && next > total.value)) return
  page.value = next
  clearSelection()
  textHits.value = []
  if (scrollPdf.value) {
    scrollToPage(next)
    return
  }
  void (props.kind === 'pdf' ? renderPdfPage() : loadTextPage())
}

function jump(): void {
  if (total.value) page.value = Math.min(Math.max(1, page.value), total.value)
  clearSelection()
  textHits.value = []
  if (scrollPdf.value) {
    scrollToPage(page.value)
    return
  }
  void (props.kind === 'pdf' ? renderPdfPage() : loadTextPage())
}

function zoom(delta: number): void {
  autoFit.value = false
  scale.value = Math.min(3, Math.max(0.5, Number((scale.value + delta).toFixed(2))))
  if (scrollPdf.value) {
    void rerenderScrollPages()
    return
  }
  if (props.kind === 'pdf') void renderPdfPage()
}

async function toggleExpand(): Promise<void> {
  expanded.value = !expanded.value
  if (props.kind !== 'pdf') return
  autoFit.value = true
  await nextTick()
  if (scrollPdf.value) {
    await rerenderScrollPages()
    return
  }
  setTimeout(() => { void renderPdfPage() }, 60)
}

function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    if (selection.value) {
      clearSelection()
      return
    }
    if (confirmClose.value) {
      confirmClose.value = false
      return
    }
    requestClose()
  }
  if (props.kind !== 'pdf') {
    if (e.key === 'ArrowLeft') go(-1)
    if (e.key === 'ArrowRight') go(1)
  }
}

window.addEventListener('keydown', onKey)

watch(() => [props.docId, props.kind], () => {
  clearScrollDom()
  page.value = props.startPage && props.startPage > 0 ? props.startPage : 1
  textBody.value = ''
  total.value = 0
  clearSelection()
  void load()
})

watch(() => props.docId, () => void loadDocMeta())

void load()

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  loadSeq += 1
  clearScrollDom()
  try {
    if (renderTask) renderTask.cancel()
  } catch {
    /* 渲染已结束 */
  }
  try {
    if (pdfDoc && typeof pdfDoc.destroy === 'function') void pdfDoc.destroy()
  } catch {
    /* 文档已销毁 */
  }
})
</script>

<template>
  <div class="viewer" :class="{ expanded }">
    <header class="v-head">
      <span class="v-title" :title="title">{{ title }}</span>
      <span class="v-spacer"></span>
      <template v-if="!scrollPdf">
        <button class="v-btn" :title="t('viewer.prev')" @click="go(-1)">‹</button>
        <input
          v-model.number="page"
          class="v-page"
          inputmode="numeric"
          @keydown.enter="jump"
          @blur="jump"
        />
        <span class="v-total">/ {{ total || '…' }}</span>
        <button class="v-btn" :title="t('viewer.next')" @click="go(1)">›</button>
      </template>
      <span v-else class="v-total">{{ page }} / {{ total || '…' }}</span>
      <template v-if="kind === 'pdf'">
        <button class="v-btn" :title="t('viewer.region')" :class="{ on: regionMode }" @click="toggleRegion">▣</button>
        <button class="v-btn" :title="t('viewer.zoomOut')" @click="zoom(-0.15)">−</button>
        <button class="v-btn" :title="t('viewer.zoomIn')" @click="zoom(0.15)">＋</button>
      </template>
      <button
        class="v-btn notes-btn"
        :class="{ on: notesOpen }"
        :title="t('viewer.notes')"
        @click="notesOpen = !notesOpen"
      >✎ {{ annotations.length }}</button>
      <button class="v-btn" :title="t('viewer.expand')" @click="toggleExpand">
        {{ expanded ? '⤡' : '⤢' }}
      </button>
      <button class="v-close" :title="t('viewer.close')" @click="requestClose">✕</button>
    </header>

    <div v-if="hasMeta && docMeta" class="v-meta">
      <span v-if="docMeta.venue" class="v-meta-venue" :title="docMeta.venue">
        {{ docMeta.venue }}
      </span>
      <span v-if="docMeta.peerReviewed" class="v-meta-chip ok">
        {{ t('viewer.peerReviewed') }}
      </span>
      <span v-if="docMeta.articleType === 'preprint'" class="v-meta-chip">
        {{ t('viewer.preprint') }}
      </span>
      <span
        v-if="docMeta.oaStatus && docMeta.oaStatus !== 'unknown' && docMeta.oaStatus !== 'closed'"
        class="v-meta-chip oa"
      >
        {{ t('viewer.freeFullText') }} · {{ docMeta.oaStatus }}
      </span>
      <span v-if="docMeta.license" class="v-meta-chip">
        {{ t('viewer.licenseLabel') }}: {{ docMeta.license }}
      </span>
      <span v-if="docMeta.retractionStatus === 'retracted'" class="v-meta-chip warn">
        {{ t('viewer.retracted') }}
      </span>
      <a
        v-if="docMeta.landingUrl"
        class="v-meta-link"
        :href="docMeta.landingUrl"
        target="_blank"
        rel="noopener noreferrer"
      >{{ t('viewer.publisherPage') }}</a>
    </div>

    <div ref="bodyEl" class="v-body" @scroll="onScroll">
      <p v-if="error" class="v-error">{{ error }}</p>
      <p v-else-if="loading && !textBody && kind === 'text'" class="v-loading">
        {{ t('viewer.loading') }}
      </p>
      <template v-if="scrollPdf">
        <div class="v-scroll">
          <div
            v-for="n in total"
            :key="n"
            :ref="(el) => setPageEl(n, el)"
            class="v-page-wrap v-page-block"
            @mouseup="onMouseUp($event, n)"
            @mousedown="onRegionDown($event, n)"
          >
            <canvas :ref="(el) => setCanvasEl(n, el)" class="v-canvas"></canvas>
            <div :ref="(el) => setTextLayerEl(n, el)" class="v-text-layer"></div>
            <div class="v-annot-layer">
              <template v-for="a in annotationsFor(n)" :key="a.id">
                <span
                  v-for="(rect, ri) in a.rects"
                  :key="`${a.id}-${ri}`"
                  class="v-annot-rect"
                  :class="`c-${a.color || 'yellow'}`"
                  :title="a.note || a.quote"
                  :style="rectStyle(rect)"
                  @click.stop="beginEdit(a)"
                ></span>
              </template>
            </div>
            <div class="v-hit-layer">
              <template v-for="(hit, hi) in hitsFor(n)" :key="`hit-${n}-${hi}`">
                <span
                  v-for="(rect, ri) in hit.rects"
                  :key="`hit-${n}-${hi}-${ri}`"
                  class="v-hit-rect"
                  :style="rectStyle(rect)"
                ></span>
              </template>
            </div>
            <div
              v-if="region && regionPage === n"
              class="v-region"
              :style="{ left: `${region.x}px`, top: `${region.y}px`, width: `${region.w}px`, height: `${region.h}px` }"
            ></div>
          </div>
        </div>
      </template>
      <template v-else-if="kind === 'pdf'">
        <div
          class="v-page-wrap"
          @mouseup="onMouseUp($event)"
          @mousedown="onRegionDown"
        >
          <canvas ref="canvasEl" class="v-canvas"></canvas>
          <div ref="textLayerEl" class="v-text-layer"></div>
          <div class="v-annot-layer">
            <template v-for="a in pageAnnotations" :key="a.id">
              <span
                v-for="(rect, ri) in a.rects"
                :key="`${a.id}-${ri}`"
                class="v-annot-rect"
                :class="`c-${a.color || 'yellow'}`"
                :title="a.note || a.quote"
                :style="rectStyle(rect)"
                @click.stop="beginEdit(a)"
              ></span>
            </template>
          </div>
          <div class="v-hit-layer">
            <template v-for="(hit, hi) in pageHits" :key="`hit-${hi}`">
              <span
                v-for="(rect, ri) in hit.rects"
                :key="`hit-${hi}-${ri}`"
                class="v-hit-rect"
                :style="rectStyle(rect)"
              ></span>
            </template>
          </div>
          <div
            v-if="region"
            class="v-region"
            :style="{ left: `${region.x}px`, top: `${region.y}px`, width: `${region.w}px`, height: `${region.h}px` }"
          ></div>
        </div>
      </template>
      <template v-else>
        <article
          v-if="displayText"
          class="v-text"
          @mouseup="onMouseUp"
          v-html="textHtml"
        ></article>
      </template>
    </div>

    <div v-if="regionShot" class="v-pop v-region-pop">
      <p class="v-quote">{{ t('viewer.regionHint') }}</p>
      <textarea
        v-model="regionQuestion"
        class="v-note-input"
        :placeholder="t('viewer.regionQuestion')"
      ></textarea>
      <div class="v-pop-actions">
        <button class="v-primary" :disabled="regionLoading || tableLoading" @click="askRegion">
          {{ regionLoading ? t('viewer.loading') : t('viewer.regionAsk') }}
        </button>
        <button class="v-btn" :disabled="regionLoading || tableLoading" @click="extractRegionTable">
          {{ tableLoading ? t('viewer.extracting') : t('viewer.extractTable') }}
        </button>
        <button class="v-btn" @click="regionShot = null">{{ t('viewer.cancel') }}</button>
      </div>
    </div>

    <TableExtractDialog
      v-if="tablePreview"
      :preview="tablePreview.preview"
      :doc-id="tablePreview.docId"
      :doc-name="tablePreview.docName"
      :page="tablePreview.page"
      :project-id="projectId"
      @close="tablePreview = null"
      @saved="tablePreview = null"
    />

    <aside v-if="regionAnswer" class="v-region-answer">
      <div class="v-region-head">
        <span>{{ t('viewer.regionAnswer') }}</span>
        <button class="v-del" @click="regionAnswer = ''">✕</button>
      </div>
      <p>{{ regionAnswer }}</p>
    </aside>

    <div v-if="selection" class="v-pop" :style="{ left: `${selection.x}px`, top: `${selection.y}px` }">
      <p class="v-quote">{{ selection.quote.slice(0, 90) }}</p>
      <textarea
        v-model="noteText"
        class="v-note-input"
        :placeholder="t('viewer.notePlaceholder')"
      ></textarea>
      <div class="v-pop-actions">
        <button class="v-primary" @click="addAnnotation">{{ t('viewer.addNote') }}</button>
        <button class="v-btn" @click="clearSelection">{{ t('viewer.cancel') }}</button>
      </div>
    </div>

    <aside v-if="notesOpen" class="v-notes">
      <p class="v-notes-title">{{ t('viewer.notes') }} · {{ annotations.length }}</p>
      <p v-if="!annotations.length" class="v-loading">{{ t('viewer.noNotes') }}</p>
      <div v-for="a in annotations" :key="a.id" class="v-note-item">
        <div class="v-note-head">
          <span class="v-note-page">{{ t('viewer.pageNo', { n: a.page }) }}</span>
          <button class="v-note-edit" @click="beginEdit(a)">{{ t('viewer.editNote') }}</button>
          <button class="v-del" @click="removeAnnotation(a.id)">✕</button>
        </div>
        <p v-if="a.quote" class="v-note-quote">{{ a.quote }}</p>
        <p v-if="a.note" class="v-note-text">{{ a.note }}</p>
      </div>
    </aside>

    <div v-if="editing" class="v-pop v-edit">
      <p class="v-quote">{{ editing.quote.slice(0, 90) }}</p>
      <textarea v-model="editNote" class="v-note-input" :placeholder="t('viewer.notePlaceholder')"></textarea>
      <div class="v-colors">
        <button
          v-for="color in ANNOT_COLORS"
          :key="color"
          class="v-color"
          :class="[`c-${color}`, { on: editColor === color }]"
          :title="color"
          @click="editColor = color"
        ></button>
      </div>
      <div class="v-pop-actions">
        <button class="v-primary" @click="saveEdit">{{ t('viewer.saveNote') }}</button>
        <button class="v-btn" @click="removeAnnotation(editing.id)">{{ t('viewer.deleteNote') }}</button>
        <button class="v-btn" @click="editing = null">{{ t('viewer.cancel') }}</button>
      </div>
    </div>

    <div v-if="confirmClose" class="v-confirm">
      <div class="v-confirm-box">
        <p class="v-confirm-title">{{ t('viewer.unsavedTitle') }}</p>
        <p class="v-confirm-text">{{ t('viewer.unsavedHint') }}</p>
        <div class="v-confirm-actions">
          <button class="v-primary" :disabled="saving" @click="confirmSaveClose">
            {{ saving ? t('viewer.saving') : t('viewer.saveClose') }}
          </button>
          <button class="v-btn" :disabled="saving" @click="discardClose">
            {{ t('viewer.discardClose') }}
          </button>
          <button class="v-btn" :disabled="saving" @click="confirmClose = false">
            {{ t('viewer.cancel') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.viewer {
  position: absolute;
  inset: 0;
  z-index: 40;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-left: 1px solid var(--line);
}

.viewer.expanded {
  position: fixed;
  inset: 64px 24px 24px auto;
  width: min(1080px, 72vw);
  z-index: 1200;
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
  overflow: hidden;
}

.v-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  flex: none;
}

.v-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding: 5px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-card);
  color: var(--text-dim);
  font-size: 11px;
  flex: none;
}

.v-meta-venue {
  max-width: 42%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-hi);
}

.v-meta-chip {
  padding: 1px 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
  white-space: nowrap;
}

.v-meta-chip.ok {
  color: var(--green, #3fb950);
  border-color: color-mix(in srgb, var(--green, #3fb950) 45%, transparent);
}

.v-meta-chip.oa {
  color: var(--cyan);
  border-color: color-mix(in srgb, var(--cyan) 45%, transparent);
}

.v-meta-chip.warn {
  color: var(--red, #f85149);
  border-color: color-mix(in srgb, var(--red, #f85149) 55%, transparent);
}

.v-meta-link {
  margin-left: auto;
  color: var(--cyan);
  text-decoration: none;
  white-space: nowrap;
}

.v-meta-link:hover {
  text-decoration: underline;
}

.v-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-hi);
  font-size: 12px;
}

.v-spacer {
  flex: 1;
}

.v-btn,
.v-close {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 5px;
  min-width: 24px;
  height: 24px;
  padding: 0 5px;
  cursor: pointer;
  font-size: 12px;
}

.v-btn:hover,
.v-close:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.v-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.v-close:hover {
  color: #ff8a8a;
}

.v-page {
  width: 44px;
  height: 24px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text);
  text-align: center;
  font-size: 11.5px;
}

.v-total {
  color: var(--text-dim);
  font-size: 11px;
}

.v-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 14px;
  display: flex;
  justify-content: flex-start;
  align-items: flex-start;
}

.v-scroll {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.v-page-block {
  margin: 0;
  flex: none;
}

.v-page-wrap {
  position: relative;
  flex: none;
  margin: 0 auto;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.35);
}

.v-canvas {
  display: block;
  background: #fff;
}

.v-text-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  line-height: 1;
  opacity: 1;
}

.v-text-layer :deep(span) {
  position: absolute;
  color: transparent;
  white-space: pre;
  transform-origin: 0 0;
  cursor: text;
}

.v-text-layer :deep(span::selection) {
  background: color-mix(in srgb, var(--cyan) 35%, transparent);
}

.v-annot-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.v-annot-rect {
  position: absolute;
  background: color-mix(in srgb, #ffd166 26%, transparent);
  border: 1px solid color-mix(in srgb, #ffd166 65%, transparent);
  border-radius: 2px;
  pointer-events: auto;
  cursor: pointer;
}

.v-annot-rect.c-cyan {
  background: color-mix(in srgb, #4cc9f0 24%, transparent);
  border-color: color-mix(in srgb, #4cc9f0 70%, transparent);
}

.v-annot-rect.c-green {
  background: color-mix(in srgb, #6ee7a8 24%, transparent);
  border-color: color-mix(in srgb, #6ee7a8 70%, transparent);
}

.v-annot-rect.c-red {
  background: color-mix(in srgb, #ff8a8a 24%, transparent);
  border-color: color-mix(in srgb, #ff8a8a 70%, transparent);
}

.v-hit-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.v-hit-rect {
  position: absolute;
  background: color-mix(in srgb, var(--cyan) 20%, transparent);
  border: 1px solid color-mix(in srgb, var(--cyan) 70%, transparent);
  border-radius: 2px;
}

.v-region {
  position: absolute;
  border: 1.5px dashed color-mix(in srgb, var(--cyan) 85%, transparent);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
  pointer-events: none;
}

.v-region-pop {
  left: auto;
  right: 16px;
  top: 70px;
  width: 300px;
  z-index: 1350;
}

.v-region-answer {
  position: fixed;
  right: 16px;
  bottom: 16px;
  width: min(360px, calc(100% - 32px));
  max-height: 46vh;
  overflow-y: auto;
  background: var(--bg-card);
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  padding: 10px 12px;
  z-index: 1350;
  box-shadow: 0 10px 36px rgba(0, 0, 0, 0.5);
}

.v-region-head {
  display: flex;
  justify-content: space-between;
  color: var(--cyan);
  font-size: 11px;
  margin-bottom: 6px;
}

.v-region-answer p {
  color: var(--text);
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.v-text {
  width: 100%;
  max-width: 760px;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
  font-size: 13px;
  line-height: 1.75;
}

.v-text :deep(.v-mark) {
  background: color-mix(in srgb, #ffd166 30%, transparent);
  color: var(--text-hi);
  border-radius: 2px;
}

.v-text :deep(.v-hit-text) {
  background: color-mix(in srgb, var(--cyan) 24%, transparent);
  color: var(--text-hi);
  border-radius: 2px;
}

.v-error {
  color: #ff8a8a;
  font-size: 12px;
}

.v-loading {
  color: var(--text-dim);
  font-size: 12px;
}

.v-pop {
  position: fixed;
  z-index: 1300;
  width: 280px;
  padding: 10px;
  background: var(--bg-card);
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  box-shadow: 0 10px 36px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.v-quote {
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.4;
  max-height: 44px;
  overflow: hidden;
}

.v-note-input {
  min-height: 58px;
  resize: vertical;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  padding: 6px 8px;
  font-size: 12px;
}

.v-pop-actions,
.v-confirm-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}

.v-primary {
  background: color-mix(in srgb, var(--cyan) 16%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 5px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 11.5px;
}

.v-notes {
  position: absolute;
  top: 42px;
  right: 0;
  bottom: 0;
  width: 260px;
  background: color-mix(in srgb, var(--bg-card) 96%, transparent);
  border-left: 1px solid var(--line);
  padding: 10px;
  overflow-y: auto;
  z-index: 45;
}

.v-notes-title {
  color: var(--cyan);
  font-size: 11px;
  margin-bottom: 8px;
}

.v-note-item {
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 7px 8px;
  margin-bottom: 8px;
}

.v-note-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--text-dim);
  font-size: 10.5px;
}

.v-del {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10px;
}

.v-del:hover {
  color: #ff8a8a;
}

.v-note-quote {
  color: var(--text);
  font-size: 11px;
  margin-top: 4px;
  line-height: 1.4;
}

.v-note-text {
  color: var(--text-dim);
  font-size: 11px;
  margin-top: 4px;
  line-height: 1.4;
}

.v-note-edit {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10px;
  margin-left: auto;
  margin-right: 6px;
}

.v-note-edit:hover {
  color: var(--cyan);
}

.v-edit {
  left: auto;
  right: 16px;
  top: 70px;
  width: 300px;
  z-index: 1350;
}

.v-colors {
  display: flex;
  gap: 6px;
}

.v-color {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
  background: #ffd166;
}

.v-color.c-cyan {
  background: #4cc9f0;
}

.v-color.c-green {
  background: #6ee7a8;
}

.v-color.c-red {
  background: #ff8a8a;
}

.v-color.on {
  border-color: var(--text-hi);
}

.v-confirm {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1400;
}

.v-confirm-box {
  width: min(340px, calc(100% - 32px));
  background: var(--bg-card);
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  padding: 16px;
}

.v-confirm-title {
  color: var(--text-hi);
  font-size: 13px;
  margin-bottom: 6px;
}

.v-confirm-text {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.5;
  margin-bottom: 12px;
}
</style>
