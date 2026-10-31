/** 论文窗口动作协议:字段白名单、页码边界、重复动作去重。 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import {
  handlePaperActionMeta,
  parsePaperActionEvent,
  paperActionFingerprint,
} from '../src/utils/paperActions'

let passed = 0
const failed: string[] = []
function check(name: string, ok: boolean, detail = '') {
  if (ok) passed++
  else failed.push(`${name}${detail ? `: ${detail}` : ''}`)
}

const event = parsePaperActionEvent({
  mg_event: 'paper_actions',
  requestId: 'r1',
  docId: 'd1',
  actions: [
    { type: 'highlight', page: 3, quote: '结论在这里' },
    { type: 'highlight', page: 3, quote: '结论在这里' },
    { type: 'annotate', page: 2, quote: '方法', note: '重点', color: 'cyan' },
    { type: 'updateAnnotation', id: 'a1', note: '新批注' },
    { type: 'deleteAnnotation', id: 'a2' },
    { type: 'deleteAnnotation', id: '' },
    { type: 'highlight', page: 0, quote: '坏页码' },
    { type: 'unknown', page: 1, quote: 'x' },
  ],
})
check('事件存在', !!event)
check('请求 id', event?.requestId === 'r1')
check('文档 id', event?.docId === 'd1')
check('动作数去重/过滤', event?.actions.length === 4,
  JSON.stringify(event?.actions))
check('重复高亮只留一条',
  event?.actions.filter((a) => a.type === 'highlight').length === 1)
check('批注颜色白名单', event?.actions.find((a) => a.type === 'annotate')?.color === 'cyan')
check('空 id 删除被拒',
  !event?.actions.some((a) => a.type === 'deleteAnnotation' && !a.id))

const legacy = parsePaperActionEvent({
  mg_meta: {
    paperActions: [{ type: 'highlight', page: 1, quote: '摘要' }],
    paperRequestId: 'r2',
  },
})
check('兼容旧 meta 帧', legacy?.requestId === 'r2' && legacy.actions.length === 1)

check('无效帧返回 null', parsePaperActionEvent({ mg_meta: { research: true } }) === null)
check('高亮指纹稳定',
  paperActionFingerprint({ type: 'highlight', page: 2, quote: 'abc' })
  === 'highlight:2:abc')
check('更新按 id 去重',
  paperActionFingerprint({ type: 'updateAnnotation', id: 'a1' })
  === 'updateAnnotation:a1')

let applied = 0
const matched = handlePaperActionMeta({
  mg_event: 'paper_actions', requestId: 'r3', docId: 'd1',
  actions: [{ type: 'highlight', page: 1, quote: '摘要' }],
}, 'd1', () => { applied++ })
check('目标匹配执行', matched && applied === 1)
const mismatched = handlePaperActionMeta({
  mg_event: 'paper_actions', requestId: 'r4', docId: 'd2',
  actions: [{ type: 'highlight', page: 1, quote: '摘要' }],
}, 'd1', () => { applied++ })
check('目标不匹配拒绝', mismatched === false && applied === 1)
const noTarget = handlePaperActionMeta({
  mg_event: 'paper_actions', requestId: 'r5', docId: 'd1',
  actions: [{ type: 'highlight', page: 1, quote: '摘要' }],
}, '', () => { applied++ })
check('无论文上下文拒绝', noTarget === false && applied === 1)

if (failed.length) {
  console.error('论文动作协议自测失败:')
  for (const line of failed) console.error(' -', line)
  process.exit(1)
}
console.log(`论文动作协议自测:${passed}/${passed} 通过`)
