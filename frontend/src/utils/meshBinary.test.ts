import { describe, expect, it } from 'vitest'

import { shapeMesh } from '@/utils/meshBinary'

function b64(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes))
}

function f32(values: number[]): number[] {
  const buffer = new ArrayBuffer(values.length * 4)
  const view = new DataView(buffer)
  values.forEach((value, index) => view.setFloat32(index * 4, value, true))
  return Array.from(new Uint8Array(buffer))
}

function u16(values: number[]): number[] {
  const buffer = new ArrayBuffer(values.length * 2)
  const view = new DataView(buffer)
  values.forEach((value, index) => view.setUint16(index * 2, value, true))
  return Array.from(new Uint8Array(buffer))
}

function u32(values: number[]): number[] {
  const buffer = new ArrayBuffer(values.length * 4)
  const view = new DataView(buffer)
  values.forEach((value, index) => view.setUint32(index * 4, value, true))
  return Array.from(new Uint8Array(buffer))
}

describe('shapeMesh', () => {
  it('解码 Float32 顶点与 Uint32 索引', () => {
    const mesh = shapeMesh({
      positions_b64: b64(f32([0, 0, 0, 1, 0, 0, 0, 1, 0])),
      indices_b64: b64(u32([0, 1, 2])),
    })
    expect(mesh).not.toBeNull()
    expect(Array.from(mesh!.positions)).toEqual([0, 0, 0, 1, 0, 0, 0, 1, 0])
    expect(Array.from(mesh!.indices)).toEqual([0, 1, 2])
  })

  it('解码 Uint16 索引', () => {
    const mesh = shapeMesh({
      positions_b64: b64(f32([0, 0, 0, 1, 0, 0, 0, 1, 0])),
      indices_b64: b64(u16([0, 1, 2])),
      indexType: 'u16',
    })
    expect(Array.from(mesh!.indices)).toEqual([0, 1, 2])
  })

  it('兼容旧 positions/indices 数组', () => {
    const mesh = shapeMesh({
      positions: [0, 0, 0, 1, 0, 0, 0, 1, 0],
      indices: [0, 1, 2],
    })
    expect(mesh?.positions).toHaveLength(9)
    expect(mesh?.indices).toHaveLength(3)
  })

  it('非法 base64 返回 null,不抛异常', () => {
    expect(shapeMesh({ positions_b64: '!!', indices_b64: '!!' })).toBeNull()
  })
})
