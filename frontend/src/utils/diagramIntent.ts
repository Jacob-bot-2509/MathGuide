/** 图解意图:识别用户本轮/最近一次明确说过的“不要画图”和“恢复画图”。 */

export interface DiagramHistoryItem {
  role: string
  content: string
}

// 与后端 research_diagrams._NO_DIAGRAM_RE 保持同一口径:
// “先不要画图 / 不用配图 / 别画了 / 不要画思维导图”都算停止指令。
const NO_DIAGRAM_RE = /(?:先|暂时|这次|本轮|本次|今天)?\s*(?:不要|不用|不需要|不必|无需|别|不)\s*(?:再|先|急着|用)?\s*(?:画|生成|出|配|做|给|用|展示)?\s*(?:图|图解|图示|图像|示意图|思维导图|可视化)|(?:不要|不用|别|无需)\s*(?:再|先)?\s*(?:画|生成|配|做)(?:了|吧|啦)?(?=\s|$|[，。,.!?])|\b(?:do not|don't|dont|no need to|without|skip)\s+(?:draw|drawing|generate|show|include|using)?\s*(?:a\s+)?(?:diagram|figure|graph|chart|visuali[sz]ation)\b/i

const DRAW_AGAIN_RE = /(?:可以|现在|继续|开始|还是|重新|恢复|请|帮我)?\s*(?:画|生成|出|做|配|给)\s*(?:一?张|个)?\s*(?:三维|3d|二维|2d|立体|函数|曲线|几何|流程|思维导图|关系)?\s*(?:图|图解|图示|图像|示意图)|\b(?:draw|show|generate|include)\s+(?:a\s+)?(?:diagram|figure|graph|chart)\b|(?:用|来)\s*(?:一?张|个)?\s*(?:三维|3d|二维|2d|立体|函数|曲线|几何|流程|思维导图|关系)?\s*(?:图|图解|图示|图像|示意图)/i

function messageState(text: string): boolean | null {
  const body = text || ''
  const negative = NO_DIAGRAM_RE.exec(body)
  const positive = DRAW_AGAIN_RE.exec(body)
  // 同一句里“不要画思维导图,画三维图”以后半句为准。
  if (positive && (!negative || positive.index > negative.index + negative[0].length)) {
    return false
  }
  if (negative) return true
  if (positive) return false
  return null
}

/** 本轮是否被用户明确要求不画图;最近的明确指令优先,直到用户恢复。 */
export function diagramSuppressed(
  question: string,
  history: DiagramHistoryItem[] = [],
): boolean {
  const current = messageState(question)
  if (current !== null) return current
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = history[index]
    if (item.role !== 'user') continue
    const state = messageState(item.content || '')
    if (state !== null) return state
  }
  return false
}

/** 用户明显在问“怎么理解/几何直观/关系/区别”,或明确要求画图时,允许回答结束后补一张图。 */
export function needsDiagram(
  question: string,
  history: DiagramHistoryItem[] = [],
): boolean {
  if (diagramSuppressed(question, history)) return false
  return /怎么理解|如何理解|怎么直观|几何直观|直观理解|怎么想|有什么关系|什么关系|有什么区别|为什么会|推导|证明思路|三维|3d|立体|曲面|梯度|画(?:个|张|一)?图|图示|示意图|可视化|一步步|逐步|图解|how (?:can|do|to) .*understand|geometric intuition|intuition|relationship|difference|draw|diagram|3d|surface|gradient/i
    .test(question || '')
}
