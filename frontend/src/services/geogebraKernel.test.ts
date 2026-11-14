// @vitest-environment happy-dom
/**
 * geogebraKernel:隐藏 2D 内核的参数校验、可用性探测与降级。
 *
 * 为什么这条链路值得测:内核跑在离屏 applet 里,一旦脚本/CDN 不可用或者
 * applet 迟迟不回调,页面不能白屏也不能一直转圈 —— 必须是「重试一次 →
 * 抛错 → 由调用方切回静态图解」。这里把每种失败都钉死:
 *   1. 空命令直接判失败(不白起一个 applet);
 *   2. 脚本加载失败 / applet 超时 → 重试后抛错,且缓存的 Promise 被清掉
 *      (否则失败会被永久缓存,后面每次图解都直接失败);
 *   3. 单条命令抛错不阻塞其余命令;
 *   4. 内核复用 + newConstruction/reset 两种复位方式。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { convertGeoGebraCommands } from '@/services/geogebraKernel'

type Api = {
  evalCommand: (command: string) => boolean
  getXML: () => string
  newConstruction?: () => void
  reset?: () => void
  setErrorDialogsActive?: (active: boolean) => void
  setPerspective?: (perspective: string) => void
  setAngleUnit?: (unit: string) => void
}

const HOST_ID = 'mg-ggb-kernel-host'

/** 一个能解析出点形状的最小 2D XML(解析器本体另有单测,这里只要有产出) */
const XML = '<geogebra><euclidianView/><construction>'
  + '<element type="point" label="A"><coords x="1" y="2" z="1"/></element>'
  + '</construction></geogebra>'

const win = window as unknown as Record<string, unknown>

function clearKernelState() {
  delete win.__mgGgbKernel
  delete win.__mgGgbLoader
  delete win.GGBApplet
  document.getElementById(HOST_ID)?.remove()
}

interface Harness {
  api: Api
  params: Record<string, unknown>[]
  inject: string[]
  constructed: () => number
}

/** 装一个假 GGBApplet:inject 时同步回调 appletOnLoad,模拟就绪 */
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
    setAngleUnit: vi.fn(),
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
  // happy-dom 在脚本加载被禁用时会自行 console.error;干净输出不影响断言
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
})


describe('convertGeoGebraCommands:成功路径', () => {
  it('把命令交给离屏 applet,产出 spec 并写回标题', async () => {
    const harness = installApplet()

    const spec = await convertGeoGebraCommands(['A=(1,2)', 'B=(3,4)'], '函数图示')

    expect(spec).not.toBeNull()
    expect(spec!.type).toBe('plot2d')
    expect(spec!.title).toBe('函数图示')
    expect(spec!.shapes.length).toBeGreaterThan(0)

    // 命令逐条执行
    expect(harness.api.evalCommand).toHaveBeenCalledTimes(2)
    expect(harness.api.evalCommand).toHaveBeenNthCalledWith(1, 'A=(1,2)')
    expect(harness.api.evalCommand).toHaveBeenNthCalledWith(2, 'B=(3,4)')
    // 每次复用一个干净构造
    expect(harness.api.newConstruction).toHaveBeenCalledTimes(1)

    // applet 参数:无界面 + 中文 + 只保留绘图区
    expect(harness.inject).toEqual([HOST_ID])
    expect(harness.params[0]).toMatchObject({
      appName: 'classic',
      language: 'zh-CN',
      showMenuBar: false,
      showAlgebraView: false,
      showToolBar: false,
      useBrowserForJS: false,
    })
    // 就绪后压制错误弹窗、切绘图视角与弧度制
    expect(harness.api.setErrorDialogsActive).toHaveBeenCalledWith(false)
    expect(harness.api.setPerspective).toHaveBeenCalledWith('G')
    expect(harness.api.setAngleUnit).toHaveBeenCalledWith('radian')

    // 离屏宿主确实挂进 DOM 且不可见
    const host = document.getElementById(HOST_ID)!
    expect(host.style.position).toBe('fixed')
    expect(host.style.opacity).toBe('0')
  })

  it('内核复用:第二次调用不再新建 applet,但仍复位构造', async () => {
    const harness = installApplet()

    await convertGeoGebraCommands(['A=(1,2)'])
    await convertGeoGebraCommands(['B=(3,4)'])

    expect(harness.constructed()).toBe(1)
    expect(harness.api.newConstruction).toHaveBeenCalledTimes(2)
    expect(document.querySelectorAll(`#${HOST_ID}`)).toHaveLength(1)
  })

  it('没有 newConstruction 时回退 reset', async () => {
    const harness = installApplet({
      api: { newConstruction: undefined, reset: vi.fn() },
    })

    await convertGeoGebraCommands(['A=(1,2)'])

    expect(harness.api.reset).toHaveBeenCalledTimes(1)
  })

  it('单条命令抛错只跳过该条,不阻塞其余命令', async () => {
    const evalCommand = vi.fn((command: string) => {
      if (command === 'boom') throw new Error('geogebra panic')
      return true
    })
    installApplet({ api: { evalCommand } })

    const spec = await convertGeoGebraCommands(['A=(1,2)', 'boom'])

    expect(spec).not.toBeNull()
    expect(evalCommand).toHaveBeenCalledTimes(2)
  })

  it('不传标题时不覆盖 spec 标题', async () => {
    installApplet()
    const spec = await convertGeoGebraCommands(['A=(1,2)'])
    expect(spec!.title).toBeUndefined()
  })
})

describe('convertGeoGebraCommands:参数校验与不可用降级', () => {
  it('空命令数组直接失败,不启动 applet', async () => {
    const harness = installApplet()

    await expect(convertGeoGebraCommands([])).rejects.toThrow('geogebra conversion failed')
    expect(harness.constructed()).toBe(0)
    expect(harness.api.evalCommand).not.toHaveBeenCalled()
  })

  it('脚本加载失败(CDN 不可达)时重试一次后抛错,并清掉缓存的失败 Promise', async () => {
    // GGBApplet 不存在 → loadScript 走缓存的 loader;这里给一个已失败的值
    const failed = Promise.reject(new Error('geogebra script failed'))
    failed.catch(() => undefined)
    win.__mgGgbLoader = failed

    await expect(convertGeoGebraCommands(['A=(1,2)']))
      .rejects.toThrow('geogebra conversion failed')

    // 失败不能被永久缓存,否则之后每次图解都直接失败
    expect(win.__mgGgbKernel).toBeUndefined()
    expect(win.__mgGgbLoader).toBeUndefined()
    expect(document.getElementById(HOST_ID)).toBeNull()
  })

  it('脚本加载成功却没有 GGBApplet(资源被拦)时抛错', async () => {
    win.__mgGgbLoader = Promise.resolve()
    await expect(convertGeoGebraCommands(['A=(1,2)']))
      .rejects.toThrow('geogebra conversion failed')
    expect(win.__mgGgbKernel).toBeUndefined()
  })

  it('applet 迟迟不回调 → 超时后抛错(不无限等待)', async () => {
    vi.useFakeTimers()
    try {
      // respond:false → inject 后不回调 appletOnLoad
      const harness = installApplet({ respond: false })

      const task = convertGeoGebraCommands(['A=(1,2)'])
      const assertion = expect(task).rejects.toThrow('geogebra conversion failed')
      await vi.advanceTimersByTimeAsync(25000)
      await vi.advanceTimersByTimeAsync(25000)
      await assertion

      // 超时后换干净实例重试了一次,且命令根本没能执行
      expect(harness.constructed()).toBe(2)
      expect(harness.api.evalCommand).not.toHaveBeenCalled()
      expect(win.__mgGgbKernel).toBeUndefined()
    } finally {
      vi.useRealTimers()
    }
  })

  it('所有命令都执行失败时不返回空 spec,而是判失败', async () => {
    const harness = installApplet({ api: { evalCommand: vi.fn(() => false) } })

    await expect(convertGeoGebraCommands(['bad']))
      .rejects.toThrow('geogebra conversion failed')
    // 两次尝试 = 两轮命令
    expect(harness.api.evalCommand).toHaveBeenCalledTimes(2)
  })

  it('XML 解析不出图形时同样判失败(避免渲染空画布)', async () => {
    installApplet({ api: { getXML: vi.fn(() => '<geogebra/>') } })

    await expect(convertGeoGebraCommands(['A=(1,2)']))
      .rejects.toThrow('geogebra conversion failed')
  })
})

describe('convertGeoGebraCommands:串行队列', () => {
  it('并发调用按顺序执行,互不污染构造', async () => {
    const order: string[] = []
    installApplet({
      api: {
        evalCommand: vi.fn((command: string) => {
          order.push(command)
          return true
        }),
      },
    })

    const [first, second] = await Promise.all([
      convertGeoGebraCommands(['A=(1,2)']),
      convertGeoGebraCommands(['B=(3,4)']),
    ])

    expect(first!.type).toBe('plot2d')
    expect(second!.type).toBe('plot2d')
    expect(order).toEqual(['A=(1,2)', 'B=(3,4)'])
  })
})

