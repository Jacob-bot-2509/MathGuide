<script setup lang="ts">
/** 从公式库为当前表推荐 Top-3 候选;用户点选后由父组件写入公式。 */
import { computed, onMounted, ref } from 'vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import {
  matchTableFormulas,
  type FormulaCandidate,
} from '@/services/researchTableService'

const props = defineProps<{ tableId: string; docId?: string }>()
const emit = defineEmits<{
  close: []
  apply: [candidate: FormulaCandidate]
  applyMany: [candidates: FormulaCandidate[]]
}>()

const loading = ref(true)
const candidates = ref<FormulaCandidate[]>([])
const selected = ref<Set<string>>(new Set())

function keyOf(item: FormulaCandidate): string {
  return item.formulaId || item.expr
}

function toggle(item: FormulaCandidate): void {
  const key = keyOf(item)
  const next = new Set(selected.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selected.value = next
}

function applySelected(): void {
  const chosen = candidates.value.filter((item) => selected.value.has(keyOf(item)))
  if (chosen.length) emit('applyMany', chosen)
}

const best = computed(() => candidates.value.find((item) =>
  item.formula && item.score >= 8 &&
  Array.isArray(item.unitConflicts) && item.unitConflicts.length === 0 &&
  item.validation && item.validation.compared > 0 &&
  item.validation.unverified === 0 && item.validation.calculationErrors === 0 &&
  item.validation.matched === item.validation.compared,
) ?? null)

onMounted(async () => {
  try {
    candidates.value = await matchTableFormulas(props.tableId, props.docId)
    if (best.value) selected.value = new Set([keyOf(best.value)])
  } catch {
    showToast(t('formula.matchFail'))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="fm-overlay" @click.self="emit('close')">
    <section class="fm-panel">
      <header class="fm-head">
        <span class="fm-title">{{ t('formula.matchTitle') }}</span>
        <button class="fm-close" @click="emit('close')">✕</button>
      </header>
      <p v-if="loading" class="fm-state">{{ t('formula.matching') }}</p>
      <p v-else-if="!candidates.length" class="fm-state">{{ t('formula.matchEmpty') }}</p>
      <div v-else class="fm-list">
        <div v-if="best" class="fm-best">
          <span>{{ t('formula.matchHigh') }}</span>
          <button type="button" @click="emit('apply', best)">
            {{ t('formula.matchApplyBest') }}
          </button>
        </div>
        <article v-for="item in candidates" :key="item.formulaId || item.expr" class="fm-card">
          <div class="fm-row">
            <input
              type="checkbox"
              :checked="selected.has(keyOf(item))"
              @change="toggle(item)"
            />
            <span class="fm-target">{{ item.target }}</span>
            <span class="fm-score">score {{ item.score.toFixed(2) }}</span>
          </div>
          <code class="fm-expr">{{ item.formula || item.expr }}</code>
          <p v-for="conflict in item.unitConflicts" :key="conflict.variable" class="fm-unit-warning">
            {{ t('formula.matchUnitConflict', {
              name: conflict.variable, expected: conflict.expected, actual: conflict.actual,
            }) }}
          </p>
          <p v-if="item.validation" class="fm-valid">
            {{ t('formula.validateResult', {
              m: item.validation.matched,
              n: item.validation.compared,
              e: item.validation.maxError,
            }) }}
          </p>
          <p v-if="item.validation && (item.validation.unverified || item.validation.calculationErrors)" class="fm-unit-warning">
            {{ t('formula.matchIncompleteValidation', {
              skipped: item.validation.unverified ?? 0, errors: item.validation.calculationErrors ?? 0,
            }) }}
          </p>
          <p
            v-for="sample in (item.validation?.samples ?? []).slice(0, 3)"
            :key="sample.row"
            class="fm-sample"
            :class="{ bad: !sample.ok }"
          >
            {{ t('tables.rowNo', { n: sample.row + 1 }) }}:
            {{ sample.actual }} → {{ sample.predicted }}
          </p>
          <div class="fm-map">
            <span v-for="(col, variable) in item.mapping" :key="variable" class="fm-map-item">
              {{ variable }} → {{ col }}<template v-if="item.units?.[variable]">
                ({{ item.units[variable] }})</template>
            </span>
          </div>
          <button class="fm-apply" type="button" @click="emit('apply', item)">
            {{ t('formula.matchApply') }}
          </button>
        </article>
        <footer class="fm-foot">
          <button class="fm-apply" type="button" :disabled="!selected.size" @click="applySelected">
            {{ t('formula.matchApplySelected', { n: selected.size }) }}
          </button>
        </footer>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fm-overlay {
  position: fixed;
  inset: 0;
  z-index: 95;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 8, 18, 0.66);
  backdrop-filter: blur(3px);
}

.fm-panel {
  width: min(620px, calc(100vw - 32px));
  max-height: 78vh;
  overflow-y: auto;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
}

.fm-head {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.fm-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 12px;
}

.fm-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
}

.fm-state {
  padding: 24px 16px;
  color: var(--text-dim);
  font-size: 12px;
}

.fm-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 16px 16px;
}

.fm-best {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--cyan) 45%, transparent);
  border-radius: 7px;
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
  color: var(--text-hi);
  font-size: 11.5px;
}

.fm-best button {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 5px;
  font-size: 11px;
  padding: 3px 9px;
  cursor: pointer;
}

.fm-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: var(--bg-card);
}

.fm-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.fm-row input {
  accent-color: var(--cyan);
}

.fm-foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

.fm-apply:disabled {
  opacity: 0.5;
  cursor: default;
}

.fm-target {
  color: var(--cyan);
  font-size: 13px;
}

.fm-score {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10px;
  font-family: var(--font-tech);
}

.fm-expr {
  display: block;
  margin-top: 5px;
  color: #ffd166;
  font-family: var(--font-tech);
  font-size: 12px;
  word-break: break-all;
}

.fm-valid {
  margin: 5px 0 0;
  color: var(--text-dim);
  font-size: 10.5px;
}

.fm-sample {
  margin: 2px 0 0;
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10px;
}

.fm-sample.bad,
.fm-unit-warning {
  color: #ff8a8a;
}

.fm-map {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}

.fm-map-item {
  color: var(--text-dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 6px;
  font-size: 10px;
}

.fm-apply {
  margin-top: 8px;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 5px;
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
}
</style>
