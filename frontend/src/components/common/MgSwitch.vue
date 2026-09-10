<script setup lang="ts">
/**
 * 开关(拨动式)。学习页的「模型语音」与隐私页的三项授权此前各写了一份
 * 结构和样式,颜色一致但尺寸已经各自长歪(34×18 / 40×22)。
 * 收敛成一个组件,尺寸用 size 表达,不再靠复制。
 */
withDefaults(defineProps<{
  modelValue: boolean
  /** 尺寸:sm = 学习页指令栏(34×18),md = 设置项(40×22) */
  size?: 'sm' | 'md'
  /** 悬停提示(已翻译文案) */
  title?: string
}>(), { size: 'md' })

const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
</script>

<template>
  <button
    type="button"
    class="switch"
    :class="[`switch--${size}`, { on: modelValue }]"
    :title="title"
    :aria-pressed="modelValue"
    @click="emit('update:modelValue', !modelValue)"
  >
    <span class="knob"></span>
  </button>
</template>

<style scoped>
.switch {
  /* 尺寸全部由变量驱动:两档只改这四个值,风格细节不会走样 */
  --sw-w: 40px;
  --sw-h: 22px;
  --sw-knob: 16px;
  --sw-on: 20px;
  width: var(--sw-w);
  height: var(--sw-h);
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.15);
  border: 1px solid var(--line);
  position: relative;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
  transition: all var(--dur-fast) var(--ease-out);
}

.switch--sm {
  --sw-w: 34px;
  --sw-h: 18px;
  --sw-knob: 12px;
  --sw-on: 18px;
}

.switch .knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: var(--sw-knob);
  height: var(--sw-knob);
  border-radius: 50%;
  background: var(--text-dim);
  transition: all var(--dur-fast) var(--ease-out);
}

.switch.on {
  background: rgba(77, 214, 255, 0.25);
  border-color: var(--line-bright);
}

.switch.on .knob {
  left: var(--sw-on);
  background: var(--cyan);
}
</style>
