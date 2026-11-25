<script setup lang="ts">
/**
 * 首页:AI for Science 科研总控台(Observatory Command Hub)。
 * 汇总实时掌握度、科研文献库、实验数据表与本机推演档案，提供直达两大工作区与核心科研工具的入口。
 * 所有后端遥测请求均静默并行执行，离线或未配置时优雅降级为占位，不阻断首页交互。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Starfield from '@/components/common/Starfield.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { fetchGraph } from '@/services/graphService'
import { listResearchDocs, type ResearchDoc } from '@/services/researchService'
import { listResearchTables, type TableSummary } from '@/services/researchTableService'
import { notebookStore } from '@/stores/notebook'
import { sessionStore } from '@/stores/sessions'
import { settingsState } from '@/stores/settings'
import { userState } from '@/stores/user'
import { t } from '@/utils/i18n'
import { crossWorkspaceHref, workspaceOfRoute } from '@/utils/workspace'

const router = useRouter()

const graphTotal = ref<number | null>(null)
const graphMastered = ref<number | null>(null)
const graphReviewDue = ref(0)
const docs = ref<ResearchDoc[]>([])
const docsLoaded = ref(false)
const tables = ref<TableSummary[]>([])
const tablesLoaded = ref(false)

const learnNotebook = notebookStore('learn')
const learnSessions = sessionStore('learn')
const researchSessions = sessionStore('research')

const localArchiveCount = computed(() =>
  learnNotebook.state.entries.length
  + learnSessions.state.sessions.filter((s) => s.messages.some((m) => m.role === 'user')).length
  + researchSessions.state.sessions.filter((s) => s.messages.some((m) => m.role === 'user')).length,
)

const masteryPct = computed(() => {
  if (!graphTotal.value || graphMastered.value === null) return ''
  return `${Math.round((graphMastered.value / graphTotal.value) * 100)}%`
})

const recentDoc = computed(() => {
  if (!docs.value.length) return null
  return [...docs.value].sort((a, b) => (b.lastReadAt ?? b.createdAt) - (a.lastReadAt ?? a.createdAt))[0]
})

const recentTable = computed(() => {
  if (!tables.value.length) return null
  return [...tables.value].sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))[0]
})

function zhEn(zh: string, en: string): string {
  return settingsState.language === 'en' ? en : zh
}

const MODULES = [
  {
    cls: 'card-learn',
    icon: '∑',
    tag: 'STUDY STUDIO',
    titleKey: 'home.learnTitle',
    descKey: 'home.learnDesc',
    statusKey: 'home.open',
    route: '/learn',
    chipsZh: ['双模型证明复核', '2D/3D 几何图解', '教材目录切片', '语音数学'],
    chipsEn: ['Dual-Model Proof', '2D/3D Figures', 'Textbook Slices', 'Math Voice'],
    disabled: false,
  },
  {
    cls: 'card-research',
    icon: '∇',
    tag: 'DISCOVERY WORKBENCH',
    titleKey: 'home.researchTitle',
    descKey: 'home.researchDesc',
    statusKey: 'home.open',
    route: '/research',
    chipsZh: ['五学术源溯源', 'PDF 联动高亮', '多子窗演示台', 'OLS 回归'],
    chipsEn: ['5-Source Search', 'Live PDF Sync', 'Multi-Pane Stage', 'OLS Regression'],
    disabled: false,
  },
]

/** 两区聊天页在双域部署下跨子域跳转;单域部署仍走 SPA 路由 */
function hrefFor(path: string): string {
  const ws = workspaceOfRoute(path)
  return ws ? crossWorkspaceHref(ws, path) : path
}

function open(m: (typeof MODULES)[number]) {
  if (m.disabled) return
  const href = hrefFor(m.route)
  if (href !== m.route) {
    window.location.assign(href)
    return
  }
  router.push(m.route)
}

onMounted(() => {
  void Promise.allSettled([
    fetchGraph().then((data) => {
      graphTotal.value = data.nodes.length
      graphMastered.value = data.nodes.filter((n) => n.status === 'mastered').length
      graphReviewDue.value = data.nodes.filter((n) => n.reviewDue).length
    }),
    listResearchDocs().then((list) => {
      docs.value = list
      docsLoaded.value = true
    }),
    listResearchTables().then((list) => {
      tables.value = list
      tablesLoaded.value = true
    }),
  ])
})
</script>

<template>
  <div class="home">
    <Starfield class="home-bg" />

    <header class="nav">
      <div class="brand">
        <span class="brand-mark">MG</span>
        <span class="brand-name">MathGuide</span>
        <span class="brand-sub tech-label">AI FOR SCIENCE</span>
      </div>
      <div class="nav-right">
        <nav class="links">
          <a class="link" :href="hrefFor('/learn')">{{ t('home.learnTitle') }}</a>
          <a class="link" :href="hrefFor('/research')">{{ t('home.researchTitle') }}</a>
          <button type="button" class="link link-btn" @click="router.push('/graph')">{{ t('graph.title') }}</button>
          <button type="button" class="link link-btn" @click="router.push('/research/tables')">{{ t('tables.entry') }}</button>
        </nav>
        <button class="dots" :title="t('common.settings')" @click="router.push('/settings')">···</button>
        <button class="avatar-btn" :title="userState.info?.nickname" @click="router.push('/settings')">
          <UserAvatar :avatar="userState.info?.avatar" :size="30" />
        </button>
      </div>
    </header>

    <main class="hub">
      <!-- 顶部总览:左侧品牌主张 + 右侧实时科研遥测 -->
      <section class="hero-grid">
        <div class="hero-copy">
          <p class="tech-label hero-code">OBSERVATORY · MATHEMATICAL REASONING &amp; DISCOVERY</p>
          <h1 class="hero-title">MathGuide</h1>
          <p class="hero-sub">{{ t('home.heroSub') }}</p>
        </div>

        <div class="telemetry" :aria-label="zhEn('科研工作台概览指标', 'Workbench Telemetry')">
          <button type="button" class="tel-cell" @click="router.push('/graph')">
            <span class="tel-k">{{ zhEn('知识图谱掌握', 'Graph Mastery') }}</span>
            <span class="tel-v">
              {{ graphMastered !== null && graphTotal !== null ? `${graphMastered}/${graphTotal}` : '—' }}
              <em v-if="masteryPct" class="tel-note tel-note--proof">{{ masteryPct }}</em>
            </span>
          </button>
          <button type="button" class="tel-cell" @click="router.push('/research/search')">
            <span class="tel-k">{{ zhEn('科研文献库', 'Paper Corpus') }}</span>
            <span class="tel-v">
              {{ docsLoaded ? docs.length : '—' }}
              <em class="tel-note tel-note--cite">PDF</em>
            </span>
          </button>
          <button type="button" class="tel-cell" @click="router.push('/research/tables')">
            <span class="tel-k">{{ zhEn('实验数据表', 'Data Tables') }}</span>
            <span class="tel-v">
              {{ tablesLoaded ? tables.length : '—' }}
              <em class="tel-note tel-note--primary">AST</em>
            </span>
          </button>
          <button type="button" class="tel-cell" @click="open(MODULES[0])">
            <span class="tel-k">{{ zhEn('本机推演档案', 'Local Sessions') }}</span>
            <span class="tel-v">
              {{ localArchiveCount }}
              <em class="tel-note tel-note--proof">{{ zhEn('已保存', 'Saved') }}</em>
            </span>
          </button>
        </div>
      </section>

      <!-- 核心双工作区入口 -->
      <section class="modules">
        <button
          v-for="m in MODULES"
          :key="m.titleKey"
          class="card"
          :class="[m.cls, { 'card-disabled': m.disabled }]"
          @click="open(m)"
        >
          <div class="card-top">
            <span class="card-icon" aria-hidden="true">{{ m.icon }}</span>
            <span class="card-tag tech-label">{{ m.tag }}</span>
          </div>
          <span class="card-title">{{ t(m.titleKey) }}</span>
          <span class="card-desc">{{ t(m.descKey) }}</span>
          <div class="card-chips">
            <span
              v-for="chip in (settingsState.language === 'en' ? m.chipsEn : m.chipsZh)"
              :key="chip"
              class="card-chip"
            >{{ chip }}</span>
          </div>
          <span class="card-status tech-label">{{ t(m.statusKey) }}</span>
          <span class="card-arrow" aria-hidden="true">→</span>
        </button>
      </section>

      <!-- 下方科研快捷入口与最近进度 -->
      <section class="quick-row">
        <button type="button" class="quick-card" @click="router.push('/graph')">
          <div class="quick-head">
            <span class="quick-dot quick-dot--proof"></span>
            <span class="quick-title">{{ t('graph.title') }}</span>
            <span class="quick-meta tech-label">
              {{ graphReviewDue ? zhEn(`${graphReviewDue} 项待复核`, `${graphReviewDue} due`) : 'DAG' }}
            </span>
          </div>
          <p class="quick-desc">
            {{ zhEn('分层知识点拓扑、先修依赖追踪与艾宾浩斯复习推荐。', 'Layered concept DAG, prerequisite tracing & spaced review.') }}
          </p>
        </button>

        <button type="button" class="quick-card" @click="router.push('/research/tables')">
          <div class="quick-head">
            <span class="quick-dot quick-dot--primary"></span>
            <span class="quick-title">{{ t('tables.entry') }}</span>
            <span class="quick-meta tech-label">OLS · POLY</span>
          </div>
          <p class="quick-desc">
            {{ recentTable
              ? zhEn(`最近编辑：${recentTable.title}`, `Recent: ${recentTable.title}`)
              : zhEn('高精度 Decimal 公式计算、图表绘制与回归建模。', 'Decimal AST formulas, charts & regression modeling.') }}
          </p>
        </button>

        <button type="button" class="quick-card" @click="router.push('/research/search')">
          <div class="quick-head">
            <span class="quick-dot quick-dot--cite"></span>
            <span class="quick-title">{{ t('search.button') }}</span>
            <span class="quick-meta tech-label">
              {{ recentDoc ? `p.${recentDoc.lastPage || 1}/${recentDoc.pages}` : '5 SOURCES' }}
            </span>
          </div>
          <p class="quick-desc">
            {{ recentDoc
              ? zhEn(`继续精读：${recentDoc.title || recentDoc.name}`, `Continue: ${recentDoc.title || recentDoc.name}`)
              : zhEn('本地论文全文索引与 arXiv / zbMATH / OpenAlex 联合检索。', 'Full-text paper library & 5-source academic search.') }}
          </p>
        </button>
      </section>
    </main>

    <footer class="foot tech-label">MATHGUIDE · SCIENTIFIC MATHEMATICS WORKBENCH · v1.31.0</footer>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  /* iPad/手机 Safari 的 100vh 含工具栏区域,dvh 跟随可见视口,横竖屏都适用 */
  min-height: 100dvh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.home-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: calc(16px + env(safe-area-inset-top)) 32px 16px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  backdrop-filter: blur(12px);
  position: relative;
  z-index: 2;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  font-family: var(--font-serif);
  font-weight: 700;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, var(--bg-card));
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 13px;
}

.brand-name {
  font-family: var(--font-serif);
  letter-spacing: 0.03em;
  color: var(--text-hi);
  font-size: 17px;
  font-weight: 600;
}

.brand-sub {
  font-size: 10px;
  padding: 2px 7px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-1);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.links {
  display: flex;
  align-items: center;
  gap: 20px;
}

.link {
  color: var(--text-dim);
  text-decoration: none;
  font-size: 13.5px;
  letter-spacing: 0.02em;
  position: relative;
  padding: 4px 2px;
  transition: color var(--dur-fast);
}

.link-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: var(--font-ui);
}

.link::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -2px;
  height: 1.5px;
  width: 100%;
  background: var(--cyan);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-fast) var(--ease-out);
}

.link:hover {
  color: var(--text-hi);
}

.link:hover::after {
  transform: scaleX(1);
}

.dots {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 4px 11px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 14px;
  letter-spacing: 0.1em;
  transition: all var(--dur-fast) var(--ease-out);
}

.dots:hover {
  color: var(--text-hi);
  border-color: var(--line-bright);
  background: var(--bg-card);
}

.avatar-btn {
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
  transition: transform var(--dur-fast) var(--ease-out);
}

.avatar-btn:hover {
  transform: translateY(-1px);
}

/* ---------- 科研总控台主区 ---------- */
.hub {
  flex: 1;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  padding: 42px 28px 36px;
  display: flex;
  flex-direction: column;
  gap: 26px;
  position: relative;
  z-index: 2;
}

.hero-grid {
  display: grid;
  grid-template-columns: 1.25fr 0.95fr;
  gap: 28px;
  align-items: end;
}

.hero-code {
  margin: 0;
  color: var(--cyan);
}

.hero-title {
  margin: 10px 0 10px;
  font-family: var(--font-serif);
  font-size: clamp(34px, 4.6vw, 52px);
  letter-spacing: -0.02em;
  font-weight: 500;
  line-height: 1.12;
  color: var(--text-hi);
}

.hero-sub {
  color: var(--text-dim);
  font-size: 14.5px;
  line-height: 1.72;
  max-width: 54ch;
  margin: 0;
}

.telemetry {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--bg-card);
  box-shadow: var(--shadow-sm);
}

.tel-cell {
  min-width: 0;
  text-align: left;
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 11px 13px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: border-color var(--dur-fast), transform var(--dur-fast);
}

.tel-cell:hover {
  border-color: var(--line-bright);
  transform: translateY(-1px);
}

.tel-k {
  font-size: 11.5px;
  color: var(--text-dim);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tel-v {
  font-family: var(--font-tech);
  font-size: 19px;
  font-weight: 600;
  color: var(--text-hi);
  font-variant-numeric: tabular-nums;
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 6px;
}

.tel-note {
  font-style: normal;
  font-size: 11px;
  font-weight: 500;
}

.tel-note--proof {
  color: var(--accent-proof);
}

.tel-note--cite {
  color: var(--accent-cite);
}

.tel-note--primary {
  color: var(--accent-primary);
}

/* ---------- 两大核心工作区卡片 ---------- */
.modules {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20px;
}

.card {
  --card-accent: var(--accent-primary);
  position: relative;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
  padding: 26px 26px 22px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 12px;
  font-family: var(--font-ui);
  color: var(--text);
  box-shadow: var(--shadow-sm);
  transition:
    transform var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-fast) var(--ease-out);
}

.card-learn {
  --card-accent: var(--accent-primary);
}

.card-research {
  --card-accent: var(--accent-cite);
}

.card:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--card-accent) 55%, var(--line));
  box-shadow: var(--shadow-md);
}

.card-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.card-icon {
  font-family: var(--font-serif);
  font-size: 24px;
  color: var(--card-accent);
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  background: color-mix(in srgb, var(--card-accent) 10%, var(--surface-1));
  border: 1px solid color-mix(in srgb, var(--card-accent) 28%, var(--line));
  border-radius: 10px;
}

.card-tag {
  font-size: 10px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-1);
}

.card-title {
  font-family: var(--font-serif);
  font-size: 22px;
  font-weight: 500;
  color: var(--text-hi);
}

.card-desc {
  font-size: 13.5px;
  color: var(--text-dim);
  line-height: 1.68;
}

.card-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.card-chip {
  font-size: 11.5px;
  padding: 3px 9px;
  border-radius: 6px;
  background: var(--surface-1);
  border: 1px solid var(--line);
  color: var(--text);
}

.card-status {
  margin-top: 8px;
  color: var(--card-accent);
  font-size: 11px;
}

.card-arrow {
  position: absolute;
  right: 24px;
  bottom: 22px;
  color: var(--card-accent);
  font-size: 18px;
  transition: transform var(--dur-fast) var(--ease-out);
}

.card:hover .card-arrow {
  transform: translateX(5px);
}

.card-disabled {
  opacity: 0.72;
}

.card-disabled:hover {
  transform: none;
  border-color: var(--line);
  box-shadow: var(--shadow-sm);
}

/* ---------- 快捷科研工具与续读行 ---------- */
.quick-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.quick-card {
  min-width: 0;
  text-align: left;
  background: var(--surface-1);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 15px 16px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: border-color var(--dur-fast), background-color var(--dur-fast), transform var(--dur-fast);
}

.quick-card:hover {
  border-color: var(--line-bright);
  background: var(--bg-card);
  transform: translateY(-1px);
}

.quick-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.quick-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex: none;
}

.quick-dot--proof {
  background: var(--accent-proof);
}

.quick-dot--primary {
  background: var(--accent-primary);
}

.quick-dot--cite {
  background: var(--accent-cite);
}

.quick-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--text-hi);
}

.quick-meta {
  margin-left: auto;
  flex: none;
  font-size: 10px;
}

.quick-desc {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.58;
  color: var(--text-dim);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.foot {
  padding: 18px 22px calc(18px + env(safe-area-inset-bottom));
  text-align: center;
  font-size: 10.5px;
  position: relative;
  z-index: 2;
}

@media (max-width: 900px) {
  .hero-grid,
  .modules,
  .quick-row {
    grid-template-columns: 1fr;
  }

  .brand-sub {
    display: none;
  }
}

@media (max-width: 760px) {
  /* 平板竖屏与手机:卡片区已直达所有模块,顶栏隐藏链接组防止换行挤压 */
  .links {
    display: none;
  }
}

@media (max-width: 600px) {
  .nav {
    padding: calc(12px + env(safe-area-inset-top)) 16px 12px;
  }

  .brand-name {
    font-size: 15px;
  }

  .nav-right {
    gap: 10px;
  }

  .hub {
    padding: 20px 14px 22px;
    gap: 16px;
  }

  .hero-title {
    font-size: clamp(28px, 9vw, 34px);
  }

  .hero-sub {
    font-size: 13px;
  }

  .telemetry {
    padding: 10px;
    gap: 8px;
  }

  .tel-cell {
    padding: 9px 10px;
  }

  .tel-v {
    font-size: 16px;
  }

  .card {
    padding: 18px 16px 20px;
  }

  .card-title {
    font-size: 19px;
  }

  .card-chip {
    font-size: 11px;
    padding: 2px 7px;
  }
}
</style>
