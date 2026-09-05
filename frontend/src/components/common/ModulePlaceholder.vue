<script setup lang="ts">
/**
 * 模块占位页:学习辅助 / 科学研究共用的界面壳,
 * 展示模块定位与规划功能,后续迭代替换为真实界面。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { t } from '@/utils/i18n'

const props = defineProps<{
  code: string
  title: string
  icon: string
  accent: string
  description: string
  status: string
  features: string[]
}>()

const router = useRouter()
const accentStyle = computed(() => ({ color: props.accent, borderColor: props.accent }))
</script>

<template>
  <div class="ph">
    <header class="ph-nav">
      <button class="back" @click="router.push('/home')">{{ t('common.backHome') }}</button>
      <span class="tech-label ph-code">{{ code }}</span>
      <span class="badge tech-label">{{ t('common.modelPending') }}</span>
    </header>

    <main class="ph-main">
      <div class="ph-icon" :style="accentStyle">{{ icon }}</div>
      <h1 class="ph-title">{{ title }}</h1>
      <p class="ph-desc">{{ description }}</p>
      <p class="tech-label ph-status">{{ status }}</p>

      <ul class="ph-features">
        <li v-for="f in features" :key="f">
          <span class="f-bullet" :style="{ color: accent }">▸</span>
          <span class="f-text">{{ f }}</span>
          <span class="f-tag tech-label">{{ t('common.planned') }}</span>
        </li>
      </ul>
    </main>

    <footer class="foot tech-label">MG SYSTEM · MODULE UNDER CONSTRUCTION</footer>
  </div>
</template>

<style scoped>
.ph {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.ph-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 30px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-panel);
  backdrop-filter: blur(8px);
}

.back {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  padding: 7px 16px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.back:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.ph-code {
  color: var(--text-dim);
}

.badge {
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 11px;
}

.ph-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  text-align: center;
}

.ph-icon {
  font-family: var(--font-tech);
  font-size: 46px;
  width: 96px;
  height: 96px;
  display: grid;
  place-items: center;
  border: 1px solid;
  border-radius: 50%;
  box-shadow: 0 0 24px color-mix(in srgb, currentColor 35%, transparent);
  animation: mg-pulse 4s ease-in-out infinite;
}

.ph-title {
  margin: 26px 0 10px;
  font-size: 30px;
  color: var(--text-hi);
  letter-spacing: 0.14em;
  font-weight: 600;
}

.ph-desc {
  color: var(--text-dim);
  font-size: 14px;
  margin: 0;
}

.ph-status {
  margin-top: 12px;
  color: var(--violet);
}

.ph-features {
  margin-top: 42px;
  list-style: none;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, minmax(200px, 300px));
  gap: 14px;
  text-align: left;
}

.ph-features li {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 13px 18px;
  transition:
    border-color var(--dur-fast),
    transform var(--dur-fast) var(--ease-out);
}

.ph-features li:hover {
  border-color: var(--line-bright);
  transform: translateY(-3px);
}

.f-text {
  font-size: 14px;
  color: var(--text);
}

.f-tag {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-dim);
}

.foot {
  padding: 20px;
  text-align: center;
  font-size: 11px;
}

@media (max-width: 640px) {
  .ph-features {
    grid-template-columns: 1fr;
  }
}
</style>
