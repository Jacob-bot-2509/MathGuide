<script setup lang="ts">
/**
 * 学习分析指令面板:展示服务端算好的掌握度快照,并提供快速自评入口。
 * 面板只负责呈现与提交自评;真正的多维度分析由「让 MG 分析」发到聊天流,
 * 模型只解读服务端事实,不在前端计算分数。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { statusOf } from '@/api/http'
import { fetchLearningAnalysis, submitSelfRating, type AnalysisPoint, type LearningAnalysis } from '@/services/graphService'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const props = defineProps<{ left?: number; width?: number }>()
const emit = defineEmits<{ close: []; analyze: [] }>()

const router = useRouter()
const data = ref<LearningAnalysis | null>(null)
const loading = ref(true)
const error = ref('')
const ratingBusy = ref('')

const percent = computed(() => Math.round((data.value?.coverage.ratio ?? 0) * 100))
const bottlenecks = computed(() => data.value?.bottlenecks ?? [])
const nextSteps = computed(() => data.value?.nextSteps ?? [])
const suggested = computed(() => data.value?.suggestedDiagnosis ?? [])
const stale = computed(() => data.value?.stale ?? [])

const qualityText = computed(() => {
  const value = data.value
  if (!value) return ''
  if (value.dataQuality === 'none') return t('analysis.qualityNone')
  if (value.dataQuality === 'sparse') {
    return t('analysis.qualitySparse', {
      n: value.coverage.diagnosed,
      min: value.limits.minSample,
    })
  }
  return t('analysis.qualityOk')
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    data.value = await fetchLearningAnalysis()
  } catch (err) {
    if (statusOf(err) === 401) {
      router.replace('/login')
      return
    }
    error.value = t('analysis.error')
  } finally {
    loading.value = false
  }
}

async function rate(point: AnalysisPoint, score: number): Promise<void> {
  if (ratingBusy.value) return
  ratingBusy.value = point.pointId
  try {
    await submitSelfRating(point.pointId, score)
    showToast(t('analysis.rated'))
    await load()
  } catch (err) {
    if (statusOf(err) === 401) {
      router.replace('/login')
      return
    }
    showToast(t('graph.ratingError'))
  } finally {
    ratingBusy.value = ''
  }
}

function openInGraph(pointId = ''): void {
  emit('close')
  router.push({ path: '/graph', query: pointId ? { focus: pointId } : {} })
}

function reasonLabel(point: AnalysisPoint): string {
  return point.reason === 'review' ? t('analysis.reasonReview') : t('analysis.reasonNew')
}

function retentionLabel(point: AnalysisPoint): string {
  const pct = Math.round((point.retention ?? 0) * 100)
  return t('analysis.retention', { pct })
}

onMounted(load)
</script>

<template>
  <div
    class="ana-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
    <section class="ana-panel">
      <header class="panel-head">
        <span class="tech-label panel-title">◇ {{ t('analysis.title') }}</span>
        <button class="close" aria-label="close" @click="emit('close')">✕</button>
      </header>

      <p v-if="loading" class="ana-hint">{{ t('analysis.loading') }}</p>
      <p v-else-if="error" class="ana-hint error">{{ error }}</p>

      <template v-else-if="data">
        <p class="ana-quality" :class="`is-${data.dataQuality}`">{{ qualityText }}</p>

        <div class="ana-coverage">
          <div class="ana-bar"><span :style="{ width: `${percent}%` }"></span></div>
          <p class="tech-label">
            {{ t('analysis.coverage', {
              done: data.coverage.diagnosed,
              total: data.coverage.total,
              pct: percent,
            }) }}
          </p>
        </div>

        <dl class="ana-stats">
          <div><dt>{{ t('analysis.mastered') }}</dt><dd>{{ data.structure.mastered }}</dd></div>
          <div><dt>{{ t('analysis.weak') }}</dt><dd>{{ data.structure.weak }}</dd></div>
          <div><dt>{{ t('analysis.stale') }}</dt><dd>{{ data.structure.stale }}</dd></div>
          <div><dt>{{ t('analysis.undiagnosed') }}</dt><dd>{{ data.structure.undiagnosed }}</dd></div>
        </dl>

        <section v-if="bottlenecks.length" class="ana-section">
          <h3>{{ t('analysis.bottlenecks') }}</h3>
          <ul class="ana-list">
            <li v-for="row in bottlenecks" :key="`b-${row.pointId}`">
              <button class="ana-link" @click="openInGraph(row.pointId)">{{ row.name }}</button>
              <em>{{ t('analysis.blocks', { n: row.descendantCount }) }}</em>
            </li>
          </ul>
        </section>

        <section v-if="stale.length" class="ana-section">
          <h3>{{ t('analysis.staleSection') }}</h3>
          <ul class="ana-list">
            <li v-for="row in stale" :key="`s-${row.pointId}`">
              <button class="ana-link" @click="openInGraph(row.pointId)">{{ row.name }}</button>
              <em>
                {{ retentionLabel(row) }} · {{ t('analysis.daysAgo', { n: row.days ?? 0 }) }}
              </em>
            </li>
          </ul>
        </section>

        <section v-if="suggested.length" class="ana-section">
          <h3>{{ t('analysis.quickDiagnosis') }}</h3>
          <p class="ana-note">{{ t('analysis.quickDiagnosisHint') }}</p>
          <ul class="ana-rate">
            <li v-for="row in suggested" :key="`d-${row.pointId}`">
              <button class="ana-link" @click="openInGraph(row.pointId)">{{ row.name }}</button>
              <span class="ana-scores">
                <button
                  v-for="score in 5"
                  :key="score"
                  :disabled="ratingBusy === row.pointId"
                  @click="rate(row, score)"
                >{{ score }}</button>
              </span>
            </li>
          </ul>
        </section>

        <section v-if="nextSteps.length" class="ana-section">
          <h3>{{ t('analysis.next') }}</h3>
          <ul class="ana-list">
            <li v-for="row in nextSteps" :key="`n-${row.pointId}`">
              <button class="ana-link" @click="openInGraph(row.pointId)">{{ row.name }}</button>
              <em>{{ reasonLabel(row) }}</em>
            </li>
          </ul>
        </section>

        <footer class="ana-actions">
          <button class="primary" @click="emit('analyze')">{{ t('analysis.askMg') }}</button>
          <button class="ghost" @click="openInGraph()">{{ t('analysis.openGraph') }}</button>
        </footer>
      </template>
    </section>
  </div>
</template>

<style scoped>
.ana-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.ana-panel {
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  width: min(420px, calc(100vw - 32px));
  max-height: 58vh;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow-y: auto;
  box-shadow: 0 12px 34px rgba(0, 0, 0, 0.45);
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.panel-title {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--cyan);
}

.close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all var(--dur-fast) var(--ease-out);
}

.close:hover {
  color: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.ana-hint {
  margin: 0;
  padding: 14px 16px;
  font-size: 12px;
  color: var(--text-dim);
}

.ana-hint.error {
  color: var(--red, #ff6b6b);
}

.ana-quality {
  margin: 10px 16px 0;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-dim);
  background: rgba(113, 130, 153, 0.12);
}

.ana-quality.is-none {
  color: #ffb86b;
  background: rgba(255, 184, 107, 0.12);
}

.ana-quality.is-sparse {
  color: var(--cyan);
  background: rgba(77, 214, 255, 0.1);
}

.ana-coverage {
  padding: 10px 16px 0;
}

.ana-bar {
  height: 4px;
  border-radius: 2px;
  background: var(--line);
  overflow: hidden;
}

.ana-bar span {
  display: block;
  height: 100%;
  background: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.ana-coverage p {
  margin: 6px 0 0;
  font-size: 10px;
  color: var(--text-dim);
}

.ana-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  margin: 10px 16px 0;
}

.ana-stats div {
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 6px;
  text-align: center;
}

.ana-stats dt {
  font-size: 10px;
  color: var(--text-dim);
}

.ana-stats dd {
  margin: 2px 0 0;
  font-family: var(--font-tech);
  font-size: 15px;
  color: var(--text-hi);
}

.ana-section {
  padding: 10px 16px 0;
}

.ana-section h3 {
  margin: 0 0 4px;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.08em;
  color: var(--cyan);
}

.ana-note {
  margin: 0 0 4px;
  font-size: 10px;
  color: var(--text-dim);
}

.ana-list,
.ana-rate {
  list-style: none;
  margin: 0;
  padding: 0;
}

.ana-list li,
.ana-rate li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 3px 0;
  font-size: 12px;
}

.ana-list em,
.ana-rate em {
  font-style: normal;
  font-size: 10px;
  color: var(--text-dim);
  white-space: nowrap;
}

.ana-link {
  background: transparent;
  border: none;
  padding: 0;
  color: var(--text-hi);
  font-size: 12px;
  cursor: pointer;
  text-align: left;
}

.ana-link:hover {
  color: var(--cyan);
  text-decoration: underline;
}

.ana-scores {
  display: flex;
  gap: 3px;
}

.ana-scores button {
  width: 20px;
  height: 20px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: transparent;
  color: var(--text-dim);
  font-size: 10px;
  cursor: pointer;
}

.ana-scores button:hover:not(:disabled) {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.ana-scores button:disabled {
  opacity: 0.4;
  cursor: default;
}

.ana-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  margin-top: 6px;
  border-top: 1px solid var(--line);
  position: sticky;
  bottom: 0;
  background: var(--bg-panel);
}

.ana-actions button {
  flex: 1;
  padding: 7px 10px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.ana-actions .primary {
  border: 1px solid var(--line-bright);
  background: rgba(77, 214, 255, 0.12);
  color: var(--cyan);
}

.ana-actions .ghost {
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-dim);
}

.ana-actions button:hover {
  box-shadow: var(--glow-cyan);
}
</style>
