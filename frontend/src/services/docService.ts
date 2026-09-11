/**
 * 文档导出服务:研究综述 → PDF(后端 LLM 结构化重组 + Edge headless 转 PDF)。
 * 一次性下载:拿到 Blob 后由调用方触发浏览器下载,服务端不存档。
 */
import { httpError } from '@/api/http'
import { getToken, logout as clearUser } from '@/stores/user'
import router from '@/router'
import { showToast } from '@/utils/toast'
import { t } from '@/utils/i18n'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export interface ExportResult {
  blob: Blob
  filename: string
}

/**
 * 导出研究综述为 PDF。
 * lang: 'zh' | 'en'(语言由调用方弹菜单选择后传入);
 * 生成要 20~60 秒(LLM 重组 + PDF 转码),调用方应展示「生成中」状态。
 * 401 与聊天服务同口径:清登录态回登录页;其余错误抛 HttpError 由调用方提示。
 */
export async function exportSurveyPdf(content: string, lang: 'zh' | 'en'): Promise<ExportResult> {
  const token = getToken()
  const res = await fetch(`${BASE_URL}/api/doc/export`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content, lang }),
  })
  if (res.status === 401) {
    clearUser()
    router.push('/login')
    showToast(t('login.toastExpired'))
    throw httpError(res)
  }
  if (!res.ok) throw httpError(res)
  const blob = await res.blob()
  // 文件名取响应头,兜底用日期(真实标题由页面标题提供,这里保持服务端命名一致)
  const cd = res.headers.get('Content-Disposition') ?? ''
  const m = /filename="([^"]+)"/.exec(cd)
  return { blob, filename: m?.[1] ?? `mg-survey-${lang}.pdf` }
}

/** 触发浏览器下载(一次性下载,不落服务端) */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
