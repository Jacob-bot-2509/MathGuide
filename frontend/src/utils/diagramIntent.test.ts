/**
 * 图解意图测试。
 *
 * 「不要画图」要一直生效到用户恢复,但恢复指令必须能压过同一句里的否定;
 * 反过来,误判成需要画图会让每个回答都带图。两侧都按真实句式钉住。
 */
import { describe, expect, it } from 'vitest'
import { diagramSuppressed, needsDiagram } from '@/utils/diagramIntent'

const user = (content: string) => ({ role: 'user', content })
const assistant = (content: string) => ({ role: 'assistant', content })

describe('diagramSuppressed / 本轮指令', () => {
  it('明确说不要画图 → 抑制', () => {
    expect(diagramSuppressed('这次不要画图')).toBe(true)
    expect(diagramSuppressed('不用配图')).toBe(true)
    expect(diagramSuppressed('别画了')).toBe(true)
    expect(diagramSuppressed('不要画思维导图')).toBe(true)
    expect(diagramSuppressed("don't draw a diagram")).toBe(true)
  })

  it('明确要求画图 → 不抑制', () => {
    expect(diagramSuppressed('请画一张三维图')).toBe(false)
    expect(diagramSuppressed('draw a diagram please')).toBe(false)
  })

  it('同一句里否定在前、恢复在后时以后半句为准', () => {
    expect(diagramSuppressed('不要画思维导图,画三维图')).toBe(false)
  })

  it('没有任何明确指令时默认不抑制', () => {
    expect(diagramSuppressed('矩阵的秩怎么求')).toBe(false)
    expect(diagramSuppressed('')).toBe(false)
  })
})

describe('diagramSuppressed / 历史回溯', () => {
  it('历史里最近的明确指令优先', () => {
    expect(diagramSuppressed('继续', [user('这次不要画图')])).toBe(true)
    expect(diagramSuppressed('继续', [user('不要画图'), user('现在恢复画图')])).toBe(false)
  })

  it('只回看用户消息,助手回复里的“不要画图”不算', () => {
    expect(diagramSuppressed('继续', [assistant('这次不要画图')])).toBe(false)
  })

  it('历史里没有明确指令时默认不抑制', () => {
    expect(diagramSuppressed('继续', [user('矩阵的秩'), assistant('秩是……')])).toBe(false)
    expect(diagramSuppressed('继续')).toBe(false)
  })

  it('空内容的历史项被跳过,不抛异常', () => {
    expect(diagramSuppressed('', [user('')])).toBe(false)
  })
})

describe('needsDiagram', () => {
  it('被抑制时一律不需要图', () => {
    expect(needsDiagram('不要画图,讲讲梯度')).toBe(false)
    expect(needsDiagram('讲讲梯度', [user('这次不要画图')])).toBe(false)
  })

  it('求直观/关系/推导类提问需要配图', () => {
    expect(needsDiagram('这个怎么理解')).toBe(true)
    expect(needsDiagram('梯度的几何直观是什么')).toBe(true)
    expect(needsDiagram('导数和微分有什么关系')).toBe(true)
    expect(needsDiagram('帮我一步步推导')).toBe(true)
    expect(needsDiagram('画个图说明')).toBe(true)
  })

  it('英文直觉类提问同样需要图', () => {
    expect(needsDiagram('how can I understand this surface')).toBe(true)
    expect(needsDiagram('geometric intuition of gradient')).toBe(true)
  })

  it('普通定义/计算类提问不需要图', () => {
    expect(needsDiagram('矩阵的秩是什么')).toBe(false)
    expect(needsDiagram('求这个极限')).toBe(false)
    expect(needsDiagram('')).toBe(false)
  })
})
