import { describe, expect, it } from 'vitest'
import { encodeWav } from './wav'

function ascii(view: DataView, offset: number, length: number): string {
  return Array.from({ length }, (_, i) => String.fromCharCode(view.getUint8(offset + i))).join('')
}

describe('encodeWav', () => {
  it('写 PCM 16-bit 单声道 WAV 头', () => {
    const samples = new Float32Array([0, 0.5, -0.5, 1, -1])
    const view = new DataView(encodeWav(samples, 16000))

    expect(ascii(view, 0, 4)).toBe('RIFF')
    expect(view.getUint32(4, true)).toBe(36 + samples.length * 2)
    expect(ascii(view, 8, 4)).toBe('WAVE')
    expect(ascii(view, 12, 4)).toBe('fmt ')
    expect(view.getUint16(20, true)).toBe(1)
    expect(view.getUint16(22, true)).toBe(1)
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint32(28, true)).toBe(32000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(ascii(view, 36, 4)).toBe('data')
    expect(view.getUint32(40, true)).toBe(samples.length * 2)
    expect(view.byteLength).toBe(44 + samples.length * 2)
  })

  it('采样值裁剪到 [-1, 1]', () => {
    const view = new DataView(encodeWav(new Float32Array([2, -2]), 16000))
    expect(view.getInt16(44, true)).toBe(0x7fff)
    expect(view.getInt16(46, true)).toBe(-0x8000)
  })
})
