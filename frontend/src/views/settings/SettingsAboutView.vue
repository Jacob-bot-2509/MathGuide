<script setup lang="ts">
/**
 * 关于 MG:产品身份、用途、版本更新、服务协议与隐私入口。
 * 版本与协议正文来自 utils/aboutContent,页面不写死版本号。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { settingsState } from '@/stores/settings'
import {
  APP_STABLE_DATE,
  APP_STABLE_VERSION,
  APP_VERSION,
  OPEN_SOURCE,
  PURPOSES,
  RELEASES,
  type Bi,
} from '@/utils/aboutContent'
import { t } from '@/utils/i18n'

const router = useRouter()
const en = computed(() => settingsState.language === 'en')
const tr = (value: Bi): string => (en.value ? value.en : value.zh)
const currentRelease = RELEASES.find((release) => release.version === APP_VERSION) ?? RELEASES[0]
</script>

<template>
  <SettingsShell :title="t('about.title')" :width="620">
    <section class="hero">
      <div class="hero-head">
        <span class="logo-mark">MG</span>
        <div class="identity">
          <p class="product-name">MATHGUIDE</p>
          <p class="tagline">{{ t('about.tagline') }}</p>
        </div>
        <div class="version-block">
          <span class="version-label">{{ t('about.version') }}</span>
          <span class="version-value">{{ APP_VERSION }}</span>
        </div>
      </div>
      <p class="desc">{{ t('about.desc') }}</p>
      <div class="hero-foot">
        <span>{{ t('about.stable') }} <b>{{ APP_STABLE_VERSION }}</b></span>
        <span class="sep">/</span>
        <span>{{ t('about.released') }} <b>{{ APP_STABLE_DATE }}</b></span>
        <span class="env">{{ t('about.demo') }}</span>
      </div>
    </section>

    <p class="section tech-label">{{ t('about.purposeTitle') }}</p>
    <div class="purpose-list">
      <div v-for="item in PURPOSES" :key="item.glyph" class="purpose">
        <span class="purpose-glyph" aria-hidden="true">{{ item.glyph }}</span>
        <div class="purpose-text">
          <span class="purpose-title">{{ tr(item.title) }}</span>
          <span class="purpose-desc">{{ tr(item.desc) }}</span>
        </div>
      </div>
    </div>

    <p class="section tech-label">{{ t('about.updatesTitle') }}</p>
    <div class="timeline">
      <article v-if="currentRelease" class="release release--current">
        <div class="release-head">
          <span class="release-version">{{ currentRelease.version }}</span>
          <span v-if="currentRelease.status === 'dev'" class="badge badge--dev">{{ t('about.devBadge') }}</span>
          <span v-else-if="currentRelease.status === 'latest'" class="badge">{{ t('about.latestBadge') }}</span>
          <span v-if="currentRelease.date" class="release-date">{{ currentRelease.date }}</span>
        </div>
        <ul class="release-items">
          <li v-for="(item, index) in currentRelease.items" :key="index">{{ tr(item) }}</li>
        </ul>
      </article>
    </div>

    <p class="section tech-label">{{ t('about.legalTitle') }}</p>
    <p class="legal-summary">{{ t('about.legalSummary') }}</p>
    <div class="link-list">
      <button class="link-row" @click="router.push('/settings/terms')">
        <span class="link-text">
          <span class="link-title">{{ t('about.terms') }}</span>
          <span class="link-desc">{{ t('about.termsDesc') }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <button
        class="link-row"
        @click="router.push({ path: '/settings/terms', query: { tab: 'privacy' } })"
      >
        <span class="link-text">
          <span class="link-title">{{ t('about.privacyPolicy') }}</span>
          <span class="link-desc">{{ t('about.privacyPolicyDesc') }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <button class="link-row" @click="router.push('/settings/privacy')">
        <span class="link-text">
          <span class="link-title">{{ t('about.privacySettings') }}</span>
          <span class="link-desc">{{ t('about.privacySettingsDesc') }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <button class="link-row" @click="router.push('/settings/feedback')">
        <span class="link-text">
          <span class="link-title">{{ t('about.feedback') }}</span>
          <span class="link-desc">{{ t('about.feedbackDesc') }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
    </div>

    <p class="section tech-label">{{ t('about.openSourceTitle') }}</p>
    <p class="open-source-desc">{{ t('about.openSourceDesc') }}</p>
    <div class="stack">
      <span v-for="item in OPEN_SOURCE" :key="item.name" class="stack-chip">
        {{ item.name }} <em>{{ item.license }}</em>
      </span>
    </div>

    <p class="copyright">{{ t('about.copyright') }}</p>
  </SettingsShell>
</template>

<style scoped>
.hero {
  position: relative;
  padding: 20px 22px 18px;
  border: 1px solid var(--line);
  border-left: 2px solid var(--cyan);
  border-radius: 10px;
  background:
    linear-gradient(120deg, color-mix(in srgb, var(--cyan) 7%, transparent), transparent 58%),
    var(--bg-card);
  overflow: hidden;
}

.hero::after {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(var(--line) 1px, transparent 1px),
    linear-gradient(90deg, var(--line) 1px, transparent 1px);
  background-size: 32px 32px;
  opacity: 0.18;
  mask-image: linear-gradient(115deg, transparent 35%, #000 100%);
  pointer-events: none;
}

.hero > * {
  position: relative;
  z-index: 1;
}

.hero-head {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-mark {
  font-family: var(--font-tech);
  font-weight: 700;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 8px 13px;
  border-radius: 7px;
  box-shadow: var(--glow-cyan);
  font-size: 20px;
  letter-spacing: 0.04em;
  flex-shrink: 0;
}

.identity {
  min-width: 0;
}

.product-name {
  margin: 0;
  font-family: var(--font-tech);
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 0.2em;
  color: var(--text-hi);
}

.tagline {
  margin: 4px 0 0;
  color: var(--text-dim);
  font-size: 11.5px;
  letter-spacing: 0.04em;
}

.version-block {
  margin-left: auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  flex-shrink: 0;
}

.version-label {
  color: var(--text-dim);
  font-size: 10.5px;
}

.version-value {
  font-family: var(--font-tech);
  color: var(--cyan);
  font-size: 13px;
}

.desc {
  margin: 16px 0 0;
  color: var(--text);
  font-size: 13px;
  line-height: 1.8;
}

.hero-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 8px;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--line);
  color: var(--text-dim);
  font-size: 11px;
}

.hero-foot b {
  font-family: var(--font-tech);
  font-weight: 500;
  color: var(--text);
}

.sep {
  opacity: 0.5;
}

.env {
  margin-left: auto;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 9px;
  font-size: 10.5px;
  color: var(--text-dim);
}

.purpose-list {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
  overflow: hidden;
}

.purpose {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}

.purpose:last-child {
  border-bottom: none;
}

.purpose-glyph {
  font-family: var(--font-tech);
  color: var(--cyan);
  font-size: 20px;
  line-height: 1.15;
  width: 28px;
  text-align: center;
  flex-shrink: 0;
}

.purpose-text {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.purpose-title {
  color: var(--text-hi);
  font-size: 13.5px;
}

.purpose-desc {
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.65;
}

.timeline {
  position: relative;
  padding-left: 17px;
}

.timeline::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 7px;
  bottom: 9px;
  width: 1px;
  background: var(--line);
}

.release {
  position: relative;
  padding-bottom: 16px;
}

.release:last-child {
  padding-bottom: 2px;
}

.release::before {
  content: '';
  position: absolute;
  left: -17px;
  top: 5px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1px solid var(--line-bright);
  background: var(--bg-void);
}

.release--current::before {
  background: var(--cyan);
  border-color: var(--cyan);
  box-shadow: var(--glow-cyan);
}

.release-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.release-version {
  font-family: var(--font-tech);
  color: var(--text-hi);
  font-size: 13px;
}

.release--current .release-version {
  color: var(--cyan);
}

.release-date {
  margin-left: auto;
  font-family: var(--font-tech);
  color: var(--text-dim);
  font-size: 10.5px;
}

.badge {
  font-size: 10px;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
  border-radius: 999px;
  padding: 1px 7px;
}

.badge--dev {
  color: var(--violet);
  border-color: color-mix(in srgb, var(--violet) 45%, transparent);
  background: color-mix(in srgb, var(--violet) 8%, transparent);
}

.release-items {
  margin: 6px 0 0;
  padding-left: 17px;
  color: var(--text);
  font-size: 12.5px;
  line-height: 1.7;
}

.release-items li {
  margin-top: 2px;
}

.release-items li::marker {
  color: var(--text-dim);
}

.legal-summary {
  margin: 0 0 10px;
  color: var(--text-dim);
  font-size: 12px;
  line-height: 1.7;
}

.link-list {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--bg-card);
  overflow: hidden;
}

.link-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  padding: 12px 16px;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--line);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out);
}

.link-row:last-child {
  border-bottom: none;
}

.link-row:hover {
  background: color-mix(in srgb, var(--cyan) 5%, transparent);
}

.link-row:focus-visible {
  outline: 1px solid var(--line-bright);
  outline-offset: -1px;
}

.link-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.link-title {
  color: var(--text-hi);
  font-size: 13px;
}

.link-desc {
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.5;
}

.chev {
  color: var(--text-dim);
  font-size: 17px;
  flex-shrink: 0;
}

.link-row:hover .chev {
  color: var(--cyan);
}

.open-source-desc {
  margin: 0 0 9px;
  color: var(--text-dim);
  font-size: 11.5px;
  line-height: 1.65;
}

.stack {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.stack-chip {
  font-family: var(--font-tech);
  font-size: 11px;
  color: var(--text);
  border: 1px solid var(--line);
  padding: 3px 9px;
  border-radius: 999px;
}

.stack-chip em {
  color: var(--text-dim);
  font-style: normal;
  margin-left: 4px;
  font-size: 10px;
}

.copyright {
  color: var(--text-dim);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  margin: 28px 0 0;
  text-align: center;
}

@media (max-width: 560px) {
  .hero {
    padding: 17px 16px 15px;
  }

  .hero-head {
    flex-wrap: wrap;
  }

  .version-block {
    width: 100%;
    align-items: flex-start;
    margin-left: 0;
    margin-top: 4px;
  }

  .env {
    margin-left: 0;
  }

  .release-date {
    margin-left: 0;
    width: 100%;
  }
}
</style>
