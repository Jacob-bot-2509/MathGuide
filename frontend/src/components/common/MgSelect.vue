<script setup lang="ts">
/**
 * 主题化下拉选择器。
 * 所有样式引用主题令牌(边框 / 背景 / 高亮),深浅色自动适配;
 * 今后所有"下拉式选项"统一使用本组件,保证与主题边框一致。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  title?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [value: string] }>()

const open = ref(false)
const rootEl = ref<HTMLDivElement | null>(null)

function onDocClick(e: MouseEvent) {
  if (open.value && rootEl.value && !rootEl.value.contains(e.target as Node)) {
    open.value = false
  }
}

function pick(opt: SelectOption) {
  if (opt.disabled) return
  emit('update:modelValue', opt.value)
  emit('change', opt.value)
  open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="rootEl" class="mg-select" :class="{ open }">
    <button class="trigger" type="button" :title="title" @click="open = !open">
      <span class="value">{{ options.find((o) => o.value === modelValue)?.label ?? modelValue }}</span>
      <span class="chev" :class="{ open }">▾</span>
    </button>
    <Transition name="drop">
      <ul v-if="open" class="menu">
        <li v-for="o in options" :key="o.value">
          <button
            class="opt"
            :class="{ on: o.value === modelValue, disabled: o.disabled }"
            type="button"
            @click="pick(o)"
          >
            {{ o.label }}<span v-if="o.value === modelValue" class="check">✓</span>
          </button>
        </li>
      </ul>
    </Transition>
  </div>
</template>

<style scoped>
.mg-select {
  position: relative;
  min-width: 130px;
}

/* 收起态:普通主题边框 */
.trigger {
  display: inline-flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  background: var(--bg-void);
  border: 1px solid var(--line);
  color: var(--text);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}

.trigger:hover {
  color: var(--cyan);
  border-color: var(--line-bright);
}

/* 展开态:边框亮起主题强调色 + 辉光 */
.mg-select.open .trigger {
  color: var(--cyan);
  border-color: var(--line-bright);
  box-shadow: var(--glow-cyan);
}

.value {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chev {
  font-size: 10px;
  color: var(--text-dim);
  transition: transform var(--dur-fast) var(--ease-out);
}

.chev.open {
  transform: rotate(180deg);
}

/* 下拉菜单:边框与主题边框体系一致 */
.menu {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  min-width: 100%;
  list-style: none;
  margin: 0;
  padding: 6px;
  background: var(--bg-panel);
  border: 1px solid var(--line-bright);
  border-radius: 8px;
  backdrop-filter: blur(10px);
  box-shadow: var(--glow-cyan);
  z-index: 40;
}

.opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  background: transparent;
  border: none;
  color: var(--text);
  padding: 8px 12px;
  border-radius: 5px;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--dur-fast);
}

.opt:hover:not(.disabled) {
  color: var(--cyan);
  background: color-mix(in srgb, var(--cyan) 8%, transparent);
}

.opt.on {
  color: var(--cyan);
}

.opt.disabled {
  color: var(--text-dim);
  cursor: not-allowed;
}

.check {
  font-size: 11px;
}

.drop-enter-active,
.drop-leave-active {
  transition:
    opacity var(--dur-fast) var(--ease-out),
    transform var(--dur-fast) var(--ease-out);
}

.drop-enter-from,
.drop-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
