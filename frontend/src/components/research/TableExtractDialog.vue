<script setup lang="ts">
/**
 * 论文表格转录预览:识别结果先逐格校对,用户确认后才写入数据表。
 * 保存时记录来源(docId / 页码 / 表注),供之后回看原文。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import {
  createResearchTable,
  type TableColumn,
} from '@/services/researchTableService'
import type { ExtractedPaperTable } from '@/services/researchService'

const props = defineProps<{
  preview: ExtractedPaperTable
  docId: string
  docName: string
  page: number
  projectId?: string | null
}>()
const emit = defineEmits<{ close: []; saved: [tableId: string] }>()
const router = useRouter()

const title = ref(props.preview.title || t('tableExtract.defaultTitle'))
const columns = ref(props.preview.columns.map((v) => v.slice(0, 60)))
const rows = ref(props.preview.rows.map((row) => [...row]))
const saving = ref(false)
const handwriting = computed(() => props.preview.handwriting)
const includeHandwriting = ref(Boolean(props.preview.handwriting?.detected))
const handwrittenCells = computed(() => new Set(
  (props.preview.handwriting?.cells ?? []).map(([r, c]) => `${r}:${c}`),
))

function isHandwritten(ri: number, ci: number): boolean {
  return handwrittenCells.value.has(`${ri}:${ci}`)
}

const warnings = computed(() => props.preview.warnings.filter(Boolean))

function isNumericColumn(index: number): boolean {
  const values = rows.value
    .map((row) => (row[index] ?? '').trim())
    .filter((v) => v !== '')
  return values.length > 0 && values.every((v) => Number.isFinite(Number(v)))
}

function buildColumns(): TableColumn[] {
  return columns.value.map((label, i) => ({
    key: columnKey(i),
    label: label || columnKey(i),
    type: isNumericColumn(i) ? 'number' : 'text',
  }))
}

function columnKey(index: number): string {
  let n = index + 1
  let out = ''
  while (n > 0) {
    n -= 1
    out = String.fromCharCode(65 + (n % 26)) + out
    n = Math.floor(n / 26)
  }
  return out
}

async function save(): Promise<void> {
  if (saving.value) return
  saving.value = true
  try {
    const exportRows = rows.value.map((row) => [...row])
    if (handwriting.value?.detected && !includeHandwriting.value) {
      if (!handwrittenCells.value.size) {
        showToast(t('tableExtract.handwritingNoCells'))
        return
      }
      for (const [r, c] of handwriting.value.cells) {
        if (exportRows[r] && c < exportRows[r].length) exportRows[r][c] = ''
      }
    }
    const created = await createResearchTable({
      title: title.value.trim().slice(0, 120) || t('tableExtract.defaultTitle'),
      columns: buildColumns(),
      rows: exportRows.map((row) => row.map((v) => String(v).slice(0, 200))),
      formulas: {},
      rowLabels: rows.value.map(() => ''),
      merges: [],
      colWidths: columns.value.map(() => 120),
      rowHeights: rows.value.map(() => 30),
      projectId: props.projectId || null,
      source: {
        docId: props.docId,
        docName: props.docName,
        page: props.page,
        quote: props.preview.notes?.slice(0, 300) || '',
        kind: 'paper',
      },
    })
    showToast(t('tableExtract.saved'))
    emit('saved', created.id)
    const query: Record<string, string> = { tableId: created.id }
    if (props.projectId) query.projectId = props.projectId
    await router.push({ path: '/research/tables', query })
  } catch {
    showToast(t('tableExtract.fail'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="te-overlay" @click.self="emit('close')">
    <section class="te-panel" role="dialog" aria-modal="true">
      <header class="te-head">
        <span class="te-title">{{ t('tableExtract.title') }}</span>
        <button class="te-close" :title="t('common.close')" @click="emit('close')">✕</button>
      </header>

      <div class="te-meta">
        <span>{{ t('tableExtract.source') }}:{{ docName }}<template v-if="page"> · {{ t('viewer.pageNo', { n: page }) }}</template></span>
      </div>

      <input v-model="title" class="te-name" :placeholder="t('tableExtract.defaultTitle')" />

      <p v-if="warnings.length" class="te-warn">
        {{ t('tableExtract.warnings') }}:{{ warnings.join('；') }}
      </p>
      <p class="te-hint">{{ t('tableExtract.hint') }}</p>

      <label v-if="handwriting?.detected" class="te-handwriting">
        <input v-model="includeHandwriting" type="checkbox" />
        <span>
          {{ t('tableExtract.handwritingAsk') }}
          <em v-if="handwriting.note">— {{ handwriting.note }}</em>
          <small>{{ t('tableExtract.handwritingCells', { n: handwriting.cells.length }) }}</small>
        </span>
      </label>

      <div class="te-grid-wrap">
        <table class="te-grid">
          <thead>
            <tr>
              <th>#</th>
              <th v-for="(_, ci) in columns" :key="ci">
                <input v-model="columns[ci]" class="te-head-input" />
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(_, ri) in rows" :key="ri">
              <td class="te-no">{{ ri + 1 }}</td>
              <td v-for="(_, ci) in columns" :key="ci">
                <input
                  v-model="rows[ri][ci]"
                  class="te-cell"
                  :class="{ 'te-hand-cell': isHandwritten(ri, ci) }"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <footer class="te-foot">
        <button class="te-btn" :disabled="saving" @click="emit('close')">
          {{ t('common.cancel') }}
        </button>
        <button class="te-btn primary" :disabled="saving" @click="save">
          {{ saving ? t('tableExtract.saving') : t('tableExtract.save') }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.te-overlay {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(2, 8, 18, 0.66);
  backdrop-filter: blur(3px);
}

.te-panel {
  width: min(880px, calc(100vw - 32px));
  max-height: min(82vh, 720px);
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}

.te-head {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
}

.te-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 12px;
  letter-spacing: 0.08em;
}

.te-close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 15px;
  cursor: pointer;
}

.te-close:hover {
  color: var(--cyan);
}

.te-meta {
  padding: 8px 16px 0;
  color: var(--text-dim);
  font-size: 11px;
}

.te-name {
  margin: 8px 16px 0;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text-hi);
  font-size: 14px;
  padding: 8px 10px;
  outline: none;
}

.te-name:focus {
  border-color: var(--line-bright);
}

.te-warn {
  margin: 8px 16px 0;
  color: #f6c85f;
  font-size: 11.5px;
  line-height: 1.6;
}

.te-hint {
  margin: 8px 16px;
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.6;
}

.te-handwriting {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin: 0 16px 10px;
  padding: 8px 10px;
  border: 1px solid rgba(255, 209, 102, 0.45);
  border-radius: 7px;
  background: color-mix(in srgb, #ffd166 9%, transparent);
  color: var(--text);
  font-size: 12px;
  line-height: 1.55;
  cursor: pointer;
}

.te-handwriting input {
  margin-top: 3px;
  accent-color: var(--cyan);
}

.te-handwriting em {
  color: #ffd166;
  font-style: normal;
}

.te-handwriting small {
  display: block;
  color: var(--text-dim);
  font-size: 10.5px;
}

.te-grid-wrap {
  flex: 1;
  min-height: 120px;
  overflow: auto;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}

.te-grid {
  border-collapse: collapse;
  width: max-content;
  min-width: 100%;
}

.te-grid th,
.te-grid td {
  border: 1px solid var(--line);
  padding: 0;
  min-width: 96px;
}

.te-grid th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--bg-panel);
}

.te-no {
  position: sticky;
  left: 0;
  background: var(--bg-panel);
  color: var(--text-dim);
  font-size: 10px;
  text-align: center;
  min-width: 34px;
}

.te-head-input {
  width: 100%;
  box-sizing: border-box;
  border: none;
  background: transparent;
  color: var(--cyan);
  font-size: 12px;
  font-weight: 600;
  padding: 8px 9px;
  outline: none;
}

.te-cell {
  width: 100%;
  box-sizing: border-box;
  border: none;
  background: var(--bg-card);
  color: var(--text);
  font-size: 12px;
  padding: 7px 9px;
  outline: none;
}

.te-cell:focus,
.te-head-input:focus {
  box-shadow: inset 0 0 0 1px var(--line-bright);
}

.te-cell.te-hand-cell {
  background: color-mix(in srgb, #ffd166 13%, var(--bg-card));
  box-shadow: inset 0 0 0 1px rgba(255, 209, 102, 0.35);
}

.te-foot {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 12px 16px;
}

.te-btn {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text-dim);
  padding: 7px 16px;
  font-size: 12.5px;
  cursor: pointer;
}

.te-btn.primary {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
}

.te-btn:disabled {
  opacity: 0.55;
  cursor: wait;
}
</style>
