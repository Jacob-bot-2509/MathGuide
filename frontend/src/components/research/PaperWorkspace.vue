<script setup lang="ts">
/**
 * 论文工作台:左对话、右阅读器,第三栏按需展开论文结构与思维导图。
 * 对话只在本篇论文内检索;关闭后聊天记录丢弃,页码与批注保留。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import { usePaperChat } from '@/composables/usePaperChat'
import MathText from '@/components/chat/MathText.vue'
import DocumentViewer from '@/components/research/DocumentViewer.vue'
import PaperInsights from '@/components/research/PaperInsights.vue'
import { type ChatStreamHandle } from '@/services/chatService'
import {
  generateResearchDocInsights,
  getResearchDocInsights,
  listResearchDocs,
  locatePaperPassages,
  saveReadingProgress,
  type PaperAction,
  type PaperStructure,
  type ResearchDoc,
} from '@/services/researchService'

const props = defineProps<{ docId: string }>()
const emit = defineEmits<{ close: [] }>()

const docs = ref<ResearchDoc[]>([])
const currentId = ref(props.docId)
const loadingDocs = ref(true)
const viewerRef = ref<{
  requestClose: () => void
  flushPending: () => Promise<boolean>
  hasPending: () => boolean
  showPassages: (items: { page: number; quote: string }[]) => Promise<void>
  applyPaperActions: (actions: PaperAction[], requestId?: string) => Promise<void>
} | null>(null)

const currentDoc = computed(() => docs.value.find((d) => d.id === currentId.value) ?? null)
const kind = computed<'pdf' | 'text'>(() =>
  currentDoc.value && /\.pdf$/i.test(currentDoc.value.name) ? 'pdf' : 'text')

/** 与主聊天共用动作帧解析;执行仍由本工作台阅读器负责。 */
const paperChat = usePaperChat({
  getTarget: () => currentDoc.value
    ? { docId: currentDoc.value.id, title: currentDoc.value.title || currentDoc.value.name }
    : null,
  applyActions: (target, actions, requestId) => {
    if (target.docId !== currentId.value) return
    return viewerRef.value?.applyPaperActions(actions, requestId)
  },
})

const showInsights = ref(false)
const expanded = ref(false)
const structure = ref<PaperStructure | null>(null)
const insightsLoading = ref(false)
const insightsError = ref('')
const insightCache = new Map<string, PaperStructure>()
let insightsSeq = 0

interface Msg {
  id: number
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
  thinking?: boolean
}
const messages = ref<Msg[]>([])
const input = ref('')
const streaming = ref(false)
const listEl = ref<HTMLElement | null>(null)
let nextMsgId = 1
let streamHandle: ChatStreamHandle | null = null
let progressTimer: ReturnType<typeof setTimeout> | undefined
let closed = false
const lastPage = ref(1)

function scrollBottom(): void {
  void nextTick(() => {
    const el = listEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

function resetChat(): void {
  if (streamHandle) {
    streamHandle.cancel()
    streamHandle = null
  }
  messages.value = []
  input.value = ''
  streaming.value = false
}

function toggleInsights(): void {
  showInsights.value = !showInsights.value
  if (showInsights.value) void loadInsights(currentId.value)
}

async function loadDocs(): Promise<void> {
  loadingDocs.value = true
  try {
    docs.value = await listResearchDocs()
    if (!docs.value.some((d) => d.id === currentId.value) && docs.value.length) {
      currentId.value = docs.value[0].id
    }
  } catch {
    showToast(t('workspace.loadFail'))
  } finally {
    loadingDocs.value = false
  }
}

async function loadInsights(id: string, refresh = false): Promise<void> {
  const seq = ++insightsSeq
  if (!refresh) {
    const cached = insightCache.get(id)
    if (cached) {
      structure.value = cached
      insightsError.value = ''
      insightsLoading.value = false
      return
    }
  }
  structure.value = null
  insightsError.value = ''
  insightsLoading.value = true
  try {
    let data = refresh
      ? await generateResearchDocInsights(id, true)
      : await getResearchDocInsights(id)
    if (!data.cached || !data.structure) {
      data = await generateResearchDocInsights(id, false)
    }
    if (seq !== insightsSeq) return
    if (!data.structure) throw new Error(t('workspace.generateFail'))
    structure.value = data.structure
    insightCache.set(id, data.structure)
  } catch (err) {
    if (seq !== insightsSeq) return
    insightsError.value = err instanceof Error && err.message
      ? err.message : t('workspace.generateFail')
  } finally {
    if (seq === insightsSeq) insightsLoading.value = false
  }
}

async function onPickPaper(e: Event): Promise<void> {
  const select = e.target as HTMLSelectElement
  const next = select.value
  if (!next || next === currentId.value) return
  if (viewerRef.value?.hasPending()) {
    const ok = await viewerRef.value.flushPending()
    if (!ok) {
      select.value = currentId.value
      return
    }
  }
  await flushProgress()
  resetChat()
  currentId.value = next
  const doc = docs.value.find((d) => d.id === next)
  lastPage.value = doc?.lastPage || 1
  if (showInsights.value) void loadInsights(next)
}

function onPageChange(page: number): void {
  lastPage.value = page
  if (currentDoc.value) currentDoc.value.lastPage = page
  if (progressTimer) clearTimeout(progressTimer)
  progressTimer = setTimeout(() => {
    progressTimer = undefined
    saveReadingProgress(currentId.value, page).catch(() => {
      /* 页码保存失败不打断阅读 */
    })
  }, 700)
}

async function flushProgress(): Promise<void> {
  if (progressTimer) {
    clearTimeout(progressTimer)
    progressTimer = undefined
  }
  try {
    await saveReadingProgress(currentId.value, lastPage.value)
  } catch {
    /* 忽略:下次翻页会再存 */
  }
}

function finishClose(): void {
  if (closed) return
  closed = true
  if (streamHandle) {
    streamHandle.cancel()
    streamHandle = null
  }
  void flushProgress()
  insightsSeq += 1
  emit('close')
}

function closeWorkspace(): void {
  // 阅读器有未保存批注时,由它自己弹保存/丢弃确认
  if (viewerRef.value?.hasPending()) {
    viewerRef.value.requestClose()
    return
  }
  finishClose()
}

function onViewerClose(): void {
  finishClose()
}

async function locate(question: string): Promise<void> {
  const docId = currentId.value
  try {
    const res = await locatePaperPassages(docId, question)
    if (docId !== currentId.value) return
    await viewerRef.value?.showPassages(res.passages)
  } catch {
    /* 定位失败不影响回答 */
  }
}

function send(): void {
  const prompt = input.value.trim()
  if (!prompt || streaming.value) return
  input.value = ''
  messages.value.push({ id: nextMsgId++, role: 'user', content: prompt })
  const reply: Msg = {
    id: nextMsgId++, role: 'assistant', content: '', streaming: true, thinking: true,
  }
  messages.value.push(reply)
  const live = messages.value[messages.value.length - 1]
  streaming.value = true
  scrollBottom()
  // 立即定位是本地预览;后端 paper_actions 到达后再以模型结果为准。
  void locate(prompt)

  const history = messages.value
    .filter((m) => m.id !== live.id && m.content)
    .slice(-8)
    .map((m) => ({ role: m.role, content: m.content }))

  let failed = false
  streamHandle = paperChat.stream(prompt, {
    onDelta: (text) => {
      live.thinking = false
      live.content += text
      scrollBottom()
    },
    onDone: (_full, complete) => {
      live.streaming = false
      live.thinking = false
      if (!live.content) live.content = t('workspace.chatFail')
      else if (!complete && !failed) live.content += '\n\n…'
      streaming.value = false
      streamHandle = null
      scrollBottom()
    },
    onError: () => {
      failed = true
      live.thinking = false
      live.streaming = false
      if (!live.content) live.content = t('workspace.chatFail')
      streaming.value = false
      streamHandle = null
      scrollBottom()
    },
  }, {
    workspace: 'research',
    paperId: currentId.value,
    history,
  })
}

function stop(): void {
  if (!streamHandle) return
  streamHandle.cancel()
  streamHandle = null
  streaming.value = false
  const last = messages.value[messages.value.length - 1]
  if (last?.streaming) {
    last.streaming = false
    last.thinking = false
  }
}

onMounted(async () => {
  await loadDocs()
  const doc = currentDoc.value
  if (!doc) return
  lastPage.value = doc.lastPage || 1
})

onBeforeUnmount(() => {
  if (closed) return
  if (streamHandle) {
    streamHandle.cancel()
    streamHandle = null
  }
  insightsSeq += 1
  void flushProgress()
})
</script>

<template>
  <div class="pw" :class="{ expanded }">
    <header class="pw-head">
      <span class="pw-title">{{ t('workspace.title') }}</span>
      <select
        class="pw-select"
        :value="currentId"
        :aria-label="t('workspace.selectPaper')"
        @change="onPickPaper"
      >
        <option v-for="d in docs" :key="d.id" :value="d.id">{{ d.title || d.name }}</option>
      </select>
      <span v-if="currentDoc" class="pw-progress">
        {{ lastPage }} / {{ currentDoc.pages }}
      </span>
      <span class="pw-spacer"></span>
      <button
        class="pw-btn"
        :class="{ on: showInsights }"
        type="button"
        @click="toggleInsights"
      >{{ t('workspace.structureToggle') }}</button>
      <button
        class="pw-btn"
        type="button"
        :title="t('workspace.expand')"
        @click="expanded = !expanded"
      >{{ expanded ? '⤡' : '⤢' }}</button>
      <button class="pw-close" type="button" @click="closeWorkspace">✕</button>
    </header>

    <div class="pw-body" :class="{ 'with-insights': showInsights }">
      <section class="pw-chat">
        <div ref="listEl" class="pw-messages">
          <p v-if="!messages.length" class="pw-empty">{{ t('workspace.chatEmpty') }}</p>
          <div
            v-for="m in messages"
            :key="m.id"
            class="pw-msg"
            :class="m.role"
          >
            <div class="pw-bubble">
              <span v-if="m.thinking" class="pw-thinking">{{ t('workspace.thinking') }}</span>
              <template v-else-if="m.role === 'assistant'">
                <MathText :text="m.content" />
                <span v-if="m.streaming" class="pw-cursor">▍</span>
              </template>
              <template v-else>{{ m.content }}</template>
            </div>
          </div>
        </div>
        <p class="pw-note">{{ t('workspace.chatCleared') }}</p>
        <form class="pw-input" @submit.prevent="send">
          <button
            class="pw-insight-toggle"
            type="button"
            :class="{ on: showInsights }"
            :title="t('workspace.structure')"
            @click="toggleInsights"
          >◫</button>
          <input
            v-model="input"
            :placeholder="t('workspace.chatHint')"
            :disabled="loadingDocs || !currentDoc"
          />
          <button v-if="streaming" class="pw-send stop" type="button" @click="stop">
            {{ t('workspace.stop') }}
          </button>
          <button v-else class="pw-send" type="submit" :disabled="!input.trim()">
            {{ t('workspace.send') }}
          </button>
        </form>
      </section>

      <section class="pw-reader">
        <p v-if="loadingDocs" class="pw-loading">…</p>
        <DocumentViewer
          v-else-if="currentDoc"
          ref="viewerRef"
          :key="currentDoc.id"
          :doc-id="currentDoc.id"
          :title="currentDoc.title || currentDoc.name"
          :kind="kind"
          :start-page="currentDoc.lastPage || 1"
          :project-id="currentDoc.projectId ?? null"
          scroll-mode
          @close="onViewerClose"
          @page-change="onPageChange"
        />
      </section>

      <PaperInsights
        v-if="showInsights"
        :structure="structure"
        :loading="insightsLoading"
        :error="insightsError"
        @refresh="loadInsights(currentId, true)"
      />
    </div>
  </div>
</template>

<style scoped>
.pw {
  position: fixed;
  inset: 64px 22px 22px 22px;
  z-index: 1100;
  display: flex;
  flex-direction: column;
  background: color-mix(in srgb, var(--bg) 78%, transparent);
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(18px) saturate(1.12);
  -webkit-backdrop-filter: blur(18px) saturate(1.12);
  overflow: hidden;
}

.pw.expanded {
  inset: 0;
  border-radius: 0;
}

.pw-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-panel) 74%, transparent);
  flex: none;
}

.pw-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 11px;
  letter-spacing: 0.06em;
  white-space: nowrap;
}

.pw-select {
  min-width: 0;
  max-width: 42%;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--text);
  font-size: 12px;
  padding: 4px 7px;
}

.pw-progress {
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10.5px;
  white-space: nowrap;
}

.pw-spacer {
  flex: 1;
}

.pw-btn,
.pw-close {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 5px;
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
}

.pw-btn:hover,
.pw-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.pw-close {
  border-color: transparent;
  font-size: 14px;
  padding: 1px 7px;
}

.pw-close:hover {
  color: var(--cyan);
}

.pw-body {
  display: flex;
  min-height: 0;
  flex: 1;
}

.pw-chat {
  width: 38%;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg-panel) 70%, transparent);
}

.pw-body.with-insights .pw-chat {
  width: 30%;
}

.pw-messages {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pw-empty,
.pw-loading {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.7;
  padding: 18px 4px;
}

.pw-msg {
  display: flex;
}

.pw-msg.user {
  justify-content: flex-end;
}

.pw-bubble {
  max-width: 92%;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.pw-msg.user .pw-bubble {
  background: color-mix(in srgb, var(--cyan) 12%, var(--bg-card));
  border-color: color-mix(in srgb, var(--cyan) 35%, var(--line));
  color: var(--text-hi);
}

.pw-msg.assistant .pw-bubble {
  white-space: normal;
}

.pw-thinking,
.pw-cursor {
  color: var(--text-dim);
}

.pw-note {
  margin: 0;
  padding: 0 12px 6px;
  color: var(--text-dim);
  font-size: 10px;
  line-height: 1.5;
}

.pw-input {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px 10px;
  border-top: 1px solid var(--line);
  flex: none;
}

.pw-input input {
  flex: 1;
  min-width: 0;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 7px;
  color: var(--text);
  font-size: 12.5px;
  padding: 7px 9px;
  outline: none;
}

.pw-input input:focus {
  border-color: var(--line-bright);
}

.pw-send,
.pw-insight-toggle {
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 6px;
  font-size: 11.5px;
  padding: 6px 10px;
  cursor: pointer;
  white-space: nowrap;
}

.pw-send:disabled {
  opacity: 0.45;
  cursor: default;
}

.pw-send.stop {
  color: #ff8a8a;
  border-color: rgba(255, 138, 138, 0.45);
}

.pw-insight-toggle {
  padding: 6px 8px;
}

.pw-insight-toggle.on {
  box-shadow: var(--glow-cyan);
}

.pw-reader {
  position: relative;
  flex: 1;
  min-width: 0;
}

/* 阅读器与结构栏跟随工作台玻璃底:PDF 页面本身仍是白纸,四周留白透出背景 */
.pw-reader :deep(.viewer) {
  background: transparent;
}

.pw-body :deep(.pi) {
  background: color-mix(in srgb, var(--bg-panel) 72%, transparent);
}

.pw-loading {
  padding: 20px;
}

@media (max-width: 900px) {
  .pw {
    inset: 0;
    border-radius: 0;
  }

  .pw-chat {
    width: 42%;
    min-width: 220px;
  }

  .pw-body.with-insights .pw-chat {
    display: none;
  }
}
</style>
