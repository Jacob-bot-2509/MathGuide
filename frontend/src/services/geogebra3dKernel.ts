/** 隐藏 GeoGebra 3D 内核:只计算实数三维构造,不显示 GeoGebra 画布。 */

import type { DiagramSpec } from '@/utils/diagramSpec'
import { diagramFromGeoGebra3DXml } from '@/utils/geogebra3dSpec'

interface GgbApi {
  evalCommand(command: string): boolean
  getXML(): string
  reset?(): void
  newConstruction?(): void
  setErrorDialogsActive?(active: boolean): void
  setPerspective?(perspective: string): void
  remove?(): void
}

interface GgbAppletCtor {
  new (params: Record<string, unknown>, html5: boolean): { inject(id: string): void }
}

declare global {
  interface Window {
    __mgGgb3dKernel?: Promise<GgbApi>
    __mgGgb3dLoader?: Promise<void>
  }
}

const SCRIPT_URL = (import.meta.env.VITE_GEOGEBRA_BASE as string | undefined)
  || 'https://www.geogebra.org/apps/deployggb.js'
const HOST_ID = 'mg-ggb3d-kernel-host'
const SCRIPT_TIMEOUT = 20000
const APPLET_TIMEOUT = 30000

function ggbCtor(): GgbAppletCtor | null {
  return (window as unknown as { GGBApplet?: GgbAppletCtor }).GGBApplet || null
}

function loadScript(): Promise<void> {
  if (ggbCtor()) return Promise.resolve()
  if (window.__mgGgb3dLoader) return window.__mgGgb3dLoader
  window.__mgGgb3dLoader = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = SCRIPT_URL
    script.async = true
    const timer = window.setTimeout(() => reject(new Error('geogebra script timeout')),
      SCRIPT_TIMEOUT)
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
  return window.__mgGgb3dLoader
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
  if (window.__mgGgb3dKernel) return window.__mgGgb3dKernel
  window.__mgGgb3dKernel = (async () => {
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
        appName: '3d',
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
          try { api.setErrorDialogsActive?.(false) } catch { /* ignore */ }
          try { api.setPerspective?.('T') } catch { /* ignore */ }
          resolve(api)
        },
      }
      new Applet(params, true).inject(hostId)
    })
  })()
  try {
    return await window.__mgGgb3dKernel
  } catch (error) {
    window.__mgGgb3dKernel = undefined
    window.__mgGgb3dLoader = undefined
    throw error
  }
}

function resetKernel(): void {
  window.__mgGgb3dKernel = undefined
  window.__mgGgb3dLoader = undefined
  document.getElementById(HOST_ID)?.remove()
}

function resetConstruction(api: GgbApi): void {
  if (typeof api.newConstruction === 'function') api.newConstruction()
  else if (typeof api.reset === 'function') api.reset()
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
      /* single command failure should not block others */
    }
  }
  if (!ok) return null
  return diagramFromGeoGebra3DXml(api.getXML())
}

let queue: Promise<unknown> = Promise.resolve()

async function attempt(commands: string[]): Promise<DiagramSpec | null> {
  try {
    return await runConversion(commands)
  } catch {
    return null
  }
}

export function convertGeoGebra3DCommands(
  commands: string[],
  title?: string,
): Promise<DiagramSpec | null> {
  const task = queue.then(async () => {
    let spec = await attempt(commands)
    if (!spec) {
      resetKernel()
      spec = await attempt(commands)
    }
    if (!spec) throw new Error('geogebra 3d conversion failed')
    if (title) spec.title = title
    return spec
  })
  queue = task.catch(() => undefined)
  return task
}
