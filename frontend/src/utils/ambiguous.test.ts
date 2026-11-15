/**
 * 跨板块知识点登记表测试。
 *
 * 两个判定的分工必须守住:
 *   resolveAmbiguous —— 已有上下文,直接定方向(不问用户);
 *   detectAmbiguous  —— 只有裸词,必须返回 topic 让界面追问。
 * 判错方向会让「特征值」永远被当成线性代数,判成裸词则每次都要追问。
 */
import { describe, expect, it } from 'vitest'
import { AMBIGUOUS_TOPICS, detectAmbiguous, resolveAmbiguous, topicById } from '@/utils/ambiguous'

describe('AMBIGUOUS_TOPICS / 数据完整性', () => {
  it('登记表规模与 id 唯一性', () => {
    expect(AMBIGUOUS_TOPICS.length).toBeGreaterThanOrEqual(30)
    expect(new Set(AMBIGUOUS_TOPICS.map((t) => t.id)).size).toBe(AMBIGUOUS_TOPICS.length)
  })

  it('每个知识点都有双语文案、fallback 与至少两个方向', () => {
    for (const topic of AMBIGUOUS_TOPICS) {
      expect(topic.term).toBeInstanceOf(RegExp)
      expect(topic.scope.zh.length).toBeGreaterThan(0)
      expect(topic.scope.en.length).toBeGreaterThan(0)
      expect(typeof topic.fallback).toBe('string')
      expect(topic.options.length).toBeGreaterThanOrEqual(2)
      for (const option of topic.options) {
        expect(option.label.zh.length).toBeGreaterThan(0)
        expect(option.hint.en.length).toBeGreaterThan(0)
        expect(option.context).toBeInstanceOf(RegExp)
      }
    }
  })

  it('fallback 必须指向该知识点自身的某个方向', () => {
    for (const topic of AMBIGUOUS_TOPICS) {
      expect(topic.options.map((o) => o.key)).toContain(topic.fallback)
    }
  })
})

describe('topicById', () => {
  it('命中返回知识点,未命中返回 null', () => {
    expect(topicById('eigen')?.id).toBe('eigen')
    expect(topicById('not-a-topic')).toBeNull()
    expect(topicById('')).toBeNull()
  })
})

describe('resolveAmbiguous / 有上下文时定方向', () => {
  it('最小二乘:矩阵语境 → 代数,回归语境 → 统计', () => {
    expect(resolveAmbiguous('矩阵的最小二乘解')?.option.key).toBe('algebra')
    expect(resolveAmbiguous('最小二乘回归拟合')?.option.key).toBe('probability')
  })

  it('特征值:矩阵/对角化 → 代数,微分方程组 → ODE,马尔可夫链 → 概率', () => {
    expect(resolveAmbiguous('求矩阵的特征值')?.option.key).toBe('algebra')
    expect(resolveAmbiguous('微分方程组的特征值')?.option.key).toBe('ode')
    expect(resolveAmbiguous('马尔可夫链的特征值')?.option.key).toBe('probability')
  })

  it('英文提问同样能定方向(大小写不敏感)', () => {
    expect(resolveAmbiguous('Least Squares via normal equations')?.option.key).toBe('algebra')
    expect(resolveAmbiguous('EIGENVALUE of a matrix')?.option.key).toBe('algebra')
  })

  it('指令前缀不影响判定', () => {
    expect(resolveAmbiguous('[问题记录] 矩阵的特征值')?.option.key).toBe('algebra')
  })

  it('有裸词但没有方向线索时返回 null(交给 detectAmbiguous)', () => {
    expect(resolveAmbiguous('讲讲最小二乘')).toBeNull()
    expect(resolveAmbiguous('特征值是什么')).toBeNull()
  })

  it('完全不涉及登记表词条时返回 null', () => {
    expect(resolveAmbiguous('极限的定义')).toBeNull()
    expect(resolveAmbiguous('')).toBeNull()
  })

  it('返回的 topic 与 option 自洽(option 属于 topic)', () => {
    const hit = resolveAmbiguous('幂级数的收敛半径')
    if (hit) {
      expect(hit.topic.options).toContain(hit.option)
      expect(hit.topic.term.test('幂级数')).toBe(true)
    }
  })
})

describe('detectAmbiguous / 裸词需要追问', () => {
  it('只提裸词时返回待询问的知识点', () => {
    expect(detectAmbiguous('最小二乘')?.id).toBe('least-squares')
    expect(detectAmbiguous('特征值')?.id).toBe('eigen')
    expect(detectAmbiguous('二次型')?.id).toBe('quadratic-form')
    expect(detectAmbiguous('least squares')?.id).toBe('least-squares')
  })

  it('已带方向线索时不追问', () => {
    expect(detectAmbiguous('矩阵的最小二乘')).toBeNull()
    expect(detectAmbiguous('马尔可夫链的特征值')).toBeNull()
  })

  it('与 resolveAmbiguous 互斥:同一句话最多一个命中', () => {
    for (const text of ['最小二乘', '最小二乘回归', '特征值', '矩阵的特征值', '留数', '用留数算积分']) {
      const resolved = resolveAmbiguous(text)
      const detected = detectAmbiguous(text)
      expect(resolved === null || detected === null).toBe(true)
    }
  })

  it('未涉及登记表词条时不追问', () => {
    expect(detectAmbiguous('矩阵的秩')).toBeNull()
    expect(detectAmbiguous('')).toBeNull()
  })

  it('只命中第一个词条(按登记顺序),不会一次抛多个问题', () => {
    const hit = detectAmbiguous('特征值与最小二乘')
    expect(hit?.id).toBe('least-squares')
  })
})
