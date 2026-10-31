<script setup lang="ts">
/**
 * 研究档案面板:科研区的项目目标、思路与论文库(替代学习区的问题归纳)。
 * 数据在服务端按用户保存,与文献检索共用同一套项目与论文;
 * 换设备登录仍可见。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import { userState } from '@/stores/user'
import {
  createResearchProject,
  downloadResearchReport,
  importLegacyResearchArchive,
  deleteResearchDoc,
  deleteResearchProject,
  listResearchDocs,
  listResearchProjects,
  updateResearchProject,
  uploadResearchDoc,
  type ResearchDoc,
  type ResearchProject,
  type ResearchStatus,
} from '@/services/researchService'
import {
  listResearchTables,
  type TableSummary,
} from '@/services/researchTableService'

const props = defineProps<{ left?: number; width?: number }>()
const emit = defineEmits<{ close: []; openDoc: [doc: ResearchDoc] }>()
const router = useRouter()

/** 面板宽 640,以触发按钮中心对齐;靠近屏幕边缘时向内收,避免被裁掉。 */
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const panelWidth = computed(() => Math.min(640, viewportWidth.value - 32))
const panelLeft = computed(() => {
  if (props.left === undefined || props.width === undefined) {
    return viewportWidth.value / 2
  }
  const center = props.left + props.width / 2
  const half = panelWidth.value / 2
  const margin = 16
  return Math.min(
    Math.max(center, half + margin),
    viewportWidth.value - half - margin,
  )
})

function onViewportResize(): void {
  viewportWidth.value = window.innerWidth
}

const tab = ref<'goal' | 'files' | 'tables'>('goal')
const fileEl = ref<HTMLInputElement | null>(null)
const projects = ref<ResearchProject[]>([])
const docs = ref<ResearchDoc[]>([])
const tables = ref<TableSummary[]>([])
const tablesLoading = ref(false)
const reportExporting = ref(false)
const activeId = ref<string | null>(null)
const loading = ref(false)
const uploading = ref(false)
type ProjectPatch = Parameters<typeof updateResearchProject>[1]
const pendingPatches = reactive<Record<string, ProjectPatch>>({})
const savingProjects = reactive<Record<string, boolean>>({})
const failedProjects = reactive<Record<string, boolean>>({})
const deletingProjects = reactive<Record<string, boolean>>({})
const legacyAvailable = ref(false)
const legacyImporting = ref(false)
try {
  const owner = localStorage.getItem('mg-research-archive-owner')
  legacyAvailable.value = !!localStorage.getItem('mg-research-archive') && (!owner || owner === userState.info?.accountKey)
} catch { /* storage unavailable */ }

const project = computed(() => projects.value.find((p) => p.id === activeId.value) ?? null)
const files = computed(() =>
  docs.value.filter((d) => !project.value || d.projectId === null || d.projectId === project.value.id),
)

/** 数据表标签:只在切到时拉取,避免打开档案面板就多一次请求 */
async function setTab(next: 'goal' | 'files' | 'tables'): Promise<void> {
  tab.value = next
  if (next === 'tables') await loadTables()
}

async function loadTables(): Promise<void> {
  if (!project.value) {
    tables.value = []
    return
  }
  tablesLoading.value = true
  try {
    tables.value = await listResearchTables(project.value.id)
  } catch {
    tables.value = []
  } finally {
    tablesLoading.value = false
  }
}

function openTable(item: TableSummary): void {
  const query: Record<string, string> = { tableId: item.id }
  if (project.value) query.projectId = project.value.id
  emit('close')
  void router.push({ path: '/research/tables', query })
}

async function exportReport(): Promise<void> {
  if (!project.value || reportExporting.value) return
  reportExporting.value = true
  try {
    await downloadResearchReport(project.value.id)
  } catch {
    showToast(t('archive.exportFail'))
  } finally {
    reportExporting.value = false
  }
}

const statuses: { key: ResearchStatus; label: string }[] = [
  { key: 'exploring', label: 'archive.statusExploring' },
  { key: 'active', label: 'archive.statusActive' },
  { key: 'paused', label: 'archive.statusPaused' },
  { key: 'done', label: 'archive.statusDone' },
]

function fmtDate(ts: number): string {
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [ps, ds] = await Promise.all([listResearchProjects(), listResearchDocs()])
    projects.value = ps.map((serverProject) => {
      const local = projects.value.find((p) => p.id === serverProject.id)
      return local && (savingProjects[serverProject.id] || pendingPatches[serverProject.id])
        ? { ...serverProject, title: local.title, goal: local.goal, approach: local.approach,
            notes: local.notes, status: local.status }
        : serverProject
    })
    docs.value = ds
    if (!activeId.value && ps.length) activeId.value = ps[0].id
    if (tab.value === 'tables') await loadTables()
  } catch {
    /* 未登录/网络失败时保持空白,操作时会再提示 */
  } finally {
    loading.value = false
  }
}

async function onCreate(): Promise<void> {
  try {
    const p = await createResearchProject()
    projects.value.unshift(p)
    activeId.value = p.id
    tab.value = 'goal'
  } catch {
    showToast(t('archive.saveFail'))
  }
}

async function onDelete(): Promise<void> {
  if (!project.value) return
  const id = project.value.id
  if (savingProjects[id] || deletingProjects[id]) return
  if (!window.confirm(t('archive.deleteConfirm'))) return
  deletingProjects[id] = true
  try {
    await deleteResearchProject(id)
    projects.value = projects.value.filter((p) => p.id !== id)
    docs.value = docs.value.map((d) => (d.projectId === id ? { ...d, projectId: null } : d))
    delete pendingPatches[id]
    delete failedProjects[id]
    if (activeId.value === id) activeId.value = projects.value[0]?.id ?? null
    tables.value = tables.value.filter((item) => item.projectId !== id)
    if (tab.value === 'tables') await loadTables()
  } catch {
    showToast(t('archive.saveFail'))
  } finally {
    delete deletingProjects[id]
  }
}

function onPickProject(e: Event): void {
  const value = (e.target as HTMLSelectElement).value
  activeId.value = value || null
  if (tab.value === 'tables') void loadTables()
}

/** 失焦即存:先本地生效,服务端失败再回滚并提示 */
/** 同一项目串行写入,响应只更新本次提交且未被新编辑覆盖的字段。 */
async function savePending(id: string): Promise<void> {
  if (savingProjects[id]) return
  savingProjects[id] = true
  failedProjects[id] = false
  try {
    while (pendingPatches[id]) {
      const patch = pendingPatches[id]
      delete pendingPatches[id]
      try {
        const updated = await updateResearchProject(id, patch)
        const current = projects.value.find((p) => p.id === id)
        if (current) {
          for (const key of Object.keys(patch) as Array<keyof ProjectPatch>) {
            if (!(key in (pendingPatches[id] ?? {}))) {
              Object.assign(current, { [key]: updated[key] })
            }
          }
          current.updatedAt = updated.updatedAt
        }
      } catch {
        pendingPatches[id] = { ...patch, ...pendingPatches[id] }
        failedProjects[id] = true
        showToast(t('archive.saveFail'))
        break
      }
    }
  } finally {
    savingProjects[id] = false
  }
}

function save(patch: ProjectPatch): void {
  if (!project.value) return
  const id = project.value.id
  if (deletingProjects[id]) return
  Object.assign(project.value, patch)
  pendingPatches[id] = { ...pendingPatches[id], ...patch }
  void savePending(id)
}

function onImport(): void {
  fileEl.value?.click()
}

async function onFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || uploading.value) return
  uploading.value = true
  try {
    const res = await uploadResearchDoc(file, project.value?.id)
    showToast(res.duplicate ? t('search.duplicate')
      : t('search.uploaded', { n: res.pages ?? 0, c: res.chunks ?? 0 }))
    docs.value = await listResearchDocs()
  } catch (err) {
    showToast(err instanceof Error && err.message ? err.message : t('search.uploadFail'))
  } finally {
    uploading.value = false
  }
}

async function removeFile(file: ResearchDoc): Promise<void> {
  try {
    await deleteResearchDoc(file.id)
    docs.value = docs.value.filter((d) => d.id !== file.id)
  } catch {
    showToast(t('search.deleteFail'))
  }
}

async function importLegacy(): Promise<void> {
  if (legacyImporting.value || !userState.info?.accountKey) return
  const name = userState.info.nickname || userState.info.accountKey
  if (!window.confirm(t('archive.legacyConfirm', { name }))) return
  legacyImporting.value = true
  try {
    const raw = localStorage.getItem('mg-research-archive')
    if (!raw) throw new Error('Missing archive')
    const result = await importLegacyResearchArchive(JSON.parse(raw))
    showToast(t(result.duplicate ? 'archive.legacyDuplicate' : 'archive.legacySuccess'))
    await load()
  } catch {
    showToast(t('archive.legacyFail'))
  } finally {
    legacyImporting.value = false
  }
}

function hasUnsavedChanges(): boolean {
  return Object.values(savingProjects).some(Boolean) || Object.keys(pendingPatches).length > 0
}

function confirmClose(): boolean {
  return !hasUnsavedChanges() || window.confirm(t('archive.discardUnsaved'))
}

defineExpose({ confirmClose, reload: load })

function warnBeforeUnload(event: BeforeUnloadEvent): void {
  if (!hasUnsavedChanges()) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  window.addEventListener('beforeunload', warnBeforeUnload)
  window.addEventListener('resize', onViewportResize)
  void load()
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', warnBeforeUnload)
  window.removeEventListener('resize', onViewportResize)
})
onBeforeRouteLeave(() => confirmClose())
</script>

<template>
  <div
    class="ra-wrap"
    :style="{ left: `${panelLeft}px` }"
  >
    <section class="ra-panel">
      <header class="panel-head">
        <span class="tech-label panel-title">◫ {{ t('archive.title') }}</span>
        <button class="tab" :class="{ on: tab === 'goal' }" @click="setTab('goal')">
          {{ t('archive.tabGoal') }}
        </button>
        <button class="tab" :class="{ on: tab === 'files' }" @click="setTab('files')">
          {{ t('archive.tabFiles') }}<span v-if="files.length" class="count">{{ files.length }}</span>
        </button>
        <button class="tab" :class="{ on: tab === 'tables' }" @click="setTab('tables')">
          {{ t('archive.tabTables') }}<span v-if="tables.length" class="count">{{ tables.length }}</span>
        </button>
        <button class="close" aria-label="close" @click="emit('close')">✕</button>
      </header>

      <!-- 项目选择条:新建 / 切换 / 删除 -->
      <div class="project-bar">
        <select class="project-select" :value="project?.id ?? ''" @change="onPickProject">
          <option value="">—</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.title }}</option>
        </select>
        <button class="mini" @click="onCreate">{{ t('archive.newProject') }}</button>
        <button v-if="project" class="mini" :disabled="reportExporting" @click="exportReport">
          {{ reportExporting ? t('archive.exportingReport') : t('archive.exportReport') }}
        </button>
        <button v-if="project" class="mini danger" :disabled="savingProjects[project.id] || deletingProjects[project.id]" @click="onDelete">{{ t('archive.deleteProject') }}</button>
      </div>

      <div v-if="legacyAvailable" class="body">
        <p class="hint">{{ t('archive.legacyHint') }}</p>
        <button class="mini" :disabled="legacyImporting || !userState.info?.accountKey" @click="importLegacy">
          {{ t('archive.legacyImport') }}
        </button>
      </div>

      <!-- 目标与思路 -->
      <div v-if="tab === 'goal'" class="body" :inert="!!project && !!deletingProjects[project.id]">
        <p v-if="project && failedProjects[project.id]" class="hint">
          {{ t('archive.pendingSave') }}
          <button class="mini" @click="savePending(project.id)">{{ t('archive.retrySave') }}</button>
        </p>
        <template v-if="project">
          <input
            class="field title-field"
            :value="project.title"
            :placeholder="t('archive.titlePh')"
            @change="save({ title: ($event.target as HTMLInputElement).value })"
          />
          <div class="row">
            <select
              class="field status"
              :value="project.status"
              @change="save({ status: ($event.target as HTMLSelectElement).value as ResearchStatus })"
            >
              <option v-for="s in statuses" :key="s.key" :value="s.key">{{ t(s.label) }}</option>
            </select>
            <span class="updated">{{ t('archive.updated', { d: fmtDate(project.updatedAt) }) }}</span>
          </div>
          <label class="lbl">{{ t('archive.goal') }}</label>
          <textarea
            class="field area"
            :value="project.goal"
            :placeholder="t('archive.goalPh')"
            @change="save({ goal: ($event.target as HTMLTextAreaElement).value })"
          ></textarea>
          <label class="lbl">{{ t('archive.approach') }}</label>
          <textarea
            class="field area"
            :value="project.approach"
            :placeholder="t('archive.approachPh')"
            @change="save({ approach: ($event.target as HTMLTextAreaElement).value })"
          ></textarea>
          <label class="lbl">{{ t('archive.notes') }}</label>
          <textarea
            class="field area"
            :value="project.notes"
            :placeholder="t('archive.notesPh')"
            @change="save({ notes: ($event.target as HTMLTextAreaElement).value })"
          ></textarea>
        </template>
        <p v-else class="empty">{{ loading ? '…' : t('archive.emptyProjects') }}</p>
      </div>

      <!-- 资料库:与服务端论文库同一份数据 -->
      <div v-else-if="tab === 'files'" class="body">
        <div class="files-head">
          <span class="lbl">{{ t('archive.files') }}</span>
          <button class="mini" :disabled="uploading" @click="onImport">
            {{ uploading ? t('search.uploading') : t('archive.addFile') }}
          </button>
          <input
            ref="fileEl"
            type="file"
            hidden
            accept=".pdf,.docx,.epub,.html,.htm,.xml,.rtf,.txt,.md,.markdown,.tex,.csv,.json,text/*,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/epub+zip,application/rtf"
            @change="onFile"
          />
        </div>
        <p class="hint">{{ t('archive.fileHint') }}</p>
        <p v-if="!files.length" class="empty">{{ t('archive.emptyFiles') }}</p>
        <ul v-else class="file-list">
          <li v-for="f in files" :key="f.id" class="file-item">
            <div class="file-main">
              <span class="file-name">{{ f.title || f.name }}</span>
              <span class="file-meta">
                <span v-if="f.projectId === null" class="tag">{{ t('archive.unassigned') }}</span>
                {{ fmtSize(f.size) }} · {{ f.pages }} {{ t('search.pagesUnit') }} · {{ fmtDate(f.createdAt) }}
                <span v-if="f.year"> · {{ f.year }}</span>
                <span v-if="f.doi" class="doi"> · {{ f.doi }}</span>
              </span>
            </div>
            <button class="mini primary" @click="emit('openDoc', f)">{{ t('workspace.continue') }}</button>
            <button class="mini danger" @click="removeFile(f)">{{ t('archive.removeFile') }}</button>
          </li>
        </ul>
      </div>

      <!-- 数据表:与实验数据表页同一份数据,项目内直接跳转 -->
      <div v-else class="body">
        <p v-if="!project" class="empty">{{ t('archive.emptyProjects') }}</p>
        <p v-else-if="tablesLoading" class="empty">…</p>
        <p v-else-if="!tables.length" class="empty">{{ t('archive.emptyTables') }}</p>
        <ul v-else class="file-list">
          <li v-for="item in tables" :key="item.id" class="file-item">
            <div class="file-main">
              <span class="file-name">{{ item.title }}</span>
              <span class="file-meta">
                {{ t('archive.tableMeta', { r: item.rows, c: item.columns }) }}
                · {{ fmtDate(item.updatedAt) }}
              </span>
            </div>
            <button class="mini" @click="openTable(item)">{{ t('archive.openTable') }}</button>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>

<style scoped>
.ra-wrap {
  position: absolute;
  bottom: 100%;
  margin-bottom: 10px;
  z-index: 45;
  width: 0;
}

.ra-panel {
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  width: min(640px, calc(100vw - 32px));
  max-height: min(62vh, calc(100vh - 96px));
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
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

.tab {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12px;
  cursor: pointer;
}

.tab.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.count {
  margin-left: 5px;
  font-family: var(--font-tech);
  font-size: 10px;
}

.close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  padding: 2px 6px;
}

.close:hover {
  color: var(--cyan);
}

.project-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--line);
}

.project-select {
  flex: 1;
  min-width: 0;
  background: var(--bg-card);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 6px 9px;
  font-size: 12.5px;
}

.mini {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 6px;
  padding: 5px 10px;
  font-size: 11.5px;
  cursor: pointer;
}

.mini:hover {
  box-shadow: var(--glow-cyan);
}

.mini.primary {
  color: var(--text-hi);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
}

.mini:disabled {
  opacity: 0.55;
  cursor: wait;
}

.mini.danger {
  color: #ff8a8a;
  border-color: rgba(255, 138, 138, 0.4);
}

.body {
  padding: 12px 16px 16px;
  overflow-y: auto;
}

.lbl {
  display: block;
  margin: 10px 0 5px;
  font-family: var(--font-tech);
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: var(--text-dim);
}

.field {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  font-family: var(--font-ui);
  font-size: 13px;
  padding: 8px 10px;
  outline: none;
}

.field:focus {
  border-color: var(--line-bright);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cyan) 10%, transparent);
}

.title-field {
  font-size: 14px;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.status {
  width: 140px;
}

.updated {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10.5px;
}

.area {
  min-height: 68px;
  max-height: 160px;
  resize: vertical;
  line-height: 1.6;
}

.empty {
  color: var(--text-dim);
  font-size: 12.5px;
  line-height: 1.7;
  text-align: center;
  padding: 28px 8px;
}

.hint {
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.6;
  margin: 6px 0 10px;
}

.files-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.files-head .lbl {
  margin: 0;
}

.files-head .mini {
  margin-left: auto;
}

.file-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
}

.file-main {
  min-width: 0;
  flex: 1;
}

.file-name {
  display: block;
  color: var(--text-hi);
  font-size: 13px;
  word-break: break-all;
}

.file-meta {
  display: block;
  margin-top: 3px;
  color: var(--text-dim);
  font-size: 10.5px;
}

.tag {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  color: var(--cyan);
  font-size: 9.5px;
}

.doi {
  color: var(--text-dim);
  word-break: break-all;
}
</style>
