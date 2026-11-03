/** 隐藏 GeoGebra 2D 内核:只计算,不显示 GeoGebra 画布。
 *
 * 命令在离屏 applet 中执行,读取 getXML() 后转成我们的 DiagramSpec,
 * 最终仍由 DiagramSvg 渲染。
 */

import type { DiagramSpec } from '@/utils/diagramSpec'
import { diagramFromGeoGebraXml } from '@/utils/geogebraSpec'

interface GgbApi {
  evalCommand(command: string): boolean
  getXML(): string
  reset?(): void
  newConstruction?(): void
  setErrorDialogsActive?(active: boolean): void
  setPerspective?(perspective: string): void
  setAngleUnit?(unit: string): void
  remove?(): void
}

interface GgbAppletCtor {
  new (params: Record<string, unknown>, html5: boolean): { inject(id: string): void }
}

declare global {
  interface Window {
    __mgGgbKernel?: Promise<GgbApi>
    __mgGgbLoader?: Promise<void>
  }
}

const SCRIPT_URL = (import.meta.env.VITE_GEOGEBRA_BASE as string | undefined)
  || 'https://www.geogebra.org/apps/deployggb.js'
const HOST_ID = 'mg-ggb-kernel-host'
const SCRIPT_TIMEOUT = 20000
const APPLET_TIMEOUT = 25000

function ggbCtor(): GgbAppletCtor | null {
  return (window as unknown as { GGBApplet?: GgbAppletCtor }).GGBApplet || null
}

function loadScript(): Promise<void> {
  if (ggbCtor()) return Promise.resolve()
  if (window.__mgGgbLoader) return window.__mgGgbLoader
  window.__mgGgbLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true
    const timer = window.setTimeout(() => {
      reject(new Error('geogebra script timeout'))
    }, SCRIPT_TIMEOUT)
    script.onload = () => {
      window.clearTimeout(timer)
      resolve()
    }
    script.onerror = () => {
      window.clearTimeout(timer)
      reject(new Error('geogebra script failed'))
    }
    document.head.appendChild(script)
  })
  return window.__mgGgbLoader
}

function ensureHost(): string {
  let host = document.getElementById(HOST_ID)
  if (!host) {
    host = document.createElement('div')
    host.id = HOST_ID
    Object.assign(host.style, {
      position: 'fixed',
      left: '-10000px',
      top: '0',
      width: '640px',
      height: '480px',
      overflow: 'hidden',
      opacity: '0',
      pointerEvents: 'none',
    })
    document.body.appendChild(host)
  }
  return HOST_ID
}

async function ensureKernel(): Promise<GgbApi> {
  if (window.__mgGgbKernel) return window.__mgGgbKernel
  window.__mgGgbKernel = (async () => {
    await loadScript()
    const Applet = ggbCtor()
    if (!Applet) throw new Error('geogebra unavailable')
    const hostId = ensureHost()
    return await new Promise<GgbApi>((resolve, reject) => {
      let settled = false
      const timer = window.setTimeout(() => {
        if (!settled) {
          settled = true
          reject(new Error('geogebra applet timeout'))
        }
      }, APPLET_TIMEOUT)
      const params = {
        appName: 'classic',
        width: 640,
        height: 480,
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
          if (settled) return
          settled = true
          window.clearTimeout(timer)
          try { api.setErrorDialogsActive?.(false) } catch { /* 老版本无此 API */ }
          try { api.setPerspective?.('G') } catch { /* 忽略 */ }
          try { api.setAngleUnit?.('radian') } catch { /* 忽略 */ }
          resolve(api)
        },
      }
      new Applet(params, true).inject(hostId)
    })
  })()
  try {
    return await window.__mgGgbKernel
  } catch (error) {
    window.__mgGgbKernel = undefined
    window.__mgGgbLoader = undefined
    throw error
  }
}

function resetConstruction(api: GgbApi): void {
  if (typeof api.newConstruction === 'function') {
    api.newConstruction()
    return
  }
  if (typeof api.reset === 'function') api.reset()
}

async function runConversion(commands: string[]): Promise<DiagramSpec | null> {
  if (!commands.length) return null
  const api = await ensureKernel()
  resetConstruction(api)
  let ok = 0
  for (const command of commands) {
    try {
      if (api.evalCommand(command)) ok += 1
    } catch {
      /* 单条失败只跳过,不阻塞其余命令 */
    }
  }
  if (!ok) return null
  const xml = api.getXML()
  return diagramFromGeoGebraXml(xml)
}

function resetKernel(): void {
  window.__mgGgbKernel = undefined
  window.__mgGgbLoader = undefined
  document.getElementById(HOST_ID)?.remove()
}

let queue: Promise<unknown> = Promise.resolve()

async function attemptConversion(commands: string[]): Promise<DiagramSpec | null> {
  try {
    return await runConversion(commands)
  } catch {
    return null
  }
}

/** 串行执行构造命令,避免多个图解共用隐藏 applet 时互相污染。 */
export function convertGeoGebraCommands(
  commands: string[],
  title?: string,
): Promise<DiagramSpec | null> {
  const task = queue.then(async () => {
    let spec = await attemptConversion(commands)
    if (!spec) {
      // 首次加载可能是 CDN/Applet 超时:换一个干净的离屏实例重试一次。
      resetKernel()
      spec = await attemptConversion(commands)
    }
    if (!spec) throw new Error('geogebra conversion failed')
    if (title) spec.title = title
    return spec
  })
  queue = task.catch(() => undefined)
  return task
}
