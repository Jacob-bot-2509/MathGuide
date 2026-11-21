import { describe, expect, it } from 'vitest'
import { panBy, pinchMetrics, zoomAround } from './graphGesture'

describe('graphGesture', () => {
  it('pinchMetrics 给出两指间距与中点', () => {
    const m = pinchMetrics({ x: 0, y: 0 }, { x: 30, y: 40 })
    expect(m.distance).toBe(50)
    expect(m.mid).toEqual({ x: 15, y: 20 })
  })

  it('zoomAround 围绕锚点放大,锚点在视口中的相对位置不变', () => {
    const view = { x: 0, y: 0, w: 1000, h: 500 }
    const anchor = { x: 250, y: 125 }
    zoomAround(view, anchor, 0.5, 100, 2000)
    expect(view.w).toBe(500)
    expect(view.h).toBe(250)
    // 锚点仍在视口内同一相对位置(左上 25%)
    expect(view.x).toBe(125)
    expect(view.y).toBe(62.5)
  })

  it('zoomAround 受上下限夹紧,越界时不再移动', () => {
    const view = { x: 0, y: 0, w: 1000, h: 500 }
    zoomAround(view, { x: 0, y: 0 }, 0.001, 500, 1600)
    expect(view.w).toBe(500)
    zoomAround(view, { x: 0, y: 0 }, 100, 500, 1600)
    expect(view.w).toBe(1600)
    expect(view.h).toBe(800)
  })

  it('panBy 按屏幕位移反向移动视口', () => {
    const view = { x: 10, y: 20, w: 100, h: 50 }
    panBy(view, 5, -4)
    expect(view).toEqual({ x: 5, y: 24, w: 100, h: 50 })
  })
})
