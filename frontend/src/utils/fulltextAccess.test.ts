/**
 * 全文获取许可判定测试。
 *
 * 这段代码决定「能不能在站内读」「只能外链」「要用户上传」还是「重试」:
 * 判错一次就是版权问题(把付费墙 PDF 当 OA 抓)或功能坏掉(OA 却只给外链)。
 * safeHttpUrl 同时是唯一的地址闸门,非 http(s) 一律拦下。
 */
import { describe, expect, it } from 'vitest'
import {
  accessAction,
  accessLabelKey,
  canOpenInReader,
  externalPageUrl,
  pageReaderUrl,
  safeHttpUrl,
  type FullTextCandidate,
  type FullTextResult,
  type FullTextStatus,
} from '@/utils/fulltextAccess'

function candidate(patch: Partial<FullTextCandidate> = {}): FullTextCandidate {
  return { url: 'https://example.org/paper.pdf', serverDownloadable: true, ...patch }
}

function result(status: FullTextStatus, best: FullTextCandidate | null = candidate()): FullTextResult {
  return {
    status,
    best,
    candidates: best ? [best] : [],
    matchedIdentifiers: [],
    reason: '',
  }
}

describe('canOpenInReader', () => {
  it('只有 oa_pdf 且服务端可下载才允许站内阅读', () => {
    expect(canOpenInReader(result('oa_pdf'))).toBe(true)
    expect(canOpenInReader(result('oa_pdf', candidate({ serverDownloadable: false })))).toBe(false)
    expect(canOpenInReader(result('oa_pdf', null))).toBe(false)
    expect(canOpenInReader(result('oa_landing'))).toBe(false)
  })
})

describe('accessAction / 状态 → 动作', () => {
  it('逐个状态映射到唯一动作', () => {
    expect(accessAction(result('oa_pdf'))).toBe('reader')
    expect(accessAction(result('oa_landing'))).toBe('external')
    expect(accessAction(result('preprint'))).toBe('external')
    expect(accessAction(result('institutional'))).toBe('external')
    expect(accessAction(result('no_legal_copy', null))).toBe('upload')
    expect(accessAction(result('unknown', null))).toBe('retry')
    expect(accessAction(result('ambiguous'))).toBe('choose')
  })

  it('未知状态兜底为 retry(而不是静默什么都不做)', () => {
    expect(accessAction(result('weird' as FullTextStatus))).toBe('retry')
  })
})

describe('accessLabelKey', () => {
  it('每个状态都有对应文案 key', () => {
    expect(accessLabelKey(result('oa_pdf'))).toBe('search.fullTextOaPdf')
    expect(accessLabelKey(result('oa_landing'))).toBe('search.fullTextOaPage')
    expect(accessLabelKey(result('preprint'))).toBe('search.fullTextPreprint')
    expect(accessLabelKey(result('institutional'))).toBe('search.fullTextInstitutional')
    expect(accessLabelKey(result('no_legal_copy'))).toBe('search.fullTextNone')
    expect(accessLabelKey(result('ambiguous'))).toBe('search.fullTextAmbiguous')
    expect(accessLabelKey(result('unknown'))).toBe('search.fullTextUnknown')
  })

  it('未知状态退回 unknown 文案', () => {
    expect(accessLabelKey(result('weird' as FullTextStatus))).toBe('search.fullTextUnknown')
  })
})

describe('safeHttpUrl', () => {
  it('放行 http/https 绝对地址', () => {
    expect(safeHttpUrl('https://example.org/a')).toBe('https://example.org/a')
    expect(safeHttpUrl('http://example.org/a?b=1#c')).toBe('http://example.org/a?b=1#c')
  })

  it('拦下危险协议与相对地址', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('data:text/html,<b>x</b>')).toBeNull()
    expect(safeHttpUrl('file:///etc/passwd')).toBeNull()
    expect(safeHttpUrl('/relative/path')).toBeNull()
    expect(safeHttpUrl('ftp://example.org/a.pdf')).toBeNull()
  })

  it('空值与畸形地址返回 null,不抛异常', () => {
    expect(safeHttpUrl(null)).toBeNull()
    expect(safeHttpUrl(undefined)).toBeNull()
    expect(safeHttpUrl('')).toBeNull()
    expect(safeHttpUrl('not a url')).toBeNull()
  })
})

describe('externalPageUrl', () => {
  it('有安全地址时返回它(用于新标签打开)', () => {
    expect(externalPageUrl(result('oa_landing', candidate({ url: 'https://a.org/landing' }))))
      .toBe('https://a.org/landing')
  })

  it('没有候选或地址不安全时返回 null', () => {
    expect(externalPageUrl(result('oa_landing', null))).toBeNull()
    expect(externalPageUrl(result('oa_landing', candidate({ url: 'javascript:void(0)' })))).toBeNull()
  })
})

describe('pageReaderUrl', () => {
  it('只有 OA 落地页能站内抓正文', () => {
    expect(pageReaderUrl(result('oa_landing', candidate({ url: 'https://a.org/abs', kind: 'landing' }))))
      .toBe('https://a.org/abs')
  })

  it('PDF 直链不走站内抓取(交给阅读器/下载)', () => {
    expect(pageReaderUrl(result('oa_landing', candidate({ kind: 'pdf' })))).toBeNull()
  })

  it('非 oa_landing 状态一律不抓', () => {
    expect(pageReaderUrl(result('oa_pdf'))).toBeNull()
    expect(pageReaderUrl(result('preprint'))).toBeNull()
    expect(pageReaderUrl(result('institutional'))).toBeNull()
  })

  it('落地页地址不安全时返回 null', () => {
    expect(pageReaderUrl(result('oa_landing', candidate({ url: 'data:text/html,x', kind: 'html' })))).toBeNull()
  })
})
