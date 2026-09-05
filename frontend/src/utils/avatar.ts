/**
 * 头像:预设头像(渐变 + 数学符号)与相册图片压缩。
 */

export interface AvatarPreset {
  key: string
  glyph: string
  from: string
  to: string
}

export const AVATAR_PRESETS: AvatarPreset[] = [
  { key: 'preset:sum', glyph: '∑', from: '#4dd6ff', to: '#2f7bff' },
  { key: 'preset:int', glyph: '∫', from: '#8b5cf6', to: '#ff4dd2' },
  { key: 'preset:inf', glyph: '∞', from: '#4dd6ff', to: '#8b5cf6' },
  { key: 'preset:grad', glyph: '∇', from: '#2f7bff', to: '#4dffb8' },
  { key: 'preset:pi', glyph: 'π', from: '#ff4dd2', to: '#ff8fa3' },
  { key: 'preset:sqrt', glyph: '√', from: '#ffd166', to: '#ff9d6b' },
  { key: 'preset:part', glyph: '∂', from: '#4dffb8', to: '#4dd6ff' },
  { key: 'preset:fn', glyph: 'ƒ', from: '#b18cff', to: '#60a5fa' },
]

/**
 * 图片 → 最长边压缩为 maxDim 的 JPEG dataURL(用于聊天附件)。
 * quality 默认 0.75:演示环境图片以 dataURL 存入 localStorage,体积需要克制。
 */
export function compressImage(file: File, maxDim: number, quality = 0.75): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(img.width * scale)
      canvas.height = Math.round(img.height * scale)
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        reject(new Error('canvas unavailable'))
        return
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', quality))
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image load failed'))
    }
    img.src = url
  })
}

/** 相册图片 → 128px 方形压缩头像(dataURL) */
export function fileToAvatar(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(file)
    img.onload = () => {
      const size = 128
      const canvas = document.createElement('canvas')
      canvas.width = size
      canvas.height = size
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        URL.revokeObjectURL(url)
        reject(new Error('canvas unavailable'))
        return
      }
      const s = Math.min(img.width, img.height)
      ctx.drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, size, size)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', 0.85))
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('image load failed'))
    }
    img.src = url
  })
}
