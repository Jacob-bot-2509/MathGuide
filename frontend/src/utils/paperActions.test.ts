/**
 * 论文窗口动作协议测试:后端 SSE 帧 → 前端白名单动作。
 *
 * 这段代码是「服务端事件」与「PDF 阅读器动作」之间唯一的闸门:
 * 字段白名单、边界值(页码/引文长度)与去重都在这里,任何一个放宽都可能
 * 让畸形帧把阅读器写坏或重复标注,所以逐分支钉住。
 */
import { describe, expect, it, vi } from 'vitest'
import type { PaperAction } from '@/services/researchService'
import {
  handlePaperActionMeta,
  paperActionFingerprint,
  parsePaperActionEvent,
} from '@/utils/paperActions'

function event(actions: unknown[], extra: Record<string, unknown> = {}) {
  return { mg_event: 'paper_actions', requestId: 'req-1', docId: 'doc-1', actions, ...extra }
}

describe('parsePaperActionEvent / 帧形状', () => {
  it('非对象载荷一律返回 null', () => {
    expect(parsePaperActionEvent(null)).toBeNull()
    expect(parsePaperActionEvent(undefined)).toBeNull()
    expect(parsePaperActionEvent('paper_actions')).toBeNull()
    expect(parsePaperActionEvent(42)).toBeNull()
  })

  it('新事件帧解析出 requestId 与 docId', () => {
    const parsed = parsePaperActionEvent(event([{ type: 'highlight', page: 3, quote: '定理 1.2' }]))
    expect(parsed).toEqual({
      requestId: 'req-1',
      docId: 'doc-1',
      actions: [{ type: 'highlight', page: 3, quote: '定理 1.2' }],
    })
  })

  it('缺 requestId 时退回 legacy(旧后端兼容)', () => {
    const parsed = parsePaperActionEvent({ mg_event: 'paper_actions', actions: [{ type: 'highlight', page: 1, quote: 'q' }] })
    expect(parsed?.requestId).toBe('legacy')
    expect(parsed?.docId).toBe('')
  })

  it('旧 meta 帧(mg_meta.paperActions)仍可解析', () => {
    const parsed = parsePaperActionEvent({
      mg_meta: { paperActions: [{ type: 'highlight', page: 2, quote: '引文' }], paperRequestId: 'legacy-req' },
    })
    expect(parsed?.requestId).toBe('legacy-req')
    expect(parsed?.docId).toBe('')
    expect(parsed?.actions).toHaveLength(1)
  })

  it('mg_meta 不是对象时返回 null', () => {
    expect(parsePaperActionEvent({ mg_meta: null })).toBeNull()
    expect(parsePaperActionEvent({ mg_meta: 'x' })).toBeNull()
    expect(parsePaperActionEvent({ mg_event: 'other' })).toBeNull()
  })

  it('actions 不是数组时返回 null', () => {
    expect(parsePaperActionEvent({ mg_event: 'paper_actions', actions: 'highlight' })).toBeNull()
    expect(parsePaperActionEvent({ mg_meta: { paperActions: {} } })).toBeNull()
  })

  it('全部动作非法时返回 null(不产生空动作帧)', () => {
    expect(parsePaperActionEvent(event([null, 1, 'x', {}]))).toBeNull()
    expect(parsePaperActionEvent(event([]))).toBeNull()
  })
})

describe('parsePaperActionEvent / 字段白名单', () => {
  it('未知 type 被丢弃', () => {
    expect(parsePaperActionEvent(event([{ type: 'delete', page: 1, quote: 'q' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 123, page: 1, quote: 'q' }]))).toBeNull()
  })

  it('highlight 缺页码或引文时丢弃', () => {
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: 0, quote: 'q' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: -2, quote: 'q' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: 1, quote: '   ' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: 'x', quote: 'q' }]))).toBeNull()
  })

  it('页码做截断取整,非有限值归零后丢弃', () => {
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: '7.9', quote: 'q' }]))?.actions)
      .toEqual([{ type: 'highlight', page: 7, quote: 'q' }])
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: Infinity, quote: 'q' }]))).toBeNull()
  })

  it('annotate 默认黄色,非法颜色也退回黄色', () => {
    const ok = parsePaperActionEvent(event([{ type: 'annotate', page: 2, quote: 'q', note: ' 笔记 ' }]))
    expect(ok?.actions[0]).toEqual({ type: 'annotate', page: 2, quote: 'q', note: '笔记', color: 'yellow' })
    const odd = parsePaperActionEvent(event([{ type: 'annotate', page: 2, quote: 'q', color: 'RAINBOW' }]))
    expect(odd?.actions[0].color).toBe('yellow')
    const cyan = parsePaperActionEvent(event([{ type: 'annotate', page: 2, quote: 'q', color: 'CYAN' }]))
    expect(cyan?.actions[0].color).toBe('cyan')
  })

  it('query 只在非空时附加', () => {
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: 1, quote: 'q', query: ' 极值 ' }]))?.actions[0])
      .toEqual({ type: 'highlight', page: 1, quote: 'q', query: '极值' })
    expect(parsePaperActionEvent(event([{ type: 'highlight', page: 1, quote: 'q', query: '' }]))?.actions[0])
      .toEqual({ type: 'highlight', page: 1, quote: 'q' })
  })

  it('超长引文/笔记按上限截断', () => {
    const parsed = parsePaperActionEvent(event([
      { type: 'annotate', page: 1, quote: 'q'.repeat(2100), note: 'n'.repeat(4100) },
    ]))
    expect(parsed?.actions[0].quote).toHaveLength(2000)
    expect(parsed?.actions[0].note).toHaveLength(4000)
  })

  it('deleteAnnotation 只需要 id', () => {
    expect(parsePaperActionEvent(event([{ type: 'deleteAnnotation', id: ' ann-1 ' }]))?.actions[0])
      .toEqual({ type: 'deleteAnnotation', id: 'ann-1' })
    expect(parsePaperActionEvent(event([{ type: 'deleteAnnotation', id: '' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'deleteAnnotation' }]))).toBeNull()
  })

  it('updateAnnotation 需要 id 且至少一个可改字段', () => {
    expect(parsePaperActionEvent(event([{ type: 'updateAnnotation', id: 'a1' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'updateAnnotation', note: ' 改 ' }]))).toBeNull()
    expect(parsePaperActionEvent(event([{ type: 'updateAnnotation', id: 'a1', note: ' 改 ' }]))?.actions[0])
      .toEqual({ type: 'updateAnnotation', id: 'a1', note: '改' })
    expect(parsePaperActionEvent(event([{ type: 'updateAnnotation', id: 'a1', color: 'green' }]))?.actions[0])
      .toEqual({ type: 'updateAnnotation', id: 'a1', color: 'green' })
    // 非法颜色不算「有字段改动」 → 丢弃
    expect(parsePaperActionEvent(event([{ type: 'updateAnnotation', id: 'a1', color: 'pink' }]))).toBeNull()
  })

  it('同帧重复动作按指纹去重', () => {
    const parsed = parsePaperActionEvent(event([
      { type: 'highlight', page: 1, quote: '同一句' },
      { type: 'highlight', page: 1, quote: '同一句' },
      { type: 'highlight', page: 2, quote: '同一句' },
    ]))
    expect(parsed?.actions).toHaveLength(2)
  })

  it('单帧动作数量上限 16', () => {
    const many = Array.from({ length: 30 }, (_, i) => ({ type: 'highlight', page: i + 1, quote: 'q' }))
    expect(parsePaperActionEvent(event(many))?.actions).toHaveLength(16)
  })
})

describe('handlePaperActionMeta', () => {
  it('解析失败或未指定目标论文时不执行', () => {
    const apply = vi.fn()
    expect(handlePaperActionMeta(null, 'doc-1', apply)).toBe(false)
    expect(handlePaperActionMeta(event([{ type: 'highlight', page: 1, quote: 'q' }]), '', apply)).toBe(false)
    expect(apply).not.toHaveBeenCalled()
  })

  it('docId 不匹配时丢弃(避免把标注打到别的论文)', () => {
    const apply = vi.fn()
    const frame = event([{ type: 'highlight', page: 1, quote: 'q' }])
    expect(handlePaperActionMeta(frame, 'doc-2', apply)).toBe(false)
    expect(apply).not.toHaveBeenCalled()
  })

  it('帧里没有 docId 时按当前论文处理', () => {
    const apply = vi.fn()
    const frame = { mg_meta: { paperActions: [{ type: 'highlight', page: 4, quote: 'q' }] } }
    expect(handlePaperActionMeta(frame, 'doc-9', apply)).toBe(true)
    expect(apply).toHaveBeenCalledWith([{ type: 'highlight', page: 4, quote: 'q' }], 'legacy')
  })

  it('匹配成功时把动作与 requestId 交给调用方', () => {
    const apply = vi.fn()
    const frame = event([{ type: 'deleteAnnotation', id: 'a1' }], { docId: 'doc-1' })
    expect(handlePaperActionMeta(frame, 'doc-1', apply)).toBe(true)
    expect(apply).toHaveBeenCalledWith([{ type: 'deleteAnnotation', id: 'a1' }], 'req-1')
  })
})

describe('paperActionFingerprint', () => {
  it('批注类按 id 去重', () => {
    const a: PaperAction = { type: 'deleteAnnotation', id: 'x1' }
    const b: PaperAction = { type: 'updateAnnotation', id: 'x1' }
    expect(paperActionFingerprint(a)).toBe('deleteAnnotation:x1')
    expect(paperActionFingerprint(b)).toBe('updateAnnotation:x1')
    expect(paperActionFingerprint({ type: 'deleteAnnotation' })).toBe('deleteAnnotation:')
  })

  it('高亮类按页码 + 引文前 80 字去重', () => {
    expect(paperActionFingerprint({ type: 'highlight', page: 3, quote: '引文' })).toBe('highlight:3:引文')
    expect(paperActionFingerprint({ type: 'highlight' })).toBe('highlight:0:')
    const longQuote = 'q'.repeat(200)
    expect(paperActionFingerprint({ type: 'annotate', page: 1, quote: longQuote }))
      .toBe(`annotate:1:${'q'.repeat(80)}`)
  })
})
