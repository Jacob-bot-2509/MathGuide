<script setup lang="ts">
/**
 * 科研文献检索(search-first):先检索自己的论文全文,再基于命中片段提问。
 * 检索在服务端完成:BM25 + embedding 混合排序,章节树先筛节点;
 * 命中带论文名、章节与页码,可直接作为提问依据。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'
import {
  deleteResearchDoc,
  listResearchDocs,
  searchResearch,
  uploadResearchDoc,
  type ResearchDoc,
  type ResearchHit,
} from '@/services/researchService'

const router = useRouter()
const docs = ref<ResearchDoc[]>([])
const query = ref('')
const hits = ref<ResearchHit[]>([])
const searched = ref(false)
const loading = ref(false)
const uploading = ref(false)
const uploadEl = ref<HTMLInputElement | null>(null)
const activeDoc = ref('')
const useTree = ref(true)
const mode = ref('')
const elapsed = ref(0)

const hasDocs = computed(() => docs.value.length > 0)

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function loadDocs(): Promise<void> {
  try {
    docs.value = await listResearchDocs()
  } catch {
    /* 未登录/后端不可达时不打断页面,检索时会再报 */
  }
}

function pickFile(): void {
  uploadEl.value?.click()
}

async function onFile(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (uploading.value) return
  uploading.value = true
  try {
    const res = await uploadResearchDoc(file)
    if (res.duplicate) {
      showToast(t('search.duplicate'))
    } else {
      showToast(t('search.uploaded', { n: res.pages ?? 0, c: res.chunks ?? 0 }))
    }
    await loadDocs()
  } catch {
    showToast(t('search.uploadFail'))
  } finally {
    uploading.value = false
  }
}

async function doSearch(): Promise<void> {
  const q = query.value.trim()
  if (!q || loading.value) return
  loading.value = true
  searched.value = true
  try {
    const res = await searchResearch(q, {
      docId: activeDoc.value || undefined,
      tree: useTree.value,
    })
    hits.value = res.hits
    mode.value = res.mode
    elapsed.value = res.elapsed
  } catch {
    hits.value = []
    showToast(t('search.searchFail'))
  } finally {
    loading.value = false
  }
}

async function removeDoc(doc: ResearchDoc): Promise<void> {
  if (!window.confirm(t('search.deleteConfirm'))) return
  try {
    await deleteResearchDoc(doc.id)
    if (activeDoc.value === doc.id) activeDoc.value = ''
    await loadDocs()
  } catch {
    showToast(t('search.deleteFail'))
  }
}

/** 把命中片段作为证据带进科研对话:检索决定材料,模型只组织回答 */
function askFromResults(): void {
  if (!hits.value.length) return
  const evidence = hits.value
    .slice(0, 6)
    .map((h) => `[${h.docName} · ${h.section} · 第 ${h.pageStart}-${h.pageEnd} 页]\n${h.snippet}`)
    .join('\n\n')
    .slice(0, 6000)
  sessionStorage.setItem(
    'mg-research-seed',
    `请只依据以下检索资料回答问题;资料不足时明确说明,不要补充资料以外的内容。\n\n问题:${query.value.trim()}\n\n${evidence}`,
  )
  router.push('/research')
}

onMounted(loadDocs)
</script>

<template>
  <div class="rs">
    <header class="rs-head">
      <button class="back" @click="router.push('/research')">{{ t('search.back') }}</button>
      <div class="title-box">
        <span class="title">{{ t('search.title') }}</span>
        <span class="tech-label sub">MODULE 02 · SEARCH</span>
      </div>
      <div class="head-right">
        <button class="act" :disabled="uploading" @click="pickFile">
          {{ uploading ? t('search.uploading') : t('search.upload') }}
        </button>
        <button class="act ghost" @click="router.push('/research')">{{ t('search.toChat') }}</button>
        <input
          ref="uploadEl"
          type="file"
          hidden
          accept=".pdf,.txt,.md,.markdown,.tex,.csv,.json,text/*,application/pdf"
          @change="onFile"
        />
      </div>
    </header>

    <main class="rs-main">
      <!-- 论文库 -->
      <section class="panel">
        <div class="panel-head">
          <span class="tech-label">{{ t('search.docs') }}</span>
          <span class="count">{{ docs.length }}</span>
          <select v-model="activeDoc" class="doc-filter">
            <option value="">{{ t('search.allDocs') }}</option>
            <option v-for="d in docs" :key="d.id" :value="d.id">{{ d.name }}</option>
          </select>
        </div>
        <p v-if="!hasDocs" class="empty">{{ t('search.noDocs') }}</p>
        <ul v-else class="doc-list">
          <li v-for="d in docs" :key="d.id" class="doc-item">
            <span class="doc-name">{{ d.name }}</span>
            <span class="doc-meta">{{ fmtSize(d.size) }} · {{ d.pages }} 页</span>
            <button class="del" :title="t('search.delete')" @click="removeDoc(d)">✕</button>
          </li>
        </ul>
        <p class="hint">{{ t('search.uploadHint') }}</p>
      </section>

      <!-- 检索区 -->
      <section class="search-box">
        <div class="search-row">
          <input
            v-model="query"
            class="search-input"
            :placeholder="t('search.placeholder')"
            @keydown.enter="doSearch"
          />
          <button class="search-btn" :disabled="loading || !query.trim()" @click="doSearch">
            {{ loading ? t('search.loading') : t('search.button') }}
          </button>
        </div>
        <div class="opts">
          <label class="opt">
            <input v-model="useTree" type="checkbox" />
            {{ t('search.tree') }}
          </label>
          <span v-if="searched && !loading" class="stat">
            {{ t('search.stat', { n: hits.length, mode: mode === 'hybrid' ? t('search.modeHybrid') : t('search.modeBm25'), s: elapsed }) }}
          </span>
        </div>
      </section>

      <!-- 结果 -->
      <section class="results">
        <p v-if="searched && !loading && !hits.length" class="empty">{{ t('search.empty') }}</p>
        <article v-for="(h, i) in hits" :key="h.docId + h.nodeId + i" class="hit">
          <div class="hit-head">
            <span class="hit-idx tech-label">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="hit-doc">{{ h.docName }}</span>
            <span class="hit-page">{{ t('search.page', { a: h.pageStart, b: h.pageEnd }) }}</span>
            <span class="hit-score tech-label">{{ h.score.toFixed(4) }}</span>
          </div>
          <div class="hit-section">{{ h.section }}</div>
          <p class="hit-text">{{ h.snippet }}</p>
        </article>
        <button v-if="hits.length" class="ask-btn" @click="askFromResults">
          {{ t('search.askResults') }}
        </button>
      </section>
    </main>
  </div>
</template>

<style scoped>
.rs {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.rs-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 22px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  backdrop-filter: blur(8px);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.title-box {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title {
  color: var(--text-hi);
  font-size: 15px;
  letter-spacing: 0.06em;
}

.sub {
  font-size: 10px;
}

.head-right {
  margin-left: auto;
  display: flex;
  gap: 10px;
}

.act {
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 7px 16px;
  border-radius: 6px;
  font-size: 12.5px;
  cursor: pointer;
}

.act:disabled {
  opacity: 0.55;
  cursor: wait;
}

.act.ghost {
  background: transparent;
  color: var(--text-dim);
  border-color: var(--line);
}

.rs-main {
  flex: 1;
  width: min(980px, calc(100% - 44px));
  margin: 0 auto;
  padding: 22px 0 48px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel,
.search-box,
.hit {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
}

.panel {
  padding: 14px 16px;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--cyan);
  font-size: 11px;
  letter-spacing: 0.08em;
}

.count {
  font-family: var(--font-tech);
  color: var(--text-dim);
}

.doc-filter {
  margin-left: auto;
  max-width: 45%;
  background: var(--bg-panel);
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 5px 8px;
  font-size: 12px;
}

.doc-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 180px;
  overflow-y: auto;
}

.doc-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 8px;
  border-radius: 6px;
}

.doc-item:hover {
  background: color-mix(in srgb, var(--cyan) 5%, transparent);
}

.doc-name {
  flex: 1;
  min-width: 0;
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-meta {
  color: var(--text-dim);
  font-size: 10.5px;
}

.del {
  background: transparent;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
}

.del:hover {
  color: #ff8a8a;
}

.hint {
  margin: 10px 0 0;
  color: var(--text-dim);
  font-size: 11px;
}

.search-box {
  padding: 14px 16px;
}

.search-row {
  display: flex;
  gap: 10px;
}

.search-input {
  flex: 1;
  background: var(--bg-panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  padding: 11px 14px;
  font-size: 14px;
  outline: none;
}

.search-input:focus {
  border-color: var(--line-bright);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--cyan) 10%, transparent);
}

.search-btn {
  background: color-mix(in srgb, var(--cyan) 12%, transparent);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 0 26px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

.search-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.opts {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
}

.opt {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  font-size: 11.5px;
}

.stat {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 11px;
  font-family: var(--font-tech);
}

.results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.hit {
  padding: 13px 16px;
}

.hit-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hit-idx {
  color: var(--cyan);
  font-size: 10px;
}

.hit-doc {
  color: var(--text-hi);
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hit-page {
  color: var(--text-dim);
  font-size: 10.5px;
}

.hit-score {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 10px;
}

.hit-section {
  margin-top: 4px;
  color: var(--cyan);
  font-size: 11px;
}

.hit-text {
  margin: 7px 0 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.empty {
  color: var(--text-dim);
  font-size: 12.5px;
  line-height: 1.7;
  text-align: center;
  padding: 26px 8px;
}

.ask-btn {
  align-self: flex-start;
  margin-top: 4px;
  background: transparent;
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  border-radius: 999px;
  padding: 7px 18px;
  font-size: 12.5px;
  cursor: pointer;
}

.ask-btn:hover {
  box-shadow: var(--glow-cyan);
}
</style>
