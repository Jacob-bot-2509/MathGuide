<script setup lang="ts">
/**
 * 关于:功能与改进(反馈)+ 关于 MG(产品信息)。
 */
import { ref } from 'vue'
import SettingsShell from '@/components/common/SettingsShell.vue'
import { t } from '@/utils/i18n'
import { showToast } from '@/utils/toast'

const feedback = ref('')

function submitFeedback() {
  const v = feedback.value.trim()
  if (!v) {
    showToast(t('about.toastEmpty'))
    return
  }
  feedback.value = ''
  showToast(t('about.toastThanks'))
}
</script>

<template>
  <SettingsShell :title="t('about.title')">
    <p class="section tech-label">{{ t('about.feedbackTitle') }}</p>
    <div class="card">
      <textarea
        v-model="feedback"
        class="feedback"
        rows="4"
        :placeholder="t('about.feedbackPh')"
      ></textarea>
      <button class="submit" @click="submitFeedback">{{ t('about.submit') }}</button>
    </div>

    <p class="section tech-label">{{ t('about.aboutTitle') }}</p>
    <div class="card about-card">
      <div class="logo-row">
        <span class="logo-mark">MG</span>
        <div class="logo-text">
          <span class="name">MATHGUIDE</span>
          <span class="ver">v0.1.0 · 演示环境</span>
        </div>
      </div>
      <p class="desc">{{ t('about.desc') }}</p>
      <div class="stack">
        <span class="stack-chip">Vue 3</span>
        <span class="stack-chip">TypeScript</span>
        <span class="stack-chip">GSAP</span>
        <span class="stack-chip">KaTeX</span>
        <span class="stack-chip">MathJax</span>
      </div>
      <p class="copyright">EST. 2026 · MG SYSTEM · HIGHER MATHEMATICS ASSISTANT</p>
    </div>
  </SettingsShell>
</template>

<style scoped>
.card {
  background: var(--bg-card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 16px 18px;
}

.feedback {
  width: 100%;
  resize: vertical;
  min-height: 96px;
  background: var(--bg-void);
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  padding: 10px 14px;
  font-size: 13.5px;
  font-family: var(--font-ui);
  outline: none;
  transition: border-color var(--dur-fast);
}

.feedback:focus {
  border-color: var(--line-bright);
}

.feedback::placeholder {
  color: var(--text-dim);
}

.submit {
  margin-top: 12px;
  background: rgba(77, 214, 255, 0.1);
  border: 1px solid var(--line-bright);
  color: var(--cyan);
  padding: 8px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  transition: all var(--dur-fast) var(--ease-out);
}

.submit:hover {
  background: rgba(77, 214, 255, 0.18);
  box-shadow: var(--glow-cyan);
}

.about-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.logo-row {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-mark {
  font-family: var(--font-tech);
  font-weight: 700;
  color: var(--cyan);
  border: 1px solid var(--line-bright);
  padding: 4px 10px;
  border-radius: 6px;
  box-shadow: var(--glow-cyan);
  font-size: 16px;
}

.logo-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.name {
  font-family: var(--font-tech);
  letter-spacing: 0.18em;
  color: var(--text-hi);
  font-size: 15px;
}

.ver {
  color: var(--text-dim);
  font-size: 11px;
}

.desc {
  color: var(--text);
  font-size: 13px;
  line-height: 1.8;
  margin: 0;
}

.stack {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.stack-chip {
  font-family: var(--font-tech);
  font-size: 11px;
  color: var(--cyan);
  border: 1px solid var(--line);
  padding: 3px 10px;
  border-radius: 999px;
}

.copyright {
  color: var(--text-dim);
  font-size: 10.5px;
  letter-spacing: 0.08em;
  margin: 4px 0 0;
}
</style>
