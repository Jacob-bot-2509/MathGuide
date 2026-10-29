<script setup lang="ts">
/**
 * 生成文档弹窗:
 *   当前对话的问题解答 / 问题归纳选择 / 独立要求。
 * 前两条直接把原问答排版成 PDF/Markdown/Word,不改写解答;
 * 独立要求先检索知识库生成可编辑大纲,再逐节生成;没有依据的章节跳过。
 */
import { computed, nextTick, ref } from 'vue'
import { statusOf } from '@/api/http'
import { downloadBlob } from '@/services/docService'
import {
  exportQaDocument,
  fetchDocQuestions,
  generateDocument,
  renderDocument,
  requestOutline,
  type DocFormat,
  type DocOutline,
  type DocQuestion,
  type StructuredDocument,
} from '@/services/docgenService'
import { settingsState } from '@/stores/settings'
import type { ChatMsg } from '@/stores/sessions'
import type { NotebookEntry } from '@/stores/notebook'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const props = defineProps<{ messages: ChatMsg[]; entries: NotebookEntry[] }>()
const emit = defineEmits<{ close: [] }>()

type Step = 'choose' | 'reading' | 'chat' | 'notebook' | 'custom' | 'outlining' | 'outline' | 'generating' | 'done'

interface SectionDraft {
  heading: string
  points: string
  evidence_ids: string[]
  has_evidence: boolean
}

const en = computed(() => settingsState.language === 'en')
const lang = computed<'zh' | 'en'>(() => (en.value ? 'en' : 'zh'))

const step = ref<Step>('choose')
const error = ref('')
const busy = ref(false)
const panelEl = ref<HTMLElement | null>(null)

const questions = ref<DocQuestion[]>([])
const chatRecent = ref<ChatMsg[]>([])
const selectedChat = ref<number[]>([])
const selectedNotes = ref<number[]>([])

const custom = ref('')
const outline = ref<DocOutline | null>(null)
const outlineTitle = ref('')
const drafts = ref<SectionDraft[]>([])
const generated = ref<StructuredDocument | null>(null)
const gaps = ref<string[]>([])
const format = ref<DocFormat>('pdf')

const chatSelectedCount = computed(() => selectedChat.value.length)
const noteSelectedCount = computed(() => selectedNotes.value.length)
const canGenerateOutline = computed(() => drafts.value.some((item) => item.has_evidence))

function focusPanel(): void {
  nextTick(() => panelEl.value?.focus())
}

function close(): void {
  if (!busy.value) emit('close')
}

function clearError(): void {
  error.value = ''
}

function errorText(err: unknown, fallback: string): string {
  if (statusOf(err) === 422) return t('doc.noEvidence')
  if (statusOf(err) === 503) return t('doc.retrievalFailed')
  return fallback
}

function startChat(): void {
  clearError()
  chatRecent.value = props.messages.slice(-80)
  step.value = 'reading'
  focusPanel()
  void (async () => {
    try {
      questions.value = await fetchDocQuestions(chatRecent.value, lang.value)
      selectedChat.value = []
      step.value = 'chat'
    } catch (err) {
      error.value = errorText(err, t('doc.failed'))
      step.value = 'choose'
    }
    focusPanel()
  })()
}

function startNotebook(): void {
  clearError()
  selectedNotes.value = []
  step.value = 'notebook'
  focusPanel()
}

function startCustom(): void {
  clearError()
  step.value = 'custom'
  focusPanel()
}

function toggle(list: number[], id: number): number[] {
  return list.includes(id) ? list.filter((item) => item !== id) : [...list, id]
}

function toggleChat(id: number): void {
  selectedChat.value = toggle(selectedChat.value, id)
}

function toggleNote(id: number): void {
  selectedNotes.value = toggle(selectedNotes.value, id)
}

function selectAllChat(): void {
  selectedChat.value = questions.value.filter((item) => item.has_answer).map((item) => item.id)
}

function clearChat(): void {
  selectedChat.value = []
}

function selectAllNotes(): void {
  selectedNotes.value = props.entries.map((entry) => entry.id)
}

function clearNotes(): void {
  selectedNotes.value = []
}

function answerAt(index: number): string {
  for (let i = index + 1; i < chatRecent.value.length; i += 1) {
    const message = chatRecent.value[i]
    if (message.role === 'user') break
    if (message.role === 'assistant' && message.content.trim()) return message.content
  }
  return ''
}

function chatItems() {
  return selectedChat.value
    .map((id) => {
      const question = questions.value.find((item) => item.id === id)
      if (!question) return null
      const answer = answerAt(id)
      return answer ? { question: question.question, answer } : null
    })
    .filter((item): item is { question: string; answer: string } => !!item)
}

function noteItems() {
  return props.entries
    .filter((entry) => selectedNotes.value.includes(entry.id))
    .map((entry) => ({ question: entry.question, answer: entry.answer }))
}

async function downloadQa(items: Array<{ question: string; answer: string }>, source: string): Promise<void> {
  if (!items.length) {
    error.value = t('doc.noQuestions')
    return
  }
  if (items.length > 20) {
    error.value = t('doc.tooMany')
    return
  }
  busy.value = true
  step.value = 'generating'
  focusPanel()
  try {
    const result = await exportQaDocument(items, lang.value, format.value, source)
    downloadBlob(result.blob, result.filename)
    step.value = 'done'
    showToast(t('doc.done'))
  } catch (err) {
    error.value = errorText(err, t('doc.failed'))
    step.value = source === t('doc.notebookSource') ? 'notebook' : 'chat'
  } finally {
    busy.value = false
    focusPanel()
  }
}

function generateChat(): void {
  void downloadQa(chatItems(), t('doc.currentChatSource'))
}

function generateNotebook(): void {
  void downloadQa(noteItems(), t('doc.notebookSource'))
}

function outlineCustom(): void {
  const request = custom.value.trim()
  if (!request) {
    error.value = t('doc.customPh')
    return
  }
  clearError()
  step.value = 'outlining'
  busy.value = true
  focusPanel()
  void (async () => {
    try {
      const plan = await requestOutline(request, lang.value)
      outline.value = plan
      outlineTitle.value = plan.title
      drafts.value = plan.sections.map((section) => ({
        heading: section.heading,
        points: section.points.join('\n'),
        evidence_ids: [...section.evidence_ids],
        has_evidence: section.has_evidence,
      }))
      gaps.value = plan.gaps
      step.value = 'outline'
    } catch (err) {
      error.value = errorText(err, t('doc.failed'))
      step.value = 'custom'
    } finally {
      busy.value = false
      focusPanel()
    }
  })()
}

function confirmedOutline(): DocOutline | null {
  if (!outline.value) return null
  return {
    ...outline.value,
    title: outlineTitle.value.trim() || outline.value.title,
    sections: drafts.value
      .map((draft) => ({
        heading: draft.heading.trim(),
        points: draft.points.split('\n').map((line) => line.trim()).filter(Boolean),
        evidence_ids: draft.evidence_ids,
        has_evidence: draft.has_evidence,
      }))
      .filter((section) => section.heading),
  }
}

function confirmOutline(): void {
  const plan = confirmedOutline()
  if (!plan || !plan.sections.length) {
    error.value = t('doc.failed')
    return
  }
  clearError()
  busy.value = true
  step.value = 'generating'
  focusPanel()
  void (async () => {
    try {
      const result = await generateDocument(custom.value.trim(), plan, lang.value)
      generated.value = result.document
      gaps.value = result.gaps
      const file = await renderDocument(result.document, lang.value, format.value)
      downloadBlob(file.blob, file.filename)
      step.value = 'done'
      showToast(t('doc.done'))
    } catch (err) {
      error.value = errorText(err, t('doc.failed'))
      step.value = 'outline'
    } finally {
      busy.value = false
      focusPanel()
    }
  })()
}

function downloadGenerated(): void {
  if (!generated.value) return
  busy.value = true
  void (async () => {
    try {
      const file = await renderDocument(generated.value!, lang.value, format.value)
      downloadBlob(file.blob, file.filename)
      showToast(t('doc.done'))
    } catch (err) {
      error.value = errorText(err, t('doc.failed'))
    } finally {
      busy.value = false
    }
  })()
}

function reset(): void {
  step.value = 'choose'
  error.value = ''
  questions.value = []
  selectedChat.value = []
  selectedNotes.value = []
  custom.value = ''
  outline.value = null
  drafts.value = []
  generated.value = null
  gaps.value = []
  focusPanel()
}

focusPanel()
</script>

<template>
  <Teleport to="body">
    <div class="doc-backdrop" @click.self="close">
      <section
        ref="panelEl"
        class="doc-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="doc-title"
        tabindex="-1"
        @keydown.esc.prevent="close"
      >
        <header class="doc-head">
          <span id="doc-title" class="doc-title">✎ {{ t('doc.title') }}</span>
          <button class="close" :disabled="busy" :aria-label="t('doc.close')" @click="close">✕</button>
        </header>

        <div class="doc-body">
          <template v-if="step === 'choose'">
            <h2 class="prompt">{{ t('doc.pickTitle') }}</h2>
            <button class="choice" @click="startChat">
              <span class="choice-icon">◈</span>
              <span class="choice-text">
                <strong>{{ t('doc.currentChat') }}</strong>
                <small>{{ t('doc.currentChatDesc') }}</small>
              </span>
              <span class="chev">›</span>
            </button>
            <button class="choice" @click="startNotebook">
              <span class="choice-icon">📓</span>
              <span class="choice-text">
                <strong>{{ t('doc.notebook') }}</strong>
                <small>{{ t('doc.notebookDesc') }}</small>
              </span>
              <span class="chev">›</span>
            </button>
            <button class="choice" @click="startCustom">
              <span class="choice-icon">✎</span>
              <span class="choice-text">
                <strong>{{ t('doc.custom') }}</strong>
                <small>{{ t('doc.customDesc') }}</small>
              </span>
              <span class="chev">›</span>
            </button>
            <p v-if="error" class="error">{{ error }}</p>
          </template>

          <div v-else-if="step === 'reading' || step === 'outlining'" class="loading">
            <span class="spinner" aria-hidden="true"></span>
            <p>{{ step === 'reading' ? t('doc.reading') : t('doc.outlining') }}</p>
          </div>

          <template v-else-if="step === 'chat'">
            <div class="step-head">
              <h2 class="prompt">{{ t('doc.pickQuestions') }}</h2>
              <span class="count">{{ t('doc.itemCount', { n: questions.length }) }}</span>
            </div>
            <p v-if="!questions.length" class="empty">{{ t('doc.noQuestions') }}</p>
            <template v-else>
              <div class="bulk">
                <button class="mini" @click="selectAllChat">{{ t('doc.selectAll') }}</button>
                <button class="mini" @click="clearChat">{{ t('doc.clear') }}</button>
                <span class="count">{{ chatSelectedCount }}</span>
              </div>
              <ul class="pick-list">
                <li v-for="question in questions" :key="question.id" class="pick-item">
                  <label :class="{ disabled: !question.has_answer }">
                    <input
                      type="checkbox"
                      :checked="selectedChat.includes(question.id)"
                      :disabled="!question.has_answer"
                      @change="toggleChat(question.id)"
                    />
                    <span class="pick-text">{{ question.question }}</span>
                    <span class="pick-status" :class="{ ok: question.has_answer }">
                      {{ question.has_answer ? t('doc.hasAnswer') : t('doc.noAnswer') }}
                    </span>
                  </label>
                </li>
              </ul>
            </template>
            <p v-if="error" class="error">{{ error }}</p>
            <footer class="doc-foot">
              <button class="btn" @click="reset">{{ t('doc.back') }}</button>
              <span class="format">
                <span class="format-label">{{ t('doc.format') }}</span>
                <button class="fmt" :class="{ on: format === 'pdf' }" @click="format = 'pdf'">PDF</button>
                <button class="fmt" :class="{ on: format === 'md' }" @click="format = 'md'">Markdown</button>
                <button class="fmt" :class="{ on: format === 'docx' }" @click="format = 'docx'">Word</button>
              </span>
              <button class="btn btn--primary" :disabled="!selectedChat.length || busy" @click="generateChat">
                {{ busy ? t('doc.generating') : t('doc.generate') }}
              </button>
            </footer>
          </template>

          <template v-else-if="step === 'notebook'">
            <div class="step-head">
              <h2 class="prompt">{{ t('doc.notebook') }}</h2>
              <span class="count">{{ t('doc.itemCount', { n: entries.length }) }}</span>
            </div>
            <p v-if="!entries.length" class="empty">{{ t('doc.noNotebook') }}</p>
            <template v-else>
              <div class="bulk">
                <button class="mini" @click="selectAllNotes">{{ t('doc.selectAll') }}</button>
                <button class="mini" @click="clearNotes">{{ t('doc.clear') }}</button>
                <span class="count">{{ noteSelectedCount }}</span>
              </div>
              <ul class="pick-list">
                <li v-for="entry in entries" :key="entry.id" class="pick-item">
                  <label>
                    <input
                      type="checkbox"
                      :checked="selectedNotes.includes(entry.id)"
                      @change="toggleNote(entry.id)"
                    />
                    <span class="pick-text">{{ entry.question }}</span>
                  </label>
                </li>
              </ul>
            </template>
            <p v-if="error" class="error">{{ error }}</p>
            <footer class="doc-foot">
              <button class="btn" @click="reset">{{ t('doc.back') }}</button>
              <span class="format">
                <span class="format-label">{{ t('doc.format') }}</span>
                <button class="fmt" :class="{ on: format === 'pdf' }" @click="format = 'pdf'">PDF</button>
                <button class="fmt" :class="{ on: format === 'md' }" @click="format = 'md'">Markdown</button>
                <button class="fmt" :class="{ on: format === 'docx' }" @click="format = 'docx'">Word</button>
              </span>
              <button class="btn btn--primary" :disabled="!selectedNotes.length || busy" @click="generateNotebook">
                {{ busy ? t('doc.generating') : t('doc.generate') }}
              </button>
            </footer>
          </template>

          <template v-else-if="step === 'custom'">
            <h2 class="prompt">{{ t('doc.custom') }}</h2>
            <textarea
              v-model="custom"
              class="custom-input"
              rows="5"
              maxlength="2000"
              :placeholder="t('doc.customPh')"
            ></textarea>
            <p class="note">{{ t('doc.noteEvidence') }}</p>
            <p v-if="error" class="error">{{ error }}</p>
            <footer class="doc-foot">
              <button class="btn" @click="reset">{{ t('doc.back') }}</button>
              <span class="format">
                <span class="format-label">{{ t('doc.format') }}</span>
                <button class="fmt" :class="{ on: format === 'pdf' }" @click="format = 'pdf'">PDF</button>
                <button class="fmt" :class="{ on: format === 'md' }" @click="format = 'md'">Markdown</button>
                <button class="fmt" :class="{ on: format === 'docx' }" @click="format = 'docx'">Word</button>
              </span>
              <button class="btn btn--primary" :disabled="busy || !custom.trim()" @click="outlineCustom">
                {{ busy ? t('doc.outlining') : t('doc.generate') }}
              </button>
            </footer>
          </template>

          <template v-else-if="step === 'outline' && outline">
            <h2 class="prompt">{{ t('doc.outlineTitle') }}</h2>
            <label class="field">
              <span>{{ t('doc.titleLabel') }}</span>
              <input v-model="outlineTitle" class="text-input" maxlength="120" />
            </label>
            <div class="outline-list">
              <div v-for="(draft, index) in drafts" :key="index" class="outline-item">
                <div class="outline-head">
                  <input v-model="draft.heading" class="text-input" maxlength="100" />
                  <span class="coverage" :class="{ ok: draft.has_evidence }">
                    {{ draft.has_evidence ? t('doc.coverage') : t('doc.missingEvidence') }}
                  </span>
                </div>
                <textarea v-model="draft.points" class="points-input" rows="3" :placeholder="t('doc.points')"></textarea>
              </div>
            </div>
            <p v-if="gaps.length" class="gaps">{{ t('doc.gaps') }} {{ gaps.join('、') }}</p>
            <p class="note">{{ t('doc.outlineHint') }}</p>
            <p v-if="error" class="error">{{ error }}</p>
            <footer class="doc-foot">
              <button class="btn" @click="step = 'custom'">{{ t('doc.back') }}</button>
              <span class="format">
                <span class="format-label">{{ t('doc.format') }}</span>
                <button class="fmt" :class="{ on: format === 'pdf' }" @click="format = 'pdf'">PDF</button>
                <button class="fmt" :class="{ on: format === 'md' }" @click="format = 'md'">Markdown</button>
                <button class="fmt" :class="{ on: format === 'docx' }" @click="format = 'docx'">Word</button>
              </span>
              <button class="btn btn--primary" :disabled="busy || !canGenerateOutline" @click="confirmOutline">
                {{ busy ? t('doc.generating') : t('doc.generate') }}
              </button>
            </footer>
          </template>

          <div v-else-if="step === 'generating'" class="loading">
            <span class="spinner" aria-hidden="true"></span>
            <p>{{ t('doc.generating') }}</p>
          </div>

          <template v-else-if="step === 'done'">
            <div class="done-mark">✓</div>
            <h2 class="prompt">{{ t('doc.done') }}</h2>
            <p class="note">{{ t('doc.doneHint') }}</p>
            <p v-if="gaps.length" class="gaps">{{ t('doc.gaps') }} {{ gaps.join('、') }}</p>
            <p v-if="error" class="error">{{ error }}</p>
            <footer class="doc-foot">
              <button class="btn" @click="reset">{{ t('doc.generate') }}</button>
              <span v-if="generated" class="format">
                <span class="format-label">{{ t('doc.format') }}</span>
                <button class="fmt" :class="{ on: format === 'pdf' }" @click="format = 'pdf'">PDF</button>
                <button class="fmt" :class="{ on: format === 'md' }" @click="format = 'md'">Markdown</button>
                <button class="fmt" :class="{ on: format === 'docx' }" @click="format = 'docx'">Word</button>
                <button class="mini" :disabled="busy" @click="downloadGenerated">{{ t('doc.download') }}</button>
              </span>
              <button class="btn btn--primary" @click="close">{{ t('doc.close') }}</button>
            </footer>
          </template>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.doc-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(3, 6, 12, 0.72);
  backdrop-filter: blur(3px);
}

.doc-panel {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: 88vh;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 18px 54px rgba(0, 0, 0, 0.55);
  outline: none;
}

.doc-head {
  display: flex;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--line);
}

.doc-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 12px;
  letter-spacing: 0.08em;
}

.close {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 15px;
}

.close:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.doc-body {
  overflow-y: auto;
  padding: 18px;
}

.prompt {
  margin: 0 0 14px;
  color: var(--text-hi);
  font-size: 16px;
  font-weight: 500;
  line-height: 1.5;
}

.choice {
  display: flex;
  align-items: center;
  gap: 13px;
  width: 100%;
  margin-bottom: 9px;
  padding: 13px 14px;
  text-align: left;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  cursor: pointer;
  transition: border-color var(--dur-fast), background var(--dur-fast);
}

.choice:hover {
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 5%, var(--bg-card));
}

.choice-icon {
  width: 26px;
  color: var(--cyan);
  font-size: 18px;
  text-align: center;
}

.choice-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.choice-text strong {
  color: var(--text-hi);
  font-size: 13.5px;
  font-weight: 500;
}

.choice-text small {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.5;
}

.chev {
  color: var(--text-dim);
  font-size: 18px;
}

.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  padding: 44px 12px;
  color: var(--text-dim);
  font-size: 13px;
}

.spinner {
  width: 26px;
  height: 26px;
  border: 2px solid var(--line);
  border-top-color: var(--cyan);
  border-radius: 50%;
  animation: spin 0.9s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.step-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.step-head .prompt {
  margin-bottom: 10px;
}

.count {
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10.5px;
  margin-left: auto;
}

.bulk {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.mini {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 11px;
  padding: 3px 8px;
}

.mini:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.pick-list {
  max-height: 42vh;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  border: 1px solid var(--line);
  border-radius: 9px;
}

.pick-item {
  border-bottom: 1px solid var(--line);
}

.pick-item:last-child {
  border-bottom: none;
}

.pick-item label {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  cursor: pointer;
  color: var(--text);
  font-size: 12.5px;
}

.pick-item label:hover {
  background: color-mix(in srgb, var(--cyan) 4%, transparent);
}

.pick-item label.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.pick-item input {
  accent-color: var(--cyan);
  flex-shrink: 0;
}

.pick-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.pick-status {
  flex-shrink: 0;
  color: var(--text-dim);
  font-size: 10.5px;
}

.pick-status.ok {
  color: var(--cyan);
}

.empty {
  padding: 26px 8px;
  color: var(--text-dim);
  font-size: 12.5px;
  text-align: center;
}

.custom-input,
.text-input,
.points-input {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--text);
  padding: 9px 11px;
  font: inherit;
  font-size: 12.5px;
  line-height: 1.65;
  outline: none;
}

.custom-input:focus,
.text-input:focus,
.points-input:focus {
  border-color: var(--line-bright);
}

.custom-input {
  min-height: 120px;
  resize: vertical;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-bottom: 12px;
  color: var(--text-dim);
  font-size: 11.5px;
}

.outline-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.outline-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: var(--bg-card);
}

.outline-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.outline-head .text-input {
  flex: 1;
}

.coverage {
  flex-shrink: 0;
  font-size: 10px;
  color: var(--text-dim);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
}

.coverage.ok {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.points-input {
  min-height: 58px;
  resize: vertical;
}

.note,
.gaps {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.6;
  margin: 10px 0 0;
}

.gaps {
  color: var(--danger);
}

.error {
  color: var(--danger);
  font-size: 12px;
  line-height: 1.6;
  margin: 10px 0 0;
}

.doc-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
}

.btn {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
  padding: 7px 13px;
}

.btn:hover:not(:disabled) {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.btn--primary {
  margin-left: auto;
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.format {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10.5px;
}

.format-label {
  margin-right: 2px;
}

.fmt {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: 5px;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10.5px;
  padding: 3px 7px;
}

.fmt.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.doc-foot .btn--primary {
  margin-left: 0;
}

.done-mark {
  width: 46px;
  height: 46px;
  margin: 10px auto 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  box-shadow: var(--glow-cyan);
  font-size: 22px;
}

.done-mark + .prompt {
  text-align: center;
}

.done-mark ~ .note {
  text-align: center;
}

@media (max-width: 560px) {
  .doc-panel {
    max-height: 92vh;
  }

  .doc-body {
    padding: 14px;
  }

  .doc-foot {
    flex-wrap: wrap;
  }

  .format {
    width: 100%;
    margin-left: 0;
    order: 3;
  }
}
</style>
