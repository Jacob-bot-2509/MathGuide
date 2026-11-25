<script setup lang="ts">
/**
 * 精密坐标蓝图基底（Observatory Blueprint Canvas）：
 * 替代原 260 粒子动态星空与赛博透视网格，采用纯 CSS 发丝级坐标网格 + 柔和顶光景深。
 * 零 requestAnimationFrame 空转（省电、不抢占公式渲染与 PDF 滚动帧率），深浅色自动跟随令牌。
 * 保留组件文件名 Starfield.vue 以维持现有视图零破坏兼容。
 */
</script>

<template>
  <div class="blueprint-field" aria-hidden="true"></div>
</template>

<style scoped>
.blueprint-field {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-color: var(--bg-void);
  background-image:
    radial-gradient(
      ellipse 72% 48% at 50% 0%,
      color-mix(in srgb, var(--accent-primary) 10%, transparent),
      transparent 70%
    ),
    linear-gradient(
      to right,
      color-mix(in srgb, var(--line) 58%, transparent) 1px,
      transparent 1px
    ),
    linear-gradient(
      to bottom,
      color-mix(in srgb, var(--line) 58%, transparent) 1px,
      transparent 1px
    );
  background-size: 100% 100%, 40px 40px, 40px 40px;
}
</style>
