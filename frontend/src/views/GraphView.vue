<script setup lang="ts">
/**
 * 知识图谱:拓扑分层布局 + 缩放/拖拽 + 点选详情。
 *
 * 布局用纯函数 utils/graphLayout(最长路径分层),节点按掌握度着色:
 * 已掌握 / 薄弱 / 未诊断。章节筛选会把视图聚焦到该章节的节点范围。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import Starfield from '@/components/common/Starfield.vue'
import { statusOf } from '@/api/http'
import {
  fetchGraph,
  fetchRecommendation,
  submitSelfRating,
  type GraphData,
  type GraphEdge,
  type GraphNode,
  type Recommendation,
  type RecommendStrategy,
} from '@/services/graphService'
import { layoutGraph, type GraphPosition } from '@/utils/graphLayout'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const router = useRouter()
const data = ref<GraphData | null>(null)
const loading = ref(true)
const error = ref('')
const wrapEl = ref<HTMLElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
const selectedId = ref('')
const activeChapter = ref('')
const query = ref('')
const recommendation = ref<Recommendation | null>(null)
const strategy = ref<RecommendStrategy>('difficulty')
const ratingBusy = ref(false)

const NODE_HALF_W = 82
const view = reactive({ x: 0, y: 0, w: 1200, h: 800 })

const nodes = computed(() => data.value?.nodes ?? [])
const edges = computed(() => data.value?.edges ?? [])
const layout = computed(() => layoutGraph(nodes.value))
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

const matches = computed(() => {
  const term = query.value.trim().toLowerCase()
  if (!term) return []
  return nodes.value.filter((node) =>
    node.name.toLowerCase().includes(term)
    || node.id.toLowerCase().includes(term)
    || node.chapter.toLowerCase().includes(term),
  ).slice(0, 8)
})

function resolve(ids: string[]): GraphNode[] {
  return ids.map((id) => nodeById.value.get(id)).filter((node): node is GraphNode => Boolean(node))
}

function pos(id: string): GraphPosition {
  return layout.value.positions[id] ?? { x: 0, y: 0, level: 0 }
}

function label(name: string): string {
  return name.length > 12 ? `${name.slice(0, 11)}…` : name
}

function isDim(node: GraphNode): boolean {
  return Boolean(activeChapter.value) && node.chapter !== activeChapter.value
}

function isEdgeDim(edge: GraphEdge): boolean {
  if (!activeChapter.value) return false
  const source = nodeById.value.get(edge.source)
  const target = nodeById.value.get(edge.target)
  return source?.chapter !== activeChapter.value
    || target?.chapter !== activeChapter.value
}

function aspectRatio(): number {
  const el = wrapEl.value
  if (!el || !el.clientWidth || !el.clientHeight) return 1.6
  return el.clientWidth / el.clientHeight
}

function resetView() {
  activeChapter.value = ''
  const graph = layout.value
  const aspect = aspectRatio()
  const height = Math.max(graph.height, 620)
  const width = Math.min(graph.width, height * aspect)
  view.w = Math.max(640, width)
  view.h = view.w / aspect
  view.x = 0
  view.y = (graph.height - view.h) / 2
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
}

function svgPoint(event: MouseEvent): DOMPoint {
  const svg = svgEl.value
  if (!svg) return new DOMPoint(event.clientX, event.clientY)
  const point = svg.createSVGPoint()
  point.x = event.clientX
  point.y = event.clientY
  const matrix = svg.getScreenCTM()
  return matrix ? point.matrixTransform(matrix.inverse()) : point
}

function onWheel(event: WheelEvent) {
  if (!svgEl.value) return
  const point = svgPoint(event)
  const factor = event.deltaY > 0 ? 1.15 : 1 / 1.15
  const nextWidth = Math.min(
    Math.max(500, view.w * factor),
    Math.max(1200, layout.value.width * 1.6),
  )
  const scale = nextWidth / view.w
  view.x = point.x - (point.x - view.x) * scale
  view.y = point.y - (point.y - view.y) * scale
  view.w = nextWidth
  view.h *= scale
}

let drag: { pointerId: number; last: DOMPoint; moved: boolean } | null = null
let suppressClick = false

function onDown(event: PointerEvent) {
  if (event.button !== 0) return
  drag = { pointerId: event.pointerId, last: svgPoint(event), moved: false }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}

function onMove(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  const point = svgPoint(event)
  const dx = point.x - drag.last.x
  const dy = point.y - drag.last.y
  if (Math.abs(dx) + Math.abs(dy) > 1) drag.moved = true
  view.x -= dx
  view.y -= dy
  drag.last = point
}

function onUp(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return
  suppressClick = drag.moved
  drag = null
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  window.removeEventListener('pointercancel', onUp)
  // 拖拽后若没有触发 click(例如指针在画布外松开),下一帧自动解除抑制,
  // 避免下一次正常点选被吞掉
  if (suppressClick) setTimeout(() => { suppressClick = false }, 0)
}

function select(node: GraphNode) {
  if (suppressClick) {
    suppressClick = false
    return
  }
  selectedId.value = node.id
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
    data.value = await fetchGraph()
    await loadRecommendation()
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

function switchStrategy(next: RecommendStrategy) {
  strategy.value = next
  void loadRecommendation()
}

function selectById(id: string) {
  const node = nodeById.value.get(id)
  if (node) pick(node)
}

function statusLabel(status: GraphNode['status']): string {
  if (status === 'mastered') return t('graph.legendMastered')
  if (status === 'weak') return t('graph.legendWeak')
  return t('graph.legendNew')
}

onMounted(async () => {
  try {
    data.value = await fetchGraph()
    resetView()
    await loadRecommendation()
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
      <button class="ghost" @click="router.push('/home')">← {{ t('graph.back') }}</button>
      <div class="titles">
        <h1>{{ t('graph.title') }}</h1>
        <p class="tech-label">{{ t('graph.subtitle') }}</p>
      </div>
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
            <span>{{ node.name }}</span>
            <em>{{ node.chapter }}</em>
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
          {{ chapter }}
        </button>
      </div>

      <div class="legend tech-label">
        <span class="lg mastered">{{ t('graph.legendMastered') }}</span>
        <span class="lg weak">{{ t('graph.legendWeak') }}</span>
        <span class="lg fresh">{{ t('graph.legendNew') }}</span>
      </div>
    </div>

    <main ref="wrapEl" class="stage">
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
            v-for="(edge, index) in edges"
            :key="`${edge.source}-${edge.target}-${index}`"
            :x1="pos(edge.source).x + NODE_HALF_W"
            :y1="pos(edge.source).y"
            :x2="pos(edge.target).x - NODE_HALF_W - 2"
            :y2="pos(edge.target).y"
            :class="{ dim: isEdgeDim(edge) }"
            marker-end="url(#mg-arrow)"
          />
        </g>

        <g class="nodes">
          <g
            v-for="node in nodes"
            :key="node.id"
            class="node"
            :class="[`is-${node.status}`, { dim: isDim(node), selected: node.id === selectedId }]"
            :transform="`translate(${pos(node.id).x} ${pos(node.id).y})`"
            @click.stop="select(node)"
          >
            <rect x="-82" y="-18" width="164" height="36" rx="8" />
            <circle cx="-67" cy="0" r="4" class="dot" />
            <text text-anchor="middle" dy="4.5">{{ label(node.name) }}</text>
          </g>
        </g>
      </svg>

      <aside v-if="selected" class="detail">
        <button class="close" :aria-label="t('graph.close')" @click="selectedId = ''">×</button>
        <h2>{{ selected.name }}</h2>
        <span class="badge" :class="`is-${selected.status}`">{{ statusLabel(selected.status) }}</span>

        <dl>
          <div><dt>{{ t('graph.chapter') }}</dt><dd>{{ selected.chapter }}</dd></div>
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
            {{ item.name }}
          </button>
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
            {{ item.name }}
          </button>
        </section>
      </aside>

      <aside v-if="recommendation" class="recommend">
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
          <span class="rec-name">{{ item.name }}</span>
          <span class="rec-meta">
            {{ item.reason === 'review' ? t('graph.reasonReview') : t('graph.reasonNew') }}
            · {{ item.difficulty }}/5
          </span>
        </button>
      </aside>
    </main>
  </div>
</template>

<style scoped>
.graph-page {
  min-height: 100vh;
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
  padding: 16px 26px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-void) 78%, transparent);
}

.titles {
  flex: 1;
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
    padding: 12px 14px;
  }

  .titles h1 {
    font-size: 16px;
  }

  .toolbar {
    padding: 8px 14px;
  }

  .detail {
    top: auto;
    left: 10px;
    right: 10px;
    bottom: 10px;
    width: auto;
    max-height: 46%;
  }

  .recommend {
    top: 10px;
    left: 10px;
    bottom: auto;
    width: min(280px, calc(100% - 20px));
    max-height: 38%;
  }
}
</style>
