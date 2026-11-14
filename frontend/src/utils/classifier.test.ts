/**
 * 问题分类器测试。
 *
 * 分类结果决定会话切到哪个板块、答案走哪套提示词,也决定「是否算一次提问」
 * (闲聊不进归纳本)。这里钉住三件事:优先级(具体板块先匹配)、中英文同口径、
 * 以及跨板块裸词先走澄清而不是硬归一类。
 */
import { describe, expect, it } from 'vitest'
import {
  CATEGORIES,
  DISPLAY_KEYS,
  FALLBACK_CATEGORY,
  categoryByKey,
  classifyQuestion,
  isChitchat,
} from '@/utils/classifier'

describe('categoryByKey', () => {
  it('已知板块返回公开字段(不泄漏关键词表)', () => {
    const cat = categoryByKey('topology')
    expect(cat).toEqual({ key: 'topology', label: '拓扑学', color: '#4dffb8' })
    expect(cat).not.toHaveProperty('keywords')
  })

  it('未知板块返回 null', () => {
    expect(categoryByKey('unknown')).toBeNull()
    expect(categoryByKey('')).toBeNull()
  })
})

describe('classifyQuestion / 关键词命中', () => {
  it('中文问题归到对应板块', () => {
    expect(classifyQuestion('求这个矩阵的特征值').key).toBe('algebra')
    expect(classifyQuestion('证明这个级数收敛').key).toBe('analysis')
    expect(classifyQuestion('素数有无穷多个怎么证').key).toBe('numberTheory')
    expect(classifyQuestion('开集与闭集的区别').key).toBe('topology')
  })

  it('英文问题同样能归类(大小写不敏感)', () => {
    expect(classifyQuestion('Find the Eigenvalue of this Matrix').key).toBe('algebra')
    expect(classifyQuestion('PROVE this series converges').key).toBe('analysis')
  })

  it('指令前缀被剥掉后再分类', () => {
    expect(classifyQuestion('[章节知识导航] 极限的定义').key).toBe('analysis')
    expect(classifyQuestion('  [问题记录] 矩阵的秩').key).toBe('algebra')
  })

  it('优先级:具体板块先于宽泛的数学分析', () => {
    // 同时出现「积分」(analysis)与「留数」(complex)时取靠前的 complex
    expect(classifyQuestion('用留数计算这个积分').key).toBe('complex')
    // 「微分方程」优先于「导数」
    expect(classifyQuestion('这个微分方程的导数怎么求').key).toBe('ode')
  })

  it('匹配不到任何板块时返回未归类', () => {
    const cat = classifyQuestion('今天天气不错')
    expect(cat).toEqual(FALLBACK_CATEGORY)
    expect(classifyQuestion('').key).toBe('other')
  })
})

describe('classifyQuestion / 跨板块词', () => {
  it('带上下文时直接定方向,不再追问', () => {
    expect(classifyQuestion('矩阵的最小二乘解').key).toBe('algebra')
    expect(classifyQuestion('回归里的最小二乘估计').key).toBe('probability')
    expect(classifyQuestion('马尔可夫链的特征值').key).toBe('probability')
  })

  it('只有裸词时按登记表的默认板块回答', () => {
    expect(classifyQuestion('讲讲最小二乘').key).toBe('algebra')
    expect(classifyQuestion('特征向量是什么').key).toBe('algebra')
  })
})

describe('isChitchat', () => {
  it('空文本不算闲聊(没有内容就没有可回答的东西)', () => {
    expect(isChitchat('')).toBe(false)
    expect(isChitchat('   ')).toBe(false)
  })

  it('寒暄/感谢/告别算闲聊', () => {
    expect(isChitchat('你好')).toBe(true)
    expect(isChitchat('hello')).toBe(true)
    expect(isChitchat('How are you')).toBe(true)
    expect(isChitchat('谢谢!')).toBe(true)
    expect(isChitchat('thanks a lot')).toBe(true)
    expect(isChitchat('再见')).toBe(true)
    expect(isChitchat('bye')).toBe(true)
  })

  it('带板块主题词的消息不算闲聊', () => {
    expect(isChitchat('矩阵的秩是什么')).toBe(false)
    expect(isChitchat('介绍一下极限')).toBe(false)
  })

  it('寒暄出现在句首时优先于主题词(否则 "How are you" 会被当数学题)', () => {
    expect(isChitchat('你好,矩阵的秩是什么')).toBe(true)
  })

  it('题目措辞判定为数学问题', () => {
    expect(isChitchat('求一下这个式子')).toBe(false)
    expect(isChitchat('这道题怎么做')).toBe(false)
    expect(isChitchat('prove that the sum is finite')).toBe(false)
  })

  it('其余一般对话按闲聊处理', () => {
    expect(isChitchat('你是谁')).toBe(true)
    expect(isChitchat('我今天有点累')).toBe(true)
  })

  it('指令前缀不影响闲聊判定', () => {
    expect(isChitchat('[章节知识导航] 你好')).toBe(true)
  })
})

describe('板块元数据', () => {
  it('分类表每项都有 key/label/color 与非空关键词', () => {
    expect(CATEGORIES.length).toBe(8)
    for (const cat of CATEGORIES) {
      expect(cat.key).toMatch(/^[a-z][A-Za-z]*$/)
      expect(cat.label.length).toBeGreaterThan(0)
      expect(cat.color).toMatch(/^#[0-9a-f]{6}$/i)
      expect(cat.keywords.length).toBeGreaterThan(0)
      // 关键词统一小写,才能与 toLowerCase 后的正文匹配
      expect(cat.keywords.every((kw) => kw === kw.toLowerCase())).toBe(true)
    }
  })

  it('展示顺序覆盖全部板块并含未归类垫底', () => {
    expect(DISPLAY_KEYS).toHaveLength(CATEGORIES.length + 1)
    expect(DISPLAY_KEYS.at(-1)).toBe('other')
    for (const cat of CATEGORIES) expect(DISPLAY_KEYS).toContain(cat.key)
  })
})
