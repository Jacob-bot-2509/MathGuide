/** 浏览器录音 → 16kHz 单声道 WAV → base64,供后端 ASR 使用。
 *
 * Web Speech 在国产浏览器/Android 网络下不可靠,所以保留一条完全走
 * MediaRecorder + 后端的兜底链路。后端只收 WAV/MP3 且限制 30 秒;
 * 这里统一重采样为 16kHz 单声道 16-bit,30 秒约 960KB,base64 后仍低于 2MB。
 */

/** 把 [-1, 1] 的浮点采样编码成 PCM 16-bit WAV。 */
export function encodeWav(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const pcmBytes = samples.length * 2
  const buffer = new ArrayBuffer(44 + pcmBytes)
  const view = new DataView(buffer)

  const writeText = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i))
  }

  writeText(0, 'RIFF')
  view.setUint32(4, 36 + pcmBytes, true)
  writeText(8, 'WAVE')
  writeText(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt chunk size
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate
  view.setUint16(32, 2, true) // block align
  view.setUint16(34, 16, true) // bits per sample
  writeText(36, 'data')
  view.setUint32(40, pcmBytes, true)

  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }
  return buffer
}

type AudioCtor = typeof AudioContext

function audioContext(): AudioContext {
  const Ctor = (window.AudioContext
    ?? (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext)
  if (!Ctor) throw new Error('AudioContext unavailable')
  return new Ctor()
}

/** 解码任意浏览器录音格式,重采样为 16kHz 单声道 WAV。 */
export async function blobToWav(blob: Blob, targetRate = 16000): Promise<Blob> {
  if (typeof OfflineAudioContext === 'undefined') {
    throw new Error('OfflineAudioContext unavailable')
  }
  const ctx = audioContext()
  try {
    const decoded = await ctx.decodeAudioData(await blob.arrayBuffer())
    const frames = Math.max(1, Math.ceil(decoded.duration * targetRate))
    const offline = new OfflineAudioContext(1, frames, targetRate)
    const source = offline.createBufferSource()
    source.buffer = decoded
    source.connect(offline.destination)
    source.start()
    const rendered = await offline.startRendering()
    return new Blob([encodeWav(rendered.getChannelData(0), targetRate)], {
      type: 'audio/wav',
    })
  } finally {
    void ctx.close()
  }
}

/** 分块 btoa,避免大数组一次展开爆调用栈。 */
export async function blobToBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer())
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  }
  return btoa(binary)
}
