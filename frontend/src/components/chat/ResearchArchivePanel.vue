<script setup lang="ts">
/**
 * 研究档案面板:科研区的目标、思路与资料库(替代学习区的问题归纳)。
 * - 项目:标题、目标、思路、过程笔记、状态,失焦即存;
 * - 资料:PDF/TXT/Markdown/TeX/CSV/JSON 提取正文后登记,原文件不上传;
 * - 科研区聊天里的附件会自动登记到当前项目。
 * 面板对齐「研究档案」按钮,在按钮上方展开。
 */
import { computed, ref } from 'vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import { extractPdfText, readTextFile, TEXT_FILE_EXT } from '@/utils/fileText'
import {
  FILE_TEXT_MAX,
  activeProject,
  addResearchFile,
  archiveState,
  createProject,
  removeProject,
  removeResearchFile,
  setActiveProject,
  updateProject,
  type ResearchStatus,
} from '@/stores/researchArchive'

const props = defineProps<{ left?: number; width?: number }>()
const emit = defineEmits<{ close: [] }>()

const tab = ref<'goal' | 'files'>('goal')
const fileEl = ref<HTMLInputElement | null>(null)
const project = computed(() => activeProject())

const statuses: { key: ResearchStatus; label: string }[] = [
  { key: 'exploring', label: 'archive.statusExploring' },
  { key: 'active', label: 'archive.statusActive' },
  { key: 'paused', label: 'archive.statusPaused' },
  { key: 'done', label: 'archive.statusDone' },
]

/** 当前项目的资料 + 尚未归属项目的资料(科研聊天未建项目时上传的) */
const files = computed(() =>
  archiveState.files.filter(
    (f) => f.projectId === null || f.projectId === project.value?.id,
  ),
)

function fmtDate(ts: number): string {
  const d = new Date(ts)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function save(patch: Parameters<typeof updateProject>[1]): void {
  if (project.value) updateProject(project.value.id, patch)
}

function onCreate(): void {
  createProject()
  tab.value = 'goal'
}

function onDelete(): void {
  if (!project.value) return
  if (!window.confirm(t('archive.deleteConfirm'))) return
  removeProject(project.value.id)
}

function onPickProject(e: Event): void {
  const value = (e.target as HTMLSelectElement).value
  setActiveProject(value ? Number(value) : null)
}

function onImport(): void {
  fileEl.value?.click()
}

async function onFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  let text = ''
  try {
    if (file.name.toLowerCase().endsWith('.pdf') || file.type === 'application/pdf') {
      text = await extractPdfText(file, FILE_TEXT_MAX)
    } else if (TEXT_FILE_EXT.test(file.name) || file.type.startsWith('text/')) {
      text = await readTextFile(file, FILE_TEXT_MAX)
    }
  } catch {
    showToast(t('archive.importFail'))
    return
  }
  addResearchFile({
    projectId: project.value?.id ?? null,
    name: file.name,
    size: file.size,
    kind: 'file',
    text: text || undefined,
  })
}
</script>

<template>
  <div
    class="ra-wrap"
    :style="{ left: props.left !== undefined && props.width !== undefined ? `${props.left + props.width / 2}px` : '50%' }"
  >
    <section class="ra-panel">
      <header class="panel-head">
        <span class="tech-label panel-title">◫ {{ t('archive.title') }}</span>
        <button class="tab" :class="{ on: tab === 'goal' }" @click="tab = 'goal'">
          {{ t('archive.tabGoal') }}
        </button>
        <button class="tab" :class="{ on: tab === 'files' }" @click="tab = 'files'">
          {{ t('archive.tabFiles') }}<span v-if="files.length" class="count">{{ files.length }}</span>
        </button>
        <button class="close" aria-label="close" @click="emit('close')">✕</button>
      </header>

      <!-- 项目选择条:新建 / 切换 / 删除 -->
      <div class="project-bar">
        <select class="project-select" :value="project?.id ?? ''" @change="onPickProject">
          <option value="">—</option>
          <option v-for="p in archiveState.projects" :key="p.id" :value="p.id">{{ p.title }}</option>
        </select>
        <button class="mini" @click="onCreate">{{ t('archive.newProject') }}</button>
        <button v-if="project" class="mini danger" @click="onDelete">{{ t('archive.deleteProject') }}</button>
      </div>

      <!-- 目标与思路 -->
      <div v-if="tab === 'goal'" class="body">
        <template v-if="project">
          <input
            class="field title-field"
            :value="project.title"
            :placeholder="t('archive.titlePh')"
            @change="save({ title: ($event.target as HTMLInputElement).value })"
          />
          <div class="row">
            <select class="field status" :value="project.status" @change="save({ status: ($event.target as HTMLSelectElement).value as ResearchStatus })">
              <option v-for="s in statuses" :key="s.key" :value="s.key">{{ t(s.label) }}</option>
            </select>
            <span class="updated">{{ t('archive.updated', { d: fmtDate(project.updatedAt) }) }}</span>
          </div>
          <label class="lbl">{{ t('archive.goal') }}</label>
          <textarea class="field area" :value="project.goal" :placeholder="t('archive.goalPh')" @change="save({ goal: ($event.target as HTMLTextAreaElement).value })"></textarea>
          <label class="lbl">{{ t('archive.approach') }}</label>
          <textarea class="field area" :value="project.approach" :placeholder="t('archive.approachPh')" @change="save({ approach: ($event.target as HTMLTextAreaElement).value })"></textarea>
          <label class="lbl">{{ t('archive.notes') }}</label>
          <textarea class="field area" :value="project.notes" :placeholder="t('archive.notesPh')" @change="save({ notes: ($event.target as HTMLTextAreaElement).value })"></textarea>
        </template>
        <p v-else class="empty">{{ t('archive.emptyProjects') }}</p>
      </div>

      <!-- 资料库 -->
      <div v-else class="body">
        <div class="files-head">
          <span class="lbl">{{ t('archive.files') }}</span>
          <button class="mini" @click="onImport">{{ t('archive.addFile') }}</button>
          <input ref="fileEl" type="file" hidden accept=".pdf,.txt,.md,.markdown,.tex,.csv,.json,text/*,application/pdf" @change="onFile" />
        </div>
        <p class="hint">{{ t('archive.fileHint') }}</p>
        <p v-if="!files.length" class="empty">{{ t('archive.emptyFiles') }}</p>
        <ul v-else class="file-list">
          <li v-for="f in files" :key="f.id" class="file-item">
            <div class="file-main">
              <span class="file-name">{{ f.name }}</span>
              <span class="file-meta">
                <span v-if="f.projectId === null" class="tag">{{ t('archive.fromChat') }}</span>
                {{ fmtSize(f.size) }} · {{ fmtDate(f.addedAt) }}
              </span>
              <details v-if="f.text" class="preview">
                <summary>{{ f.text.slice(0, 80) }}{{ f.text.length > 80 ? '…' : '' }}</summary>
                <p>{{ f.text.slice(0, 800) }}{{ f.text.length > 800 ? '…' : '' }}</p>
              </details>
            </div>
            <button class="mini danger" @click="removeResearchFile(f.id)">{{ t('archive.removeFile') }}</button>
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
  max-height: 62vh;
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

.preview {
  margin-top: 6px;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.55;
}

.preview summary {
  cursor: pointer;
  color: var(--text-dim);
  word-break: break-all;
}

.preview p {
  margin: 6px 0 0;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text);
  opacity: 0.8;
}
</style>
