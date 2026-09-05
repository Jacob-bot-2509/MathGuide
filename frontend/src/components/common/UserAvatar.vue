<script setup lang="ts">
/**
 * 用户头像:预设头像(渐变 + 数学符号)或相册上传的图片。
 */
import { computed } from 'vue'
import { AVATAR_PRESETS } from '@/utils/avatar'

const props = withDefaults(defineProps<{ avatar?: string; size?: number }>(), { avatar: '', size: 32 })

const preset = computed(() =>
  props.avatar.startsWith('preset:') ? AVATAR_PRESETS.find((p) => p.key === props.avatar) : undefined,
)

const sizeStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.round(props.size * 0.45)}px`,
}))

const bgStyle = computed(() =>
  preset.value ? { background: `linear-gradient(135deg, ${preset.value.from}, ${preset.value.to})` } : undefined,
)
</script>

<template>
  <img v-if="avatar && !preset" class="ava" :style="sizeStyle" :src="avatar" alt="用户头像" />
  <div v-else class="ava" :style="[sizeStyle, bgStyle]">{{ preset ? preset.glyph : 'MG' }}</div>
</template>

<style scoped>
.ava {
  border-radius: 50%;
  object-fit: cover;
  display: grid;
  place-items: center;
  font-family: var(--font-tech);
  color: rgba(255, 255, 255, 0.92);
  user-select: none;
  flex-shrink: 0;
}
</style>
