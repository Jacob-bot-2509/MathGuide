<script setup lang="ts">
/**
 * 论文结构侧栏:研究问题/方法/结论/局限 + 思维导图 + 章节树。
 * 数据由后端按 docId + 内容哈希缓存;这里只渲染,不重复调用模型。
 */
import { computed } from 'vue'
import { t } from '@/utils/i18n'
import type { OutlineNode, PaperStructure } from '@/services/researchService'

const props = defineProps<{
  structure: PaperStructure | null
  loading: boolean
  error: string
}>()
const emit = defineEmits<{ refresh: [] }>()

const outlineRows = computed(() => {
  const rows: { title: string; depth: number }[] = []
  function walk(nodes: OutlineNode[], depth: number): void {
    for (const node of nodes) {
      if (rows.length >= 60) return
      rows.push({ title: node.title, depth })
      walk(node.children || [], depth + 1)
    }
  }
  if (props.structure) walk(props.structure.outline || [], 0)
  return rows
})

const question = computed(() => props.structure?.question || '')
</script>

<template>
  <aside class="pi">
    <header class="pi-head">
      <span class="pi-title">{{ t('workspace.structure') }}</span>
      <button
        v-if="structure && !loading"
        class="pi-refresh"
        type="button"
        @click="emit('refresh')"
      >{{ t('workspace.refresh') }}</button>
    </header>

    <div v-if="loading" class="pi-state">
      <span class="pi-spinner"></span>{{ t('workspace.generating') }}
    </div>
    <div v-else-if="error" class="pi-state error">
      <span>{{ error }}</span>
      <button class="pi-retry" type="button" @click="emit('refresh')">
        {{ t('workspace.retry') }}
      </button>
    </div>

    <div v-else-if="structure" class="pi-body">
      <section class="pi-section">
        <h4>{{ t('workspace.question') }}</h4>
        <p v-if="question" class="pi-question">{{ question }}</p>
        <p v-else class="pi-muted">—</p>
      </section>

      <section v-if="structure.methods.length" class="pi-section">
        <h4>{{ t('workspace.methods') }}</h4>
        <ul>
          <li v-for="(item, i) in structure.methods" :key="`m${i}`">{{ item }}</li>
        </ul>
      </section>

      <section v-if="structure.conclusions.length" class="pi-section">
        <h4>{{ t('workspace.conclusions') }}</h4>
        <ul>
          <li v-for="(item, i) in structure.conclusions" :key="`c${i}`">{{ item }}</li>
        </ul>
      </section>

      <section v-if="structure.limitations.length" class="pi-section">
        <h4>{{ t('workspace.limitations') }}</h4>
        <ul>
          <li v-for="(item, i) in structure.limitations" :key="`l${i}`">{{ item }}</li>
        </ul>
      </section>

      <section class="pi-section">
        <h4>{{ t('workspace.mindmap') }}</h4>
        <div class="mm">
          <div class="mm-root">{{ t('workspace.paper') }}</div>
          <div class="mm-branches">
            <div v-if="question" class="mm-branch">
              <span class="mm-label">{{ t('workspace.question') }}</span>
              <span class="mm-leaf">{{ question }}</span>
            </div>
            <div v-if="structure.methods.length" class="mm-branch">
              <span class="mm-label">{{ t('workspace.methods') }}</span>
              <span v-for="(item, i) in structure.methods" :key="`mm${i}`" class="mm-leaf">{{ item }}</span>
            </div>
            <div v-if="structure.conclusions.length" class="mm-branch">
              <span class="mm-label">{{ t('workspace.conclusions') }}</span>
              <span v-for="(item, i) in structure.conclusions" :key="`mc${i}`" class="mm-leaf">{{ item }}</span>
            </div>
            <div v-if="structure.limitations.length" class="mm-branch">
              <span class="mm-label">{{ t('workspace.limitations') }}</span>
              <span v-for="(item, i) in structure.limitations" :key="`ml${i}`" class="mm-leaf">{{ item }}</span>
            </div>
            <div v-if="outlineRows.length" class="mm-branch">
              <span class="mm-label">{{ t('workspace.outline') }}</span>
              <span v-for="(row, i) in outlineRows" :key="`mo${i}`" class="mm-leaf">
                {{ row.title }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <section v-if="outlineRows.length" class="pi-section">
        <h4>{{ t('workspace.outline') }}</h4>
        <div class="pi-outline">
          <div
            v-for="(row, i) in outlineRows"
            :key="`o${i}`"
            class="pi-outline-row"
            :style="{ paddingLeft: `${row.depth * 14}px` }"
          >
            <span class="pi-dot"></span>{{ row.title }}
          </div>
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.pi {
  display: flex;
  flex-direction: column;
  width: min(340px, 32vw);
  min-width: 280px;
  flex: none;
  min-height: 0;
  height: 100%;
  background: var(--bg-panel);
  border-left: 1px solid var(--line);
}

.pi-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 12px;
  border-bottom: 1px solid var(--line);
  flex: none;
}

.pi-title {
  color: var(--cyan);
  font-family: var(--font-tech);
  font-size: 11px;
  letter-spacing: 0.06em;
}

.pi-refresh {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  border-radius: 5px;
  font-size: 10.5px;
  padding: 2px 7px;
  cursor: pointer;
}

.pi-refresh:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.pi-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 12px;
  color: var(--text-dim);
  font-size: 12px;
}

.pi-state.error {
  color: #ff8a8a;
  flex-direction: column;
  align-items: flex-start;
}

.pi-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--line-bright);
  border-top-color: var(--cyan);
  border-radius: 50%;
  animation: pi-spin 0.8s linear infinite;
}

@keyframes pi-spin {
  to { transform: rotate(360deg); }
}

.pi-retry {
  background: transparent;
  border: 1px solid rgba(255, 138, 138, 0.45);
  color: #ff8a8a;
  border-radius: 5px;
  font-size: 11px;
  padding: 3px 8px;
  cursor: pointer;
}

.pi-body {
  overflow-y: auto;
  padding: 10px 12px 18px;
}

.pi-section {
  margin-bottom: 14px;
}

.pi-section h4 {
  margin: 0 0 6px;
  color: var(--text-dim);
  font-family: var(--font-tech);
  font-size: 10px;
  letter-spacing: 0.08em;
  font-weight: normal;
}

.pi-section ul {
  margin: 0;
  padding-left: 16px;
  color: var(--text);
  font-size: 12px;
  line-height: 1.6;
}

.pi-question {
  margin: 0;
  color: var(--text-hi);
  font-size: 12.5px;
  line-height: 1.65;
}

.pi-muted {
  color: var(--text-dim);
  font-size: 12px;
}

.mm {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px;
  background: var(--bg-card);
}

.mm-root {
  display: inline-block;
  padding: 4px 10px;
  border: 1px solid var(--line-bright);
  border-radius: 999px;
  color: var(--cyan);
  font-size: 11.5px;
}

.mm-branches {
  margin: 8px 0 0 12px;
  padding-left: 10px;
  border-left: 1px solid var(--line-bright);
}

.mm-branch {
  position: relative;
  margin: 7px 0;
  padding-left: 10px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mm-branch::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  width: 8px;
  border-top: 1px solid var(--line-bright);
}

.mm-label {
  color: var(--cyan);
  font-size: 10.5px;
  font-family: var(--font-tech);
}

.mm-leaf {
  color: var(--text);
  font-size: 11.5px;
  line-height: 1.5;
}

.pi-outline {
  border-left: 1px solid var(--line);
  padding-left: 8px;
}

.pi-outline-row {
  position: relative;
  padding-top: 3px;
  padding-bottom: 3px;
  color: var(--text);
  font-size: 11.5px;
  line-height: 1.45;
}

.pi-dot {
  display: inline-block;
  width: 4px;
  height: 4px;
  margin-right: 6px;
  border-radius: 50%;
  background: var(--cyan);
  vertical-align: middle;
}
</style>
