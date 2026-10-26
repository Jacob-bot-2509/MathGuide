<script setup lang="ts">
/**
 * 服务协议 / 隐私政策:同一页面两个标签,正文来自 utils/aboutContent。
 * 从「关于 MG」或登录页可直接带 ?tab=privacy 打开隐私政策。
 */
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { settingsState } from '@/stores/settings'
import { APP_ISSUES_URL, PRIVACY, TERMS, type Bi } from '@/utils/aboutContent'
import { t } from '@/utils/i18n'

const route = useRoute()
const router = useRouter()
const en = computed(() => settingsState.language === 'en')
const tr = (value: Bi): string => (en.value ? value.en : value.zh)

const tab = ref<'terms' | 'privacy'>(route.query.tab === 'privacy' ? 'privacy' : 'terms')
const doc = computed(() => (tab.value === 'privacy' ? PRIVACY : TERMS))

watch(
  () => route.query.tab,
  (value) => {
    tab.value = value === 'privacy' ? 'privacy' : 'terms'
  },
)

function selectTab(next: 'terms' | 'privacy') {
  if (tab.value === next) return
  tab.value = next
  router.replace({ path: '/settings/terms', query: next === 'privacy' ? { tab: 'privacy' } : {} })
}
</script>

<template>
  <SettingsShell :title="t('terms.title')" :width="680">
    <div class="doc-head">
      <div class="tabs" role="tablist" :aria-label="t('terms.title')">
        <button
          id="terms-tab"
          class="tab"
          :class="{ on: tab === 'terms' }"
          role="tab"
          :aria-selected="tab === 'terms'"
          aria-controls="terms-panel"
          @click="selectTab('terms')"
        >{{ t('terms.tabTerms') }}</button>
        <button
          id="privacy-tab"
          class="tab"
          :class="{ on: tab === 'privacy' }"
          role="tab"
          :aria-selected="tab === 'privacy'"
          aria-controls="terms-panel"
          @click="selectTab('privacy')"
        >{{ t('terms.tabPrivacy') }}</button>
      </div>
      <span class="updated">{{ t('terms.updated') }} {{ doc.updated }}</span>
    </div>

    <div id="terms-panel" class="doc-body" role="tabpanel" :aria-labelledby="`${tab}-tab`">
      <p class="intro">{{ tr(doc.intro) }}</p>

      <section v-for="(section, index) in doc.sections" :key="index" class="legal-section">
        <h2>
          <span class="num" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
          <span>{{ tr(section.title) }}</span>
        </h2>
        <p v-for="(paragraph, pIndex) in section.paragraphs" :key="`p-${pIndex}`">
          {{ tr(paragraph) }}
        </p>
        <ul v-if="section.bullets">
          <li v-for="(bullet, bIndex) in section.bullets" :key="`b-${bIndex}`">
            {{ tr(bullet) }}
          </li>
        </ul>
      </section>

      <div class="contact">
        <p>{{ t('terms.contact') }}</p>
        <a :href="APP_ISSUES_URL" target="_blank" rel="noopener noreferrer">
          {{ t('terms.contactBtn') }} <span aria-hidden="true">↗</span>
        </a>
      </div>

      <p class="note">{{ t('terms.note') }}</p>
    </div>
  </SettingsShell>
</template>

<style scoped>
.doc-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 18px;
}

.tabs {
  display: flex;
  gap: 18px;
}

.tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-dim);
  padding: 8px 2px 9px;
  cursor: pointer;
  font-size: 13px;
  transition: color var(--dur-fast) var(--ease-out);
}

.tab:hover {
  color: var(--text);
}

.tab.on {
  color: var(--cyan);
  border-bottom-color: var(--cyan);
}

.tab:focus-visible {
  outline: 1px solid var(--line-bright);
  outline-offset: 2px;
}

.updated {
  font-family: var(--font-tech);
  color: var(--text-dim);
  font-size: 10.5px;
  padding-bottom: 10px;
  flex-shrink: 0;
}

.doc-body {
  max-width: 68ch;
}

.intro {
  margin: 0 0 22px;
  color: var(--text);
  font-size: 13px;
  line-height: 1.85;
}

.legal-section {
  margin-bottom: 22px;
}

.legal-section h2 {
  display: flex;
  align-items: baseline;
  gap: 9px;
  margin: 0 0 8px;
  color: var(--text-hi);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.5;
}

.num {
  font-family: var(--font-tech);
  color: var(--cyan);
  font-size: 10.5px;
  flex-shrink: 0;
}

.legal-section p {
  margin: 0 0 8px;
  color: var(--text);
  font-size: 12.8px;
  line-height: 1.85;
}

.legal-section ul {
  margin: 6px 0 0;
  padding-left: 18px;
  color: var(--text);
  font-size: 12.8px;
  line-height: 1.85;
}

.legal-section li + li {
  margin-top: 4px;
}

.legal-section li::marker {
  color: var(--text-dim);
}

.contact {
  margin-top: 26px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--bg-card);
}

.contact p {
  margin: 0 0 6px;
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.7;
}

.contact a {
  color: var(--cyan);
  font-size: 12.5px;
  text-decoration: none;
}

.contact a:hover {
  text-shadow: 0 0 10px rgba(77, 214, 255, 0.5);
}

.note {
  margin: 18px 0 0;
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.7;
}

@media (max-width: 560px) {
  .doc-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .updated {
    padding-bottom: 8px;
  }
}
</style>
