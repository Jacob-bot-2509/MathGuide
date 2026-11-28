/** 隐式曲面网格解码:后端编码为 Float32 positions + Uint32 indices + base64。 */

export interface DecodedMesh {
  positions: Float32Array
  indices: Uint16Array | Uint32Array
}

const cache = new WeakMap<object, DecodedMesh | null>()

function decodeBase64(value: string): Uint8Array | null {
  try {
    const binary = atob(value)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
    return bytes
  } catch {
    return null
  }
}


/** 从 DiagramShape 解出网格;兼容旧的 positions/indices JSON。 */
export function shapeMesh(shape: Record<string, unknown>): DecodedMesh | null {
  const cached = cache.get(shape)
  if (cached !== undefined) return cached
  let result: DecodedMesh | null = null
  const posB64 = typeof shape.positions_b64 === 'string' ? shape.positions_b64 : ''
  const idxB64 = typeof shape.indices_b64 === 'string' ? shape.indices_b64 : ''
  if (posB64 && idxB64) {
    const posBytes = decodeBase64(posB64)
    const idxBytes = decodeBase64(idxB64)
    const indexWidth = shape.indexType === 'u16' ? 2 : 4
    if (posBytes && idxBytes && posBytes.length % 4 === 0
      && idxBytes.length % indexWidth === 0) {
      const positions = new Float32Array(
        posBytes.buffer, posBytes.byteOffset, posBytes.length / 4,
      )
      const indexType = shape.indexType === 'u16' ? 'u16' : 'u32'
      const indices = indexType === 'u16'
        ? new Uint16Array(idxBytes.buffer, idxBytes.byteOffset, idxBytes.length / 2)
        : new Uint32Array(idxBytes.buffer, idxBytes.byteOffset, idxBytes.length / 4)
      if (positions.length >= 9 && indices.length >= 3) {
        result = { positions, indices }
      }
    }
  } else if (Array.isArray(shape.positions) && Array.isArray(shape.indices)
    && shape.positions.length >= 9 && shape.indices.length >= 3) {
    result = {
      positions: Float32Array.from(shape.positions.map((v) => Number(v) || 0)),
      indices: Uint32Array.from(shape.indices.map((v) => Math.max(0, Math.trunc(Number(v) || 0)))),
    }
  }
  cache.set(shape, result)
  return result
}
