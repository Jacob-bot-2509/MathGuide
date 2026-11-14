// @vitest-environment happy-dom
/**
 * 头像工具测试:预设头像与相册图片压缩�?
 *
 * 压缩链路(Image �?canvas �?toDataURL)在真实浏览器里无法单�?这里�?
 * Image / canvas / URL 全部换成可控替身,钉住四件�?
 *   1. 等比缩放只缩不放,长边落到 maxDim;
 *   2. 头像方形裁剪取中心最大正方形;
 *   3. canvas 不可用时 reject,不会 resolve 出空 dataURL;
 *   4. 成败都要 revokeObjectURL,否则 blob 泄漏�?
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AVATAR_PRESETS, compressImage, fileToAvatar } from '@/utils/avatar'

const DATA_URL = 'data:image/jpeg;base64,AAAA'

type FakeImage = {
  width: number
  height: number
  onload: (() => void) | null
  onerror: (() => void) | null
  src: string
}

let createObjectURL: ReturnType<typeof vi.fn>
let revokeObjectURL: ReturnType<typeof vi.fn>
let drawImage: ReturnType<typeof vi.fn>
let toDataURL: ReturnType<typeof vi.fn>
let canvases: Array<{ width: number; height: number }>
let ctxAvailable = true
let imageMode: 'load' | 'error' = 'load'
let naturalSize = { width: 200, height: 100 }

function installImage() {
  class StubImage implements FakeImage {
    width = naturalSize.width
    height = naturalSize.height
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    #src = ''
    get src() {
      return this.#src
    }
    set src(value: string) {
      this.#src = value
      // 浏览器的 load/error 是异步事�?这里用微任务保持同样的时�?
      queueMicrotask(() => {
        if (imageMode === 'error') this.onerror?.()
        else this.onload?.()
      })
    }
  }
  vi.stubGlobal('Image', StubImage)
}

beforeEach(() => {
  ctxAvailable = true
  imageMode = 'load'
  naturalSize = { width: 200, height: 100 }
  canvases = []
  createObjectURL = vi.fn(() => 'blob:fake-1')
  revokeObjectURL = vi.fn()
  drawImage = vi.fn()
  toDataURL = vi.fn(() => DATA_URL)
  Object.assign(URL, { createObjectURL, revokeObjectURL })
  installImage()

  const realCreate = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, options?: unknown) => {
    if (tag !== 'canvas') return realCreate(tag, options as never)
    const canvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => (ctxAvailable ? { drawImage } : null)),
      toDataURL,
    }
    canvases.push(canvas)
    return canvas
  }) as never)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function png(name = 'photo.png'): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type: 'image/png' })
}

describe('AVATAR_PRESETS', () => {
  it('提供 8 个互不重复的预设,key 前缀统一、颜色为十六进制', () => {
    expect(AVATAR_PRESETS).toHaveLength(8)
    expect(new Set(AVATAR_PRESETS.map((p) => p.key)).size).toBe(8)
    for (const preset of AVATAR_PRESETS) {
      expect(preset.key.startsWith('preset:')).toBe(true)
      expect(preset.glyph.length).toBeGreaterThan(0)
      expect(preset.from).toMatch(/^#[0-9a-f]{6}$/i)
      expect(preset.to).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })

  it('key 顺序稳定(用于按索引回退默认头像)', () => {
    expect(AVATAR_PRESETS.map((p) => p.key)).toEqual([
      'preset:sum', 'preset:int', 'preset:inf', 'preset:grad',
      'preset:pi', 'preset:sqrt', 'preset:part', 'preset:fn',
    ])
  })
})

describe('compressImage', () => {
  it('长边缩到 maxDim,短边等比,输出 JPEG dataURL', async () => {
    const result = await compressImage(png(), 50, 0.6)
    expect(result).toBe(DATA_URL)
    expect(canvases.at(-1)).toMatchObject({ width: 50, height: 25 })
    expect(drawImage).toHaveBeenCalledTimes(1)
    expect(toDataURL).toHaveBeenCalledWith('image/jpeg', 0.6)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1')
  })

  it('图片本身小于上限时不放大', async () => {
    naturalSize = { width: 64, height: 32 }
    await compressImage(png(), 512)
    expect(canvases.at(-1)).toMatchObject({ width: 64, height: 32 })
    // 默认质量 0.75
    expect(toDataURL).toHaveBeenCalledWith('image/jpeg', 0.75)
  })

  it('canvas 不可用时 reject 并回�?blob', async () => {
    ctxAvailable = false
    await expect(compressImage(png(), 128)).rejects.toThrow('canvas unavailable')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1')
    expect(toDataURL).not.toHaveBeenCalled()
  })

  it('图片加载失败�?reject 并回�?blob', async () => {
    imageMode = 'error'
    await expect(compressImage(png(), 128)).rejects.toThrow('image load failed')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1')
  })
})

describe('fileToAvatar', () => {
  it('裁成 128 方形:从中心取最大正方形', async () => {
    naturalSize = { width: 400, height: 200 }
    const result = await fileToAvatar(png())
    expect(result).toBe(DATA_URL)
    expect(canvases.at(-1)).toMatchObject({ width: 128, height: 128 })
    // (400,200) �?源矩�?(100,0,200,200) �?目标 (0,0,128,128)
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 100, 0, 200, 200, 0, 0, 128, 128)
    expect(toDataURL).toHaveBeenCalledWith('image/jpeg', 0.85)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1')
  })

  it('竖图同样取中心正方形', async () => {
    naturalSize = { width: 100, height: 300 }
    await fileToAvatar(png())
    expect(drawImage).toHaveBeenCalledWith(expect.anything(), 0, 100, 100, 100, 0, 0, 128, 128)
  })

  it('canvas 不可用时 reject', async () => {
    ctxAvailable = false
    await expect(fileToAvatar(png())).rejects.toThrow('canvas unavailable')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-1')
  })

  it('图片加载失败�?reject', async () => {
    imageMode = 'error'
    await expect(fileToAvatar(png())).rejects.toThrow('image load failed')
  })
})
