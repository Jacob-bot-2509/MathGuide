// @vitest-environment happy-dom
/**
 * geogebra3dKernel:隐藏 3D 内核的参数校验、可用性探测与降级。
 *
 * 3D 内核比 2D 更脆:applet 体积更大(超时 30s)、透视必须切到 3D(T)、
 * 一旦不可用必须立刻失败让调用方回落到静态图解,而不是把 NaN 顶点交给
 * WebGL 场景。这里锁死四件事:
 *   1. 参数正确(appName=3d、perspective=T、不设角度单位);
 *   2. 空命令不启动 applet;
 *   3. 脚本失败 / applet 超时 → 重试一次后抛错,并清掉缓存的失败 Promise;
 *   4. 单条命令抛错不阻塞其余命令,复位 API 缺失时回退 reset。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { convertGeoGebra3DCommands } from '@/services/geogebra3dKernel'

type Api = {
  evalCommand: (command: string) => boolean
  getXML: () => string
  newConstruction?: () => void
  reset?: () => void
  setErrorDialogsActive?: (active: boolean) => void
  setPerspective?: (perspective: string) => void
}

const HOST_ID = 'mg-ggb3d-kernel-host'

/** 最小 3D XML:一个普通点,足以产出 geometry3d spec */
const XML = '<geogebra><construction>'
  + '<element type="point3d" label="A"><coords x="1" y="2" z="3"/></element>'
  + '</construction></geogebra>'

const win = window as unknown as Record<string, unknown>

function clearKernelState() {
  delete win.__mgGgb3dKernel
  delete win.__mgGgb3dLoader
  delete win.GGBApplet
  document.getElementById(HOST_ID)?.remove()
}

interface Harness {
  api: Api
  params: Record<string, unknown>[]
  inject: string[]
  constructed: () => number
}

function installApplet(options: {
  api?: Partial<Api>
  respond?: boolean
} = {}): Harness {
  const params: Record<string, unknown>[] = []
  const inject: string[] = []
  let constructed = 0
  const api: Api = {
    evalCommand: vi.fn(() => true),
    getXML: vi.fn(() => XML),
    newConstruction: vi.fn(),
    setErrorDialogsActive: vi.fn(),
    setPerspective: vi.fn(),
    ...options.api,
  }
  const respond = options.respond !== false
  win.GGBApplet = class {
    constructor(private readonly config: Record<string, unknown>, readonly html5: boolean) {
      constructed += 1
      params.push(config)
    }

    inject(id: string) {
      inject.push(id)
      if (respond) (this.config.appletOnLoad as (api: Api) => void)(api)
    }
  }
  return { api, params, inject, constructed: () => constructed }
}

beforeEach(() => {
  clearKernelState()
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
})


describe('convertGeoGebra3DCommands:成功路径', () => {
  it('命令交给 3D 离屏 applet,产出 geometry3d spec 并带标题', async () => {
    const harness = installApplet()

    const spec = await convertGeoGebra3DCommands(['A=(1,2,3)'], '立体图示')

    expect(spec).not.toBeNull()
    expect(spec!.type).toBe('geometry3d')
    expect(spec!.title).toBe('立体图示')
    expect(spec!.shapes).toHaveLength(1)

    expect(harness.inject).toEqual([HOST_ID])
    expect(harness.params[0]).toMatchObject({
      appName: '3d',
      language: 'zh-CN',
      showAlgebraView: false,
      enableRightClick: false,
    })
    // 3D 视图 + 压制错误弹窗
    expect(harness.api.setPerspective).toHaveBeenCalledWith('T')
    expect(harness.api.setErrorDialogsActive).toHaveBeenCalledWith(false)
    expect(harness.api.newConstruction).toHaveBeenCalledTimes(1)
    expect(harness.api.evalCommand).toHaveBeenCalledWith('A=(1,2,3)')

    const host = document.getElementById(HOST_ID)!
    expect(host.style.position).toBe('fixed')
    expect(host.style.pointerEvents).toBe('none')
  })

  it('内核复用:第二次调用不重建 applet,但仍复位构造', async () => {
    const harness = installApplet()

    await convertGeoGebra3DCommands(['A=(1,2,3)'])
    await convertGeoGebra3DCommands(['B=(4,5,6)'])

    expect(harness.constructed()).toBe(1)
    expect(harness.api.newConstruction).toHaveBeenCalledTimes(2)
    expect(document.querySelectorAll(`#${HOST_ID}`)).toHaveLength(1)
  })

  it('没有 newConstruction 时回退 reset', async () => {
    const harness = installApplet({
      api: { newConstruction: undefined, reset: vi.fn() },
    })

    await convertGeoGebra3DCommands(['A=(1,2,3)'])

    expect(harness.api.reset).toHaveBeenCalledTimes(1)
  })

  it('单条命令抛错只跳过该条', async () => {
    const evalCommand = vi.fn((command: string) => {
      if (command === 'boom') throw new Error('geogebra panic')
      return true
    })
    installApplet({ api: { evalCommand } })

    const spec = await convertGeoGebra3DCommands(['A=(1,2,3)', 'boom'])

    expect(spec).not.toBeNull()
    expect(evalCommand).toHaveBeenCalledTimes(2)
  })
})

describe('convertGeoGebra3DCommands:参数校验与不可用降级', () => {
  it('空命令数组直接失败,不启动 applet', async () => {
    const harness = installApplet()

    await expect(convertGeoGebra3DCommands([]))
      .rejects.toThrow('geogebra 3d conversion failed')
    expect(harness.constructed()).toBe(0)
    expect(harness.api.evalCommand).not.toHaveBeenCalled()
  })

  it('脚本加载失败(CDN 不可达)时重试一次后抛错,并清掉失败缓存', async () => {
    const failed = Promise.reject(new Error('geogebra script failed'))
    failed.catch(() => undefined)
    win.__mgGgb3dLoader = failed

    await expect(convertGeoGebra3DCommands(['A=(1,2,3)']))
      .rejects.toThrow('geogebra 3d conversion failed')

    expect(win.__mgGgb3dKernel).toBeUndefined()
    expect(win.__mgGgb3dLoader).toBeUndefined()
    expect(document.getElementById(HOST_ID)).toBeNull()
  })

  it('脚本加载成功但没有 GGBApplet 时抛错', async () => {
    win.__mgGgb3dLoader = Promise.resolve()
    await expect(convertGeoGebra3DCommands(['A=(1,2,3)']))
      .rejects.toThrow('geogebra 3d conversion failed')
    expect(win.__mgGgb3dKernel).toBeUndefined()
  })

  it('applet 30s 内不回调 → 超时后抛错', async () => {
    vi.useFakeTimers()
    try {
      const harness = installApplet({ respond: false })

      const task = convertGeoGebra3DCommands(['A=(1,2,3)'])
      const assertion = expect(task).rejects.toThrow('geogebra 3d conversion failed')
      await vi.advanceTimersByTimeAsync(30000)
      await vi.advanceTimersByTimeAsync(30000)
      await assertion

      expect(harness.constructed()).toBe(2)
      expect(harness.api.evalCommand).not.toHaveBeenCalled()
      expect(win.__mgGgb3dKernel).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it('命令全部执行失败时不返回空 spec', async () => {
    const harness = installApplet({ api: { evalCommand: vi.fn(() => false) } })

    await expect(convertGeoGebra3DCommands(['bad']))
      .rejects.toThrow('geogebra 3d conversion failed')
    expect(harness.api.evalCommand).toHaveBeenCalledTimes(2)
  })

  it('XML 解析不出图形时判失败(避免 WebGL 黑屏)', async () => {
    installApplet({ api: { getXML: vi.fn(() => '<geogebra/>') } })

    await expect(convertGeoGebra3DCommands(['A=(1,2,3)']))
      .rejects.toThrow('geogebra 3d conversion failed')
  })
})
