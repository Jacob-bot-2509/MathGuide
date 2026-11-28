import { describe, expect, it } from 'vitest'

import { mathToThree, surfaceIndices, surfacePositions } from '@/utils/diagram3d'

describe('diagram3d 坐标映射', () => {
  it('数学 (x,y,z) 映射到 Three (x,z,-y),保持右手系', () => {
    expect(mathToThree([1, 2, 3])).toEqual([1, 3, -2])
    expect(mathToThree([0, 0, 0])).toEqual([0, 0, 0])
  })

  it('曲面顶点与点/线使用同一映射,不再把 y 轴镜像', () => {
    const positions = surfacePositions([[1, 2, 3], [4, 5, 6]])
    expect(Array.from(positions)).toEqual([1, 3, -2, 4, 6, -5])
  })

  it('曲面三角形朝上,法向不被翻到 -y', () => {
    // 2×2 网格:x 方向 +1,y 方向 +1,z=0;映射后应为 (0,0,0),(1,0,0),(0,0,-1),(1,0,-1)
    const positions = surfacePositions([
      [0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0],
    ])
    const indices = surfaceIndices(2, 2)
    const point = (i: number) => [
      positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2],
    ]
    const [a, b, c] = indices.slice(0, 3).map(point)
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]]
    const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
    const normal = [
      u[1] * v[2] - u[2] * v[1],
      u[2] * v[0] - u[0] * v[2],
      u[0] * v[1] - u[1] * v[0],
    ]
    expect(normal[1]).toBeGreaterThan(0)
  })
})
