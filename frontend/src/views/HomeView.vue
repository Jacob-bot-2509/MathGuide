<script setup lang="ts">
/**
 * 首页:两大功能板块入口(学习辅助 / 科学研究)。
 * 科学研究暂未开放,占位展示。
 */
import { useRouter } from 'vue-router'
import Starfield from '@/components/common/Starfield.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { userState } from '@/stores/user'
import { t } from '@/utils/i18n'

const router = useRouter()

const MODULES = [
  {
    cls: 'card-learn',
    icon: '∑',
    titleKey: 'home.learnTitle',
    descKey: 'home.learnDesc',
    statusKey: 'home.open',
    route: '/learn',
    disabled: false,
  },
  {
    cls: 'card-research',
    icon: '∇',
    titleKey: 'home.researchTitle',
    descKey: 'home.researchDesc',
    statusKey: 'home.researchPending',
    route: '/research',
    disabled: true,
  },
]

function open(m: (typeof MODULES)[number]) {
  if (m.disabled) return
  router.push(m.route)
}
</script>

<template>
  <div class="home">
    <Starfield class="home-bg" />

    <header class="nav">
      <div class="brand">
        <span class="brand-mark">MG</span>
        <span class="brand-name">MathGuide</span>
      </div>
      <div class="nav-right">
        <nav class="links">
          <RouterLink class="link" to="/learn">{{ t('home.learnTitle') }}</RouterLink>
          <RouterLink class="link link-pending" to="/research">{{ t('home.researchTitle') }}</RouterLink>
        </nav>
        <button class="dots" :title="t('common.settings')" @click="router.push('/settings')">···</button>
        <button class="avatar-btn" :title="userState.info?.nickname" @click="router.push('/settings')">
          <UserAvatar :avatar="userState.info?.avatar" :size="30" />
        </button>
      </div>
    </header>

    <main class="hero">
      <p class="tech-label hero-code">MG CORE · ONLINE</p>
      <h1 class="hero-title">MATHGUIDE</h1>
      <p class="hero-sub">{{ t('home.heroSub') }}</p>

      <div class="modules">
        <button
          v-for="m in MODULES"
          :key="m.titleKey"
          class="card"
          :class="[m.cls, { 'card-disabled': m.disabled }]"
          @click="open(m)"
        >
          <span class="card-icon" aria-hidden="true">{{ m.icon }}</span>
          <span class="card-title">{{ t(m.titleKey) }}</span>
          <span class="card-desc">{{ t(m.descKey) }}</span>
          <span class="card-status tech-label">{{ t(m.statusKey) }}</span>
          <span class="card-arrow" aria-hidden="true">→</span>
        </button>
      </div>
    </main>

    <footer class="foot tech-label">MG SYSTEM · HIGHER MATHEMATICS ASSISTANT · v0.1.0</footer>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  position: relative;
}

.home-bg {
  position: fixed;
  inset: 0;
  z-index: -1;
  opacity: 0.8;
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 34px;
  position: relative;
  z-index: 2;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  font-family: var(--font-tech);
  font-weight: 700;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 3px 8px;
  border-radius: 4px;
  box-shadow: var(--glow-cyan);
  font-size: 13px;
}

.brand-name {
  font-family: var(--font-tech);
  letter-spacing: 0.18em;
  color: var(--text-hi);
  font-size: 15px;
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 18px;
}

.links {
  display: flex;
  gap: 26px;
}

.dots {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 4px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  letter-spacing: 0.1em;
  transition: all var(--dur-fast) var(--ease-out);
}

.dots:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.avatar-btn {
  background: transparent;
  border: none;
  padding: 0;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.avatar-btn:hover {
  filter: drop-shadow(0 0 8px rgba(77, 214, 255, 0.6));
  transform: translateY(-1px);
}

.link {
  color: var(--text-dim);
  text-decoration: none;
  font-size: 14px;
  letter-spacing: 0.12em;
  position: relative;
  padding: 4px 2px;
  transition: color var(--dur-fast);
}

.link::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -2px;
  height: 1px;
  width: 100%;
  background: var(--cyan);
  transform: scaleX(0);
  transform-origin: left;
  transition: transform var(--dur-med) var(--ease-out);
}

.link:hover {
  color: var(--cyan);
}

.link:hover::after {
  transform: scaleX(1);
}

.link-pending {
  opacity: 0.75;
}

.link-pending::after {
  background: var(--magenta);
}

.link-pending:hover {
  color: var(--magenta);
}

.hero {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8vh 24px 6vh;
  position: relative;
  z-index: 2;
  text-align: center;
}

.hero-code {
  animation: mg-pulse 5s ease-in-out infinite;
}

.hero-title {
  margin: 18px 0 10px;
  font-family: var(--font-tech);
  font-size: clamp(34px, 6vw, 64px);
  letter-spacing: 0.14em;
  font-weight: 600;
  background: linear-gradient(92deg, var(--cyan), var(--violet) 55%, var(--magenta));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 0 34px rgba(77, 214, 255, 0.18);
}

.hero-sub {
  color: var(--text-dim);
  font-size: 15px;
  letter-spacing: 0.1em;
  margin: 0;
}

.modules {
  margin-top: 8vh;
  display: grid;
  grid-template-columns: repeat(2, minmax(240px, 340px));
  gap: 34px;
}

.card {
  --card-accent: var(--cyan);
  --card-glow: var(--glow-cyan);
  position: relative;
  overflow: hidden;
  text-align: left;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 10px;
  align-items: flex-start;
  padding: 30px 30px 26px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 12px;
  font-family: var(--font-ui);
  color: var(--text);
  transition:
    transform var(--dur-med) var(--ease-out),
    border-color var(--dur-med),
    box-shadow var(--dur-med);
}

.card-learn {
  --card-accent: var(--cyan);
  --card-glow: var(--glow-cyan);
}

.card-research {
  --card-accent: var(--magenta);
  --card-glow: var(--glow-magenta);
}

.card:hover {
  transform: translateY(-6px);
  border-color: var(--card-accent);
  box-shadow: var(--card-glow);
}

/* 悬浮扫描光 */
.card::after {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(
    105deg,
    transparent 42%,
    color-mix(in srgb, var(--card-accent) 14%, transparent) 50%,
    transparent 58%
  );
  transform: translateX(-130%);
  transition: transform 0.9s var(--ease-out);
}

.card:hover::after {
  transform: translateX(130%);
}

.card-icon {
  font-family: var(--font-tech);
  font-size: 30px;
  color: var(--card-accent);
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-bright);
  border-radius: 10px;
  margin-bottom: 8px;
  transition:
    box-shadow var(--dur-med),
    transform var(--dur-med);
}

.card:hover .card-icon {
  box-shadow: var(--card-glow);
  transform: scale(1.06);
}

.card-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-hi);
  letter-spacing: 0.06em;
}

.card-desc {
  font-size: 13.5px;
  color: var(--text-dim);
  line-height: 1.7;
}

.card-status {
  margin-top: 10px;
  color: var(--card-accent);
  font-size: 11px;
}

.card-arrow {
  position: absolute;
  right: 24px;
  bottom: 24px;
  color: var(--card-accent);
  font-size: 18px;
  transition: transform var(--dur-fast) var(--ease-out);
}

.card:hover .card-arrow {
  transform: translateX(6px);
}

.card-disabled {
  opacity: 0.72;
}

.card-disabled:hover {
  transform: none;
  border-color: var(--line);
  box-shadow: none;
}

.card-disabled:hover::after {
  transform: translateX(-130%);
}

.card-disabled .card-status {
  color: var(--text-dim);
}

.foot {
  padding: 22px;
  text-align: center;
  font-size: 11px;
  position: relative;
  z-index: 2;
}

@media (max-width: 720px) {
  .modules {
    grid-template-columns: 1fr;
  }
}
</style>
