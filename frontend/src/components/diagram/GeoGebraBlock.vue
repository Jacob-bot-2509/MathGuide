<script setup lang="ts">
/** GeoGebra 图解:命令版 spec 交给 GeoGebra 引擎渲染(2D Classic / 3D)。 */
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'
import type { DiagramSpec } from '@/utils/diagramSpec'
import { t } from '@/utils/i18n'

const props = defineProps<{ spec: DiagramSpec }>()
const host = ref<HTMLDivElement | null>(null)
const error = ref('')
const rawId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
const hostId = `ggb-${rawId}`
let applet: GgbApi | null = null
let disposed = false

interface GgbApi {
  evalCommand(command: string): boolean
  setErrorDialogsActive(active: boolean): void
  setPerspective(perspective: string): void
  setWidth(width: number): void
  setHeight(height: number): void
  remove?: () => void
}

declare global {
  interface Window {
    GGBApplet?: new (params: Record<string, unknown>, html5: boolean) => {
      inject(id: string): void
    }
    __ggbLoader?: Promise<void>
  }
}

const SCRIPT_URL = (import.meta.env.VITE_GEOGEBRA_BASE as string | undefined)
  || 'https://www.geogebra.org/apps/deployggb.js'

function loadGeoGebra(): Promise<void> {
  if (window.GGBApplet) return Promise.resolve()
  if (window.__ggbLoader) return window.__ggbLoader
  window.__ggbLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('geogebra script failed'))
    document.head.appendChild(script)
  })
  return window.__ggbLoader
}

function runCommands(api: GgbApi): number {
  let ok = 0
  for (const command of props.spec.commands || []) {
    try {
      if (api.evalCommand(command)) ok += 1
    } catch {
      /* 单条失败只跳过,不弹窗、不阻塞其余命令 */
    }
  }
  return ok
}

onMounted(async () => {
  const el = host.value
  if (!el) return
  try {
    await loadGeoGebra()
    if (disposed || !window.GGBApplet) return
    const is3d = props.spec.type === 'geogebra3d'
    const params = {
      appName: is3d ? '3d' : 'classic',
      width: Math.max(280, el.clientWidth),
      height: Math.max(280, el.clientHeight),
      showMenuBar: false,
      showToolBar: false,
      showAlgebraInput: false,
      showAlgebraView: false,
      showInputBar: false,
      showResetIcon: false,
      showZoomButtons: false,
      enableLabelDrags: false,
      enableRightClick: false,
      language: 'zh-CN',
      useBrowserForJS: false,
      appletOnLoad(api: GgbApi) {
        if (disposed) return
        applet = api
        try { api.setErrorDialogsActive(false) } catch { /* 老版本无此 API */ }
        try { api.setPerspective(is3d ? 'T' : 'G') } catch { /* 忽略 */ }
        if (runCommands(api) === 0) error.value = t('diagram.renderFail')
      },
    }
    new window.GGBApplet(params, true).inject(hostId)
  } catch {
    error.value = t('diagram.renderFail')
  }
})

onBeforeUnmount(() => {
  disposed = true
  try { applet?.remove?.() } catch { /* 忽略 */ }
  applet = null
  if (window.__ggbLoader) window.__ggbLoader = undefined
})
</script>

<template>
  <div class="ggb-wrap">
    <div :id="hostId" ref="host" class="ggb-host" />
    <p v-if="error" class="ggb-error">{{ error }}</p>
  </div>
</template>

<style scoped>
.ggb-wrap {
  width: 100%;
  max-width: 560px;
  margin: 0 auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.ggb-host {
  width: 100%;
  height: 340px;
}

.ggb-error {
  margin: 0;
  padding: 10px 12px;
  color: var(--text-dim);
  font-size: 12px;
}

@media (max-width: 680px) {
  .ggb-host {
    height: 280px;
  }
}
</style>
