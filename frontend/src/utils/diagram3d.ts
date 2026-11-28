/**
 * 3D 坐标映射:数学坐标 (x, y, z) → Three.js (x, z, -y)。
 * z 轴朝上、保持右手系;曲面与点/线/向量必须共用同一映射,否则曲面会镜像。
 */

export function mathToThree(point: ArrayLike<number>): [number, number, number] {
  const x = Number(point[0] ?? 0)
  const y = Number(point[1] ?? 0)
  const z = Number(point[2] ?? 0)
  return [x, z, y === 0 ? 0 : -y]
}

/** 按 row-major 的曲面采样点生成 Three.js position 缓冲 */
export function surfacePositions(points: number[][]): Float32Array {
  const out = new Float32Array(points.length * 3)
  points.forEach((point, index) => {
    const [x, y, z] = mathToThree(point)
    out[index * 3] = x
    out[index * 3 + 1] = y
    out[index * 3 + 2] = z
  })
  return out
}

/** 曲面三角形索引:逆时针朝 +y(数学 +z),与 z=f(x,y) 上侧法向一致 */
export function surfaceIndices(rows: number, cols: number): number[] {
  const indices: number[] = []
  for (let row = 0; row < rows - 1; row += 1) {
    for (let col = 0; col < cols - 1; col += 1) {
      const a = row * cols + col
      const b = a + 1
      const c = a + cols
      const d = c + 1
      indices.push(a, b, c, b, d, c)
    }
  }
  return indices
}
