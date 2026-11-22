<script setup lang="ts">
/**
 * 知识图谱:后端 NetworkX 分层坐标 + 缩放/拖拽 + 点选详情。
 *
 * 坐标优先用 /api/graph 返回的 x/y/level;缺失时退回本地
 * utils/graphLayout 的最长路径分层。节点按掌握度着色:
 * 已掌握 / 薄弱 / 未诊断。章节筛选会把视图聚焦到该章节的节点范围。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Starfield from '@/components/common/Starfield.vue'
import MathText from '@/components/chat/MathText.vue'
import { statusOf } from '@/api/http'
import {
  exportGraphHtml,
  fetchGraph,
  fetchRecommendation,
  submitSelfRating,
  type GraphData,
  type GraphNode,
  type Recommendation,
  type RecommendationItem,
  type RecommendStrategy,
} from '@/services/graphService'
import { resolveLayout } from '@/utils/graphLayout'
import { panBy, pinchMetrics, zoomAround } from '@/utils/graphGesture'
import { t } from '@/utils/i18n'
import { settingsState } from '@/stores/settings'
import { showToast } from '@/utils/toast'
import { downloadBlob } from '@/services/docService'

const router = useRouter()
const route = useRoute()
const data = ref<GraphData | null>(null)
const loading = ref(true)
const error = ref('')
const wrapEl = ref<HTMLElement | null>(null)
const panelsEl = ref<HTMLElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
const selectedId = ref('')
const activeChapter = ref('')
const query = ref('')
const recommendation = ref<Recommendation | null>(null)
const strategy = ref<RecommendStrategy>('difficulty')
const ratingBusy = ref(false)

const view = reactive({ x: 0, y: 0, w: 1200, h: 800 })

const nodes = computed(() => data.value?.nodes ?? [])
const edges = computed(() => data.value?.edges ?? [])
const layout = computed(() => resolveLayout(nodes.value))
const viewBox = computed(() => `${view.x} ${view.y} ${view.w} ${view.h}`)

const nodeById = computed(() => {
  const map = new Map<string, GraphNode>()
  for (const node of nodes.value) map.set(node.id, node)
  return map
})

const dependents = computed(() => {
  const map = new Map<string, string[]>()
  for (const edge of edges.value) {
    const list = map.get(edge.source) ?? []
    list.push(edge.target)
    map.set(edge.source, list)
  }
  return map
})

const selected = computed(() =>
  selectedId.value ? nodeById.value.get(selectedId.value) ?? null : null)
const selectedPrerequisites = computed(() =>
  selected.value ? resolve(selected.value.prerequisites) : [])
const selectedDependents = computed(() =>
  selected.value ? resolve(dependents.value.get(selected.value.id) ?? []) : [])

function displayName(node: { name: string; nameEn?: string }): string {
  return settingsState.language === 'en' ? node.nameEn || node.name : node.name
}

function chapterLabel(chapter: string): string {
  if (settingsState.language !== 'en') return chapter
  return data.value?.chaptersEn?.[chapter] || chapter
}

function summaryText(node: GraphNode): string {
  return settingsState.language === 'en' ? node.summaryEn || node.summary || '' : node.summary || ''
}

function keyPointTexts(node: GraphNode): string[] {
  if (settingsState.language === 'en' && node.keyPointsEn?.length) return node.keyPointsEn
  return node.keyPoints ?? []
}

/* ---------- 节点框自适应 ----------
   英文知识点名比中文长很多,固定 164px 会把名字截成 "Second-Order …"。
   这里按完整名称测量宽度:一行放得下就一行,放不下自动换行,框的高度
   随行数增高;宽度上限 240,避免挤占相邻层级。 */
const NODE_MIN_W = 120
const NODE_MAX_W = 220
const NODE_TEXT_PAD = 40
const NODE_LINE_H = 13
const measureContext = document.createElement('canvas').getContext('2d')
let measureFontSpec = ''

/** 画布测量字体只初始化一次;字体令牌在模块加载后才稳定。 */
function ensureMeasureFont(): void {
  if (measureFontSpec) return
  const font = getComputedStyle(document.documentElement)
    .getPropertyValue('--font-ui').trim()
  measureFontSpec = `12.5px ${font || 'sans-serif'}`
  if (measureContext) measureContext.font = measureFontSpec
}

function measureLabel(text: string): number {
  if (!measureContext) return Array.from(text).length * 7
  ensureMeasureFont()
  return measureContext.measureText(text).width
}

function wrapFullLabel(text: string, maxWidth: number): string[] {
  if (measureLabel(text) <= maxWidth) return [text]
  const words = text.split(/\s+/)
  const lines: string[] = []
  let line = ''
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word
    if (measureLabel(candidate) <= maxWidth) {
      line = candidate
      continue
    }
    if (line) {
      lines.push(line)
      line = ''
    }
    if (measureLabel(word) <= maxWidth) {
      line = word
      continue
    }
    // 单个超长单词/中文长串:按字符切
    let chunk = ''
    for (const char of Array.from(word)) {
      if (measureLabel(chunk + char) <= maxWidth) chunk += char
      else {
        if (chunk) lines.push(chunk)
        chunk = char
      }
    }
    line = chunk
  }
  if (line) lines.push(line)
  return lines.length ? lines : [text]
}

const nodeSizes = computed(() => {
  const map = new Map<string, { w: number; h: number; lines: string[] }>()
  for (const node of nodes.value) {
    const full = displayName(node)
    const natural = measureLabel(full) + NODE_TEXT_PAD
    const width = Math.min(NODE_MAX_W, Math.max(NODE_MIN_W, natural))
    const lines = wrapFullLabel(full, width - NODE_TEXT_PAD)
    const height = Math.max(44, 14 + lines.length * NODE_LINE_H)
    map.set(node.id, { w: width, h: height, lines })
  }
  return map
})

const matches = computed(() => {
  const term = query.value.trim().toLowerCase()
  if (!term) return []
  return nodes.value.filter((node) =>
    node.name.toLowerCase().includes(term)
    || (node.nameEn ?? '').toLowerCase().includes(term)
    || node.id.toLowerCase().includes(term)
    || node.chapter.toLowerCase().includes(term)
    || chapterLabel(node.chapter).toLowerCase().includes(term),
  ).slice(0, 8)
})

/**
 * 画布几何预计算:拖拽/缩放只改 viewBox(view 的 x/y/w/h),
 * 若模板里逐元素调用 pos()/isDim()/label(),每次 pointermove 都要把
 * 全部节点与边重算一遍。放进 computed 后平移缩放只更新一个属性,
 * 几何只在布局或章节筛选变化时重算。
 */
const edgeGeoms = computed(() =>
  edges.value.map((edge, index) => {
    const from = layout.value.positions[edge.source] ?? { x: 0, y: 0, level: 0 }
    const to = layout.value.positions[edge.target] ?? { x: 0, y: 0, level: 0 }
    const source = nodeById.value.get(edge.source)
    const target = nodeById.value.get(edge.target)
    const sourceHalf = (nodeSizes.value.get(edge.source)?.w ?? 164) / 2
    const targetHalf = (nodeSizes.value.get(edge.target)?.w ?? 164) / 2
    return {
      key: `${edge.source}-${edge.target}-${index}`,
      x1: from.x + sourceHalf,
      y1: from.y,
      x2: to.x - targetHalf - 2,
      y2: to.y,
      dim: Boolean(activeChapter.value)
        && (source?.chapter !== activeChapter.value || target?.chapter !== activeChapter.value),
    }
  }),
)

const nodeGeoms = computed(() =>
  nodes.value.map((node) => {
    const point = layout.value.positions[node.id] ?? { x: 0, y: 0, level: 0 }
    const size = nodeSizes.value.get(node.id) ?? { w: 164, h: 44, lines: [displayName(node)] }
    return {
      node,
      x: point.x,
      y: point.y,
      w: size.w,
      h: size.h,
      lines: size.lines,
      dim: Boolean(activeChapter.value) && node.chapter !== activeChapter.value,
    }
  }),
)

function resolve(ids: string[]): GraphNode[] {
  return ids.map((id) => nodeById.value.get(id)).filter((node): node is GraphNode => Boolean(node))
}

function aspectRatio(): number {
  const el = wrapEl.value
  if (!el || !el.clientWidth || !el.clientHeight) return 1.6
  return el.clientWidth / el.clientHeight
}

function resetView() {
  activeChapter.value = ''
  // 按节点实际范围取景:框宽随英文全名变化,旧的 640 固定宽度会裁掉两侧
  fitTo(nodes.value.map((node) => node.id))
}

function fitTo(ids: string[]) {
  const points = ids.map((id) => layout.value.positions[id]).filter(Boolean)
  if (!points.length) return
  const minX = Math.min(...points.map((point) => point.x)) - 160
  const maxX = Math.max(...points.map((point) => point.x)) + 160
  const minY = Math.min(...points.map((point) => point.y)) - 100
  const maxY = Math.max(...points.map((point) => point.y)) + 100
  const aspect = aspectRatio()
  let width = Math.max(760, maxX - minX)
  let height = Math.max(480, maxY - minY)
  if (width / height > aspect) height = width / aspect
  else width = height * aspect
  view.w = width
  view.h = height
  view.x = (minX + maxX) / 2 - width / 2
  view.y = (minY + maxY) / 2 - height / 2
}

function chooseChapter(chapter: string) {
  activeChapter.value = chapter
  if (!chapter) {
    resetView()
    return
  }
  fitTo(nodes.value.filter((node) => node.chapter === chapter).map((node) => node.id))
}

function centerOn(id: string) {
  const point = layout.value.positions[id]
  if (!point) return
  view.x = point.x - view.w / 2
  view.y = point.y - view.h / 2
}

function pick(node: GraphNode) {
  query.value = ''
  selectedId.value = node.id
  centerOn(node.id)
  revealDetail()
}

/** 窄屏的推荐/详情是同一个横向滚动窗口:选中节点后滑到详情页。 */
function revealDetail(): void {
  void nextTick(() => {
    const el = panelsEl.value
    if (!el || el.clientWidth <= 0) return
    el.scrollTo({ left: el.clientWidth, behavior: 'smooth' })
  })
}

function closeDetail(): void {
  const el = panelsEl.value
  if (el && el.clientWidth > 0 && el.scrollLeft > 0) {
    el.scrollTo({ left: 0, behavior: 'smooth' })
  }
  selectedId.value = ''
}

function svgPoint(screen: { x: number; y: number }): DOMPoint {
  const svg = svgEl.value
  if (!svg) return new DOMPoint(screen.x, screen.y)
  const point = svg.createSVGPoint()
  point.x = screen.x
  point.y = screen.y
  const matrix = svg.getScreenCTM()
  return matrix ? point.matrixTransform(matrix.inverse()) : point
}

function viewMaxWidth(): number {
  return Math.max(1200, layout.value.width * 1.6)
}

function onWheel(event: WheelEvent) {
  if (!svgEl.value) return
  const point = svgPoint({ x: event.clientX, y: event.clientY })
  const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15
  zoomAround(view, point, factor, 500, viewMaxWidth())
}

/* 触屏手势:一根手指平移,两根手指围绕中点缩放(同时跟手平移)。
   画布已设 touch-action: none,双指不再放大整个网页。 */
const pointers = new Map<number, DOMPoint>()
let pinch: { distance: number; mid: DOMPoint } | null = null

let drag: { pointerId: number; last: DOMPoint; moved: boolean } | null = null
let suppressClick = false

function readPinch(): { distance: number; mid: DOMPoint } | null {
  const pts = [...pointers.values()]
  if (pts.length < 2) return null
  const { distance, mid } = pinchMetrics(pts[0], pts[1])
  return { distance, mid: new DOMPoint(mid.x, mid.y) }
}

function onDown(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const point = new DOMPoint(event.clientX, event.clientY)
  pointers.set(event.pointerId, point)
  if (pointers.size >= 2) {
    pinch = readPinch()
    drag = null
    suppressClick = true
  } else {
    drag = { pointerId: event.pointerId, last: point, moved: false }
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}

function onMove(event: PointerEvent) {
  if (!pointers.has(event.pointerId)) return
  const point = new DOMPoint(event.clientX, event.clientY)
  pointers.set(event.pointerId, point)

  if (pinch && pointers.size >= 2) {
    const next = readPinch()
    if (!next) return
    const previousMid = svgPoint(pinch.mid)
    const nextMid = svgPoint(next.mid)
    panBy(view, nextMid.x - previousMid.x, nextMid.y - previousMid.y)
    zoomAround(view, previousMid, pinch.distance / (next.distance || 1), 500, viewMaxWidth())
    pinch = next
    suppressClick = true
    return
  }

  if (!drag || drag.pointerId !== event.pointerId) return
  const previousPoint = svgPoint(drag.last)
  const nextPoint = svgPoint(point)
  const dx = nextPoint.x - previousPoint.x
  const dy = nextPoint.y - previousPoint.y
  if (Math.abs(dx) + Math.abs(dy) > 1) drag.moved = true
  panBy(view, dx, dy)
  drag.last = point
}

function onUp(event: PointerEvent) {
  pointers.delete(event.pointerId)

  if (pointers.size >= 2) {
    pinch = readPinch()
    drag = null
    return
  }

  pinch = null
  if (pointers.size === 1) {
    // 松开一指后继续用剩下那根平移;moved=true 防止抬手误触发节点点选
    const [id, last] = [...pointers.entries()][0]
    drag = { pointerId: id, last, moved: true }
    return
  }

  const moved = suppressClick || Boolean(drag?.moved)
  drag = null
  suppressClick = moved
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  // 拖拽/缩放后若没有触发 click(例如指针在画布外松开),下一帧自动解除抑制,
  // 避免下一次正常点选被吞掉
  if (suppressClick) setTimeout(() => { suppressClick = false }, 0)
}

function select(node: GraphNode) {
  if (suppressClick) {
    suppressClick = false
    return
  }
  selectedId.value = node.id
  revealDetail()
}

async function loadRecommendation() {
  try {
    recommendation.value = await fetchRecommendation(strategy.value, 5)
  } catch {
    recommendation.value = null // 推荐失败不阻断图谱浏览
  }
}

async function rate(score: number) {
  if (!selected.value || ratingBusy.value) return
  ratingBusy.value = true
  try {
    await submitSelfRating(selected.value.id, score)
    showToast(t('graph.rated'))
    // 图谱与推荐互不依赖:并发取回,少等一个往返;推荐在提交诊断后发起,
    // 拿到的仍是本次评分后的结果
    const graphTask = fetchGraph()
    const recommendationTask = loadRecommendation()
    data.value = await graphTask
    await recommendationTask
  } catch (err) {
    if (statusOf(err) === 401) {
      router.replace('/login')
      return
    }
    showToast(t('graph.ratingError'))
  } finally {
    ratingBusy.value = false
  }
}

async function exportHtml() {
  try {
    const blob = await exportGraphHtml(settingsState.language)
    downloadBlob(blob, `mathguide-graph-${new Date().toISOString().slice(0, 10)}.html`)
  } catch {
    showToast(t('graph.exportError'))
  }
}

function switchStrategy(next: RecommendStrategy) {
  strategy.value = next
  void loadRecommendation()
}

function selectById(id: string) {
  const node = nodeById.value.get(id)
  if (node) pick(node)
}

/** 带着知识点进入学习辅助;聊天页消费一次 query 后立即清掉。 */
function goLearn(node: GraphNode) {
  router.push({
    path: '/learn',
    query: { point: node.id, name: displayName(node), start: '1' },
  })
}

function statusLabel(status: GraphNode['status']): string {
  if (status === 'mastered') return t('graph.legendMastered')
  if (status === 'weak') return t('graph.legendWeak')
  return t('graph.legendNew')
}

function retentionLabel(value?: number | null): string {
  return value === null || value === undefined
    ? ''
    : t('graph.retention', { pct: Math.round(value * 100) })
}

function recLabel(item: RecommendationItem): string {
  if (item.reviewDue) return t('graph.reviewDue')
  return item.reason === 'review' ? t('graph.reasonReview') : t('graph.reasonNew')
}

onMounted(async () => {
  // 图谱与推荐互不依赖,同时发出:首屏少等一个往返
  const recommendationTask = loadRecommendation()
  try {
    data.value = await fetchGraph()
    resetView()
    await recommendationTask
    // 从学习分析/分析面板跳转过来时聚焦指定知识点
    const focus = route.query.focus
    if (typeof focus === 'string' && focus) selectById(focus)
  } catch (err) {
    if (statusOf(err) === 401) {
      router.replace('/login')
      return
    }
    error.value = t('graph.error')
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
})
</script>

<template>
  <div class="graph-page">
    <Starfield class="graph-bg" />

    <header class="topbar">
      <button class="ghost" @click="router.push('/learn')">← {{ t('graph.back') }}</button>
      <div class="titles">
        <h1>{{ t('graph.title') }}</h1>
        <p class="tech-label">{{ t('graph.subtitle') }}</p>
      </div>
      <button class="ghost" @click="exportHtml">{{ t('graph.export') }}</button>
      <button class="ghost" @click="resetView">{{ t('graph.reset') }}</button>
    </header>

    <div class="toolbar">
      <div class="search">
        <input
          v-model="query"
          type="search"
          :placeholder="t('graph.search')"
          :aria-label="t('graph.search')"
        />
        <ul v-if="matches.length" class="matches">
          <li v-for="node in matches" :key="node.id" @click="pick(node)">
            <span>{{ displayName(node) }}</span>
            <em>{{ chapterLabel(node.chapter) }}</em>
          </li>
        </ul>
        <p v-else-if="query.trim()" class="no-match">{{ t('graph.empty') }}</p>
      </div>

      <div class="chapters">
        <button :class="{ on: !activeChapter }" @click="chooseChapter('')">
          {{ t('graph.all') }}
        </button>
        <button
          v-for="chapter in data?.chapters ?? []"
          :key="chapter"
          :class="{ on: activeChapter === chapter }"
          @click="chooseChapter(chapter)"
        >
          {{ chapterLabel(chapter) }}
        </button>
      </div>

      <div class="legend tech-label">
        <span class="lg mastered">{{ t('graph.legendMastered') }}</span>
        <span class="lg weak">{{ t('graph.legendWeak') }}</span>
        <span class="lg fresh">{{ t('graph.legendNew') }}</span>
      </div>
    </div>

    <main class="stage">
      <div ref="wrapEl" class="graph-viewport">
        <p v-if="loading" class="hint">{{ t('graph.loading') }}</p>
        <p v-else-if="error" class="hint error">{{ error }}</p>

        <svg
          v-else
          ref="svgEl"
          class="canvas"
          :viewBox="viewBox"
          preserveAspectRatio="xMidYMid meet"
          @wheel.prevent="onWheel"
          @pointerdown="onDown"
        >
        <defs>
          <marker
            id="mg-arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" style="fill: var(--line-bright)" />
          </marker>
        </defs>

        <g class="edges">
          <line
            v-for="edge in edgeGeoms"
            :key="edge.key"
            :x1="edge.x1"
            :y1="edge.y1"
            :x2="edge.x2"
            :y2="edge.y2"
            :class="{ dim: edge.dim }"
            marker-end="url(#mg-arrow)"
          />
        </g>

        <g class="nodes">
          <g
            v-for="geom in nodeGeoms"
            :key="geom.node.id"
            class="node"
            :class="[`is-${geom.node.status}`, { dim: geom.dim, selected: geom.node.id === selectedId }]"
            :transform="`translate(${geom.x} ${geom.y})`"
            @click.stop="select(geom.node)"
          >
            <title>{{ geom.lines.join(' ') }}</title>
            <rect :x="-geom.w / 2" :y="-geom.h / 2" :width="geom.w" :height="geom.h" rx="8" />
            <circle :cx="-geom.w / 2 + 14" cy="0" r="4" class="dot" />
            <text text-anchor="middle" x="10" :aria-label="geom.lines.join(' ')">
              <tspan
                v-for="(line, index) in geom.lines"
                :key="index"
                x="10"
                :y="(index - (geom.lines.length - 1) / 2) * 13 + 4.5"
              >{{ line }}</tspan>
            </text>
          </g>
        </g>
      </svg>
      </div>

      <div ref="panelsEl" class="panels">
        <aside v-if="selected" class="detail">
          <button class="close" :aria-label="t('graph.close')" @click="closeDetail">×</button>
        <h2>{{ displayName(selected) }}</h2>
        <span class="badge" :class="`is-${selected.status}`">{{ statusLabel(selected.status) }}</span>
        <span v-if="selected.reviewDue" class="badge is-review">{{ t('graph.reviewDue') }}</span>
        <span v-if="selected.reviewDue && selected.retention != null" class="retention-note">
          {{ retentionLabel(selected.retention) }}
        </span>

        <dl>
          <div><dt>{{ t('graph.chapter') }}</dt><dd>{{ chapterLabel(selected.chapter) }}</dd></div>
          <div><dt>{{ t('graph.difficulty') }}</dt><dd>{{ selected.difficulty }} / 5</dd></div>
          <div><dt>{{ t('graph.coreness') }}</dt><dd>{{ selected.descendantCount }}</dd></div>
          <div><dt>{{ t('graph.mastery') }}</dt><dd>{{ selected.mastery ?? '—' }}</dd></div>
        </dl>

        <section>
          <h3>{{ t('graph.selfRating') }}</h3>
          <div class="rating">
            <button
              v-for="score in 5"
              :key="score"
              :disabled="ratingBusy"
              @click="rate(score)"
            >
              {{ score }}
            </button>
          </div>
        </section>

        <section>
          <h3>{{ t('graph.prerequisites') }}</h3>
          <p v-if="!selectedPrerequisites.length" class="none">{{ t('graph.none') }}</p>
          <button
            v-for="item in selectedPrerequisites"
            :key="item.id"
            class="link-node"
            @click="pick(item)"
          >
            {{ displayName(item) }}
          </button>
        </section>

        <section>
          <h3>{{ t('graph.mainContent') }}</h3>
          <MathText v-if="summaryText(selected)" class="summary" :text="summaryText(selected)" />
          <ul v-if="keyPointTexts(selected).length" class="key-points">
            <li v-for="item in keyPointTexts(selected)" :key="item"><MathText :text="item" /></li>
          </ul>
          <p v-else-if="!summaryText(selected)" class="none">{{ t('graph.noSummary') }}</p>
          <button class="go-learn" @click="goLearn(selected)">{{ t('graph.goLearn') }}</button>
        </section>

        <section>
          <h3>{{ t('graph.dependents') }}</h3>
          <p v-if="!selectedDependents.length" class="none">{{ t('graph.none') }}</p>
          <button
            v-for="item in selectedDependents"
            :key="item.id"
            class="link-node"
            @click="pick(item)"
          >
            {{ displayName(item) }}
          </button>
        </section>
      </aside>

      <aside class="recommend" :class="{ 'is-empty': !recommendation }">
        <template v-if="recommendation">
          <div class="rec-head">
            <strong>{{ t('graph.recommend') }}</strong>
            <div class="rec-strategy">
              <button
                :class="{ on: strategy === 'difficulty' }"
                @click="switchStrategy('difficulty')"
              >
                {{ t('graph.strategyDifficulty') }}
              </button>
              <button
                :class="{ on: strategy === 'coreness' }"
                @click="switchStrategy('coreness')"
              >
                {{ t('graph.strategyCoreness') }}
              </button>
            </div>
          </div>
          <p v-if="!recommendation.items.length" class="none">{{ t('graph.noRecommendation') }}</p>
          <button
            v-for="item in recommendation.items"
            :key="item.pointId"
            class="rec-item"
            @click="selectById(item.pointId)"
          >
            <span class="rec-name">{{ displayName(nodeById.get(item.pointId) ?? item) }}</span>
            <span class="rec-meta">
              {{ recLabel(item) }} · {{ item.difficulty }}/5
              <template v-if="item.reviewDue && item.retention != null">
                · {{ retentionLabel(item.retention) }}
              </template>
            </span>
          </button>
        </template>
        <p v-else class="none">{{ t('graph.noRecommendation') }}</p>
      </aside>
      </div>
    </main>
  </div>
</template>

<style scoped>
.graph-page {
  min-height: 100vh;
  /* iPad/手机 Safari 的 100vh 含工具栏区域,dvh 跟随可见视口,横竖屏都适用 */
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
  background: var(--bg-void);
  color: var(--text);
}

.graph-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  opacity: 0.5;
  pointer-events: none;
}

.topbar,
.toolbar,
.stage {
  position: relative;
  z-index: 1;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: calc(16px + env(safe-area-inset-top)) 26px 16px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-void) 78%, transparent);
}

.titles {
  flex: 1;
  min-width: 0;
  text-align: center;
}

.titles h1 {
  margin: 0;
  font-size: 20px;
  letter-spacing: 0.08em;
  color: var(--text-hi);
}

.titles p {
  margin: 3px 0 0;
  font-size: 11px;
  color: var(--text-dim);
}

.ghost {
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: transparent;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 12px;
  cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}

.ghost:hover {
  border-color: var(--line-bright);
  color: var(--text-hi);
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 10px 26px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-void) 72%, transparent);
}

.search {
  position: relative;
  min-width: 210px;
}

.search input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-hi);
  font-family: var(--font-ui);
  font-size: 12px;
  outline: none;
}

.search input:focus {
  border-color: var(--line-bright);
}

.matches {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  margin: 0;
  padding: 4px;
  list-style: none;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  backdrop-filter: blur(12px);
  z-index: 5;
}

.matches li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 8px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.matches li:hover {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
}

.matches em {
  font-style: normal;
  color: var(--text-dim);
  font-size: 11px;
}

.no-match {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  right: 0;
  margin: 0;
  padding: 8px 10px;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-dim);
}

.chapters {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  flex: 1;
  min-width: 240px;
  scrollbar-width: thin;
}

.chapters button {
  white-space: nowrap;
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--text-dim);
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
}

.chapters button.on {
  border-color: var(--cyan);
  color: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.legend {
  display: flex;
  gap: 12px;
  font-size: 10px;
  color: var(--text-dim);
}

.lg {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.lg::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
}

.lg.mastered {
  color: var(--cyan);
}

.lg.weak {
  color: var(--danger);
}

.lg.fresh {
  color: var(--text-dim);
}

.stage {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
}

.graph-viewport {
  position: absolute;
  inset: 0;
}

/* 宽屏:推荐/详情仍是画布上的浮层;panels 不生成盒子 */
.panels {
  display: contents;
}

.canvas {
  width: 100%;
  height: 100%;
  display: block;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.canvas:active {
  cursor: grabbing;
}

.hint {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  margin: 0;
  color: var(--text-dim);
  font-size: 13px;
}

.hint.error {
  color: var(--danger);
}

.edges line {
  stroke: var(--line-bright);
  stroke-width: 1;
  opacity: 0.55;
  transition: opacity var(--dur-fast);
}

.edges line.dim {
  opacity: 0.06;
}

.node rect {
  fill: var(--bg-card);
  stroke: var(--line-bright);
  stroke-width: 1.2;
}

.node .dot {
  fill: var(--text-dim);
}

.node text {
  fill: var(--text);
  font-family: var(--font-ui);
  font-size: 12.5px;
  pointer-events: none;
}

.node {
  cursor: pointer;
  transition: opacity var(--dur-fast);
}

.node.is-mastered rect {
  stroke: var(--cyan);
  filter: drop-shadow(0 0 5px rgba(77, 214, 255, 0.35));
}

.node.is-mastered .dot {
  fill: var(--cyan);
}

.node.is-weak rect {
  stroke: var(--danger);
}

.node.is-weak .dot {
  fill: var(--danger);
}

.node.selected rect {
  stroke: var(--violet);
  stroke-width: 2;
  filter: drop-shadow(0 0 8px rgba(139, 92, 246, 0.6));
}

.node.dim {
  opacity: 0.14;
}

.detail {
  position: absolute;
  top: 18px;
  right: 18px;
  bottom: 18px;
  width: 300px;
  max-width: calc(100% - 36px);
  padding: 18px;
  overflow-y: auto;
  box-sizing: border-box;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 14px;
  backdrop-filter: blur(14px);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
}

.close {
  position: absolute;
  top: 10px;
  right: 12px;
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 20px;
  line-height: 1;
  cursor: pointer;
}

.detail h2 {
  margin: 0 26px 8px 0;
  font-size: 17px;
  color: var(--text-hi);
}

.badge {
  display: inline-block;
  padding: 3px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 11px;
}

.badge.is-mastered {
  color: var(--cyan);
  border-color: var(--cyan);
}

.badge.is-weak {
  color: var(--danger);
  border-color: var(--danger);
}

.badge.is-new {
  color: var(--text-dim);
}

.badge.is-review {
  color: var(--magenta);
  border-color: var(--magenta);
}

.retention-note {
  margin-left: 6px;
  font-size: 10px;
  color: var(--text-dim);
}

.detail dl {
  margin: 16px 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.detail dl div {
  padding: 8px 10px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
}

.detail dt {
  font-size: 10px;
  color: var(--text-dim);
}

.detail dd {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--text-hi);
}

.detail section {
  margin-top: 16px;
}

.detail h3 {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--text-dim);
  font-weight: 500;
}

.none {
  margin: 0;
  font-size: 12px;
  color: var(--text-dim);
}

.link-node {
  display: block;
  width: 100%;
  margin-bottom: 6px;
  padding: 7px 9px;
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 7px;
  background: transparent;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 12px;
  cursor: pointer;
}

.link-node:hover {
  border-color: var(--cyan);
  color: var(--cyan);
}

.summary {
  margin: 0 0 8px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
}

.key-points {
  margin: 0 0 10px;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-dim);
}

.key-points li {
  margin-bottom: 4px;
}

.go-learn {
  width: 100%;
  margin-top: 6px;
  padding: 8px 10px;
  border: 1px solid var(--line-bright);
  border-radius: 7px;
  background: rgba(77, 214, 255, 0.1);
  color: var(--cyan);
  font-family: var(--font-ui);
  font-size: 12px;
  cursor: pointer;
}

.go-learn:hover {
  box-shadow: var(--glow-cyan);
}

.rating {
  display: flex;
  gap: 6px;
}

.rating button {
  flex: 1;
  padding: 6px 0;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: transparent;
  color: var(--text);
  font-family: var(--font-tech);
  font-size: 12px;
  cursor: pointer;
}

.rating button:hover:not(:disabled) {
  border-color: var(--cyan);
  color: var(--cyan);
}

.rating button:disabled {
  opacity: 0.45;
  cursor: wait;
}

.recommend {
  position: absolute;
  left: 18px;
  bottom: 18px;
  width: 280px;
  max-height: 46%;
  overflow-y: auto;
  padding: 14px;
  box-sizing: border-box;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  backdrop-filter: blur(14px);
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.3);
}

/* 桌面端推荐加载失败/无数据时不占画布;手机端保留占位作为左滑起点 */
@media (min-width: 761px) {
  .recommend.is-empty {
    display: none;
  }
}

.rec-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.rec-head strong {
  font-size: 13px;
  color: var(--text-hi);
}

.rec-strategy {
  display: flex;
  gap: 6px;
}

.rec-strategy button {
  padding: 4px 8px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: transparent;
  color: var(--text-dim);
  font-family: var(--font-ui);
  font-size: 11px;
  cursor: pointer;
}

.rec-strategy button.on {
  border-color: var(--cyan);
  color: var(--cyan);
}

.rec-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  width: 100%;
  margin-bottom: 6px;
  padding: 8px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text);
  text-align: left;
  cursor: pointer;
}

.rec-item:hover {
  border-color: var(--cyan);
}

.rec-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-hi);
}

.rec-meta {
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
}

@media (max-width: 760px) {
  .topbar {
    flex-wrap: wrap;
    gap: 8px;
    padding: calc(10px + env(safe-area-inset-top)) 14px 10px;
  }

  .titles {
    order: -1;
    flex-basis: 100%;
    text-align: left;
  }

  .titles h1 {
    font-size: 16px;
  }

  .titles p {
    display: none;
  }

  .toolbar {
    gap: 8px;
    padding: 8px 14px;
  }

  .search {
    flex: 1 1 100%;
    min-width: 0;
  }

  .chapters {
    flex: 1 1 100%;
    min-width: 0;
  }

  /* 手机:图谱在上,推荐/详情合并成下方横向滑动窗口 */
  .stage {
    display: flex;
    flex-direction: column;
  }

  .graph-viewport {
    position: relative;
    inset: auto;
    flex: 1;
    min-height: 0;
  }

  .panels {
    display: flex;
    flex: none;
    height: clamp(140px, 38dvh, 360px);
    overflow-x: auto;
    overflow-y: hidden;
    scroll-snap-type: x mandatory;
    overscroll-behavior: contain;
    -webkit-overflow-scrolling: touch;
    background: var(--bg-panel);
    border-top: 1px solid var(--line);
    scrollbar-width: none;
  }

  .panels::-webkit-scrollbar {
    display: none;
  }

  .panels > .recommend,
  .panels > .detail {
    position: relative;
    inset: auto;
    flex: 0 0 100%;
    width: 100%;
    max-width: none;
    max-height: none;
    height: 100%;
    margin: 0;
    padding: 14px 16px calc(14px + env(safe-area-inset-bottom));
    overflow-y: auto;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
    backdrop-filter: none;
    scroll-snap-align: start;
    scroll-snap-stop: always;
  }

  /* 视觉顺序固定为「推荐 → 详情」,与 DOM 顺序无关 */
  .panels > .recommend {
    order: 0;
  }

  .panels > .detail {
    order: 1;
  }
}
</style>
