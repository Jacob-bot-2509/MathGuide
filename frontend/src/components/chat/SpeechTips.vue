<script setup lang="ts">
/**
 * 念法速查贴士(语音输入配套):语音输入进行中时,麦克风旁的📓本子按钮打开本面板。
 * 内置中英切换:同一对象的两种语言念法一键对照;公式列用技术字体原样展示。
 */
import { ref } from 'vue'
import { TIP_GROUPS } from '@/utils/speechTips'
import { settingsState } from '@/stores/settings'
import { t } from '@/utils/i18n'

const emit = defineEmits<{ close: [] }>()

const lang = ref<'zh' | 'en'>(settingsState.language === 'en' ? 'en' : 'zh')
</script>

<template>
  <section class="tips-panel">
    <header class="tips-head">
      <span class="tech-label tips-title">📓 {{ t('tips.title') }}</span>
      <div class="lang-switch" :title="t('tips.langHint')">
        <button class="lang-btn" :class="{ on: lang === 'zh' }" @click="lang = 'zh'">中文</button>
        <button class="lang-btn" :class="{ on: lang === 'en' }" @click="lang = 'en'">EN</button>
      </div>
      <button class="close" aria-label="close" @click="emit('close')">✕</button>
    </header>
    <p class="hint">{{ t('tips.hint') }}</p>
    <div class="tips-body">
      <div v-for="g in TIP_GROUPS" :key="g.title[0]" class="tip-group">
        <div class="tip-group-title">{{ lang === 'zh' ? g.title[0] : g.title[1] }}</div>
        <div v-for="(it, i) in g.items" :key="i" class="tip-row">
          <span class="tip-say">{{ lang === 'zh' ? it.zh : it.en }}</span>
          <span class="tip-arrow">→</span>
          <span class="tip-formula">{{ it.formula }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.tips-panel {
  background: var(--bg-panel);
  border-bottom: 1px solid var(--line);
  padding: 12px 22px 14px;
  max-height: 40vh;
  overflow-y: auto;
}

.tips-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 8px;
}

.tips-title {
  color: var(--cyan);
  font-size: 11px;
}

.lang-switch {
  display: inline-flex;
  gap: 4px;
}

.lang-btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  padding: 3px 10px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 11px;
  font-family: var(--font-tech);
  transition: all var(--dur-fast) var(--ease-out);
}

.lang-btn.on {
  color: var(--cyan);
  border-color: var(--line-bright);
  background: color-mix(in srgb, var(--cyan) 10%, transparent);
  box-shadow: var(--glow-cyan);
}

.close {
  margin-left: auto;
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-dim);
  width: 24px;
  height: 24px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
  transition: all var(--dur-fast) var(--ease-out);
}

.close:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

.hint {
  color: var(--text-dim);
  font-size: 11px;
  margin: 0 0 8px;
}

.tips-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tip-group-title {
  font-size: 11px;
  font-family: var(--font-tech);
  color: var(--magenta);
  letter-spacing: 0.08em;
  margin-bottom: 4px;
}

.tip-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12.5px;
  line-height: 1.6;
  transition: background var(--dur-fast);
}

.tip-row:hover {
  background: rgba(96, 165, 250, 0.06);
}

.tip-say {
  flex: 1;
  color: var(--text);
  min-width: 0;
  word-break: break-word;
}

.tip-arrow {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}

.tip-formula {
  flex-shrink: 0;
  font-family: var(--font-tech);
  color: var(--cyan);
  font-size: 14px;
  letter-spacing: 0.02em;
  white-space: nowrap;
}
</style>
