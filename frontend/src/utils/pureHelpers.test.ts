// @vitest-environment happy-dom
/**
 * 小型纯工具批量测试:cmdLink / toast / regressionChart / workspace。
 *
 * 这四个模块语句数都不超过 24,但线上都承担"出错就静默异常"的职责:
 * 畸形百分号编码会让章节链接点不动、toast 定时器不清会串提示、
 * 子域判定错会把用户带到错误的学习/科研区。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { chapterNameFromCmd } from '@/utils/cmdLink'
import { fitSegments, residualSegments, type RegressionResultLike } from '@/utils/regressionChart'
import { showToast, toast } from '@/utils/toast'
import {
  crossWorkspaceHref,
  hostWorkspace,
  isSameWorkspaceHost,
  workspaceOfRoute,
} from '@/utils/workspace'

describe('cmdLink', () => {
  it('只认 cmd://chapter/ 前缀', () => {
    expect(chapterNameFromCmd('https://x/y')).toBeNull()
    expect(chapterNameFromCmd('')).toBeNull()
  })

  it('解出百分号编码的章节名', () => {
    expect(chapterNameFromCmd('cmd://chapter/%E6%9E%81%E9%99%90')).toBe('极限')
  })

  it('畸形编码退回原始文本,而不是抛 URIError', () => {
    expect(chapterNameFromCmd('cmd://chapter/%E0%A4%A')).toBe('%E0%A4%A')
  })

  it('空前缀后没有内容时返回 null', () => {
    expect(chapterNameFromCmd('cmd://chapter/')).toBeNull()
  })
})

describe('toast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    toast.msg = ''
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('显示后按指定时长自动消失', () => {
    showToast('已保存', 1000)
    expect(toast.msg).toBe('已保存')
    vi.advanceTimersByTime(999)
    expect(toast.msg).toBe('已保存')
    vi.advanceTimersByTime(1)
    expect(toast.msg).toBe('')
  })

  it('连续提示时清掉上一个定时器,不会提前消失', () => {
    showToast('第一条', 1000)
    vi.advanceTimersByTime(800)
    showToast('第二条', 1000)
    vi.advanceTimersByTime(800)      // 距离第一条已 1600ms
    expect(toast.msg).toBe('第二条')  // 若旧定时器没清,这里会是空
    vi.advanceTimersByTime(200)
    expect(toast.msg).toBe('')
  })
})

describe('regressionChart', () => {
  const result: RegressionResultLike = {
    points: [
      { row: 0, x: 1, actual: 3, fitted: 2.9, residual: 0.1 },
      { row: 1, x: 2, actual: 5, fitted: 4.8, residual: 0.2 },
    ],
    fitCurve: [{ x: 1, y: 2.9 }, { x: 2, y: 4.8 }],
  }

  it('有拟合曲线时包装成单段折线', () => {
    expect(fitSegments(result)).toEqual([{ points: result.fitCurve }])
  })

  it('没有拟合曲线时返回空数组(多元回归不画线)', () => {
    expect(fitSegments({ ...result, fitCurve: [] })).toEqual([])
  })

  it('残差散点用 fitted 作横轴', () => {
    expect(residualSegments(result)).toEqual([{ x: 2.9, y: 0.1 }, { x: 4.8, y: 0.2 }])
  })
})

describe('workspace', () => {
  it('按子域判定工作区', () => {
    expect(hostWorkspace('research.example.com')).toBe('research')
    expect(hostWorkspace('learn.example.com')).toBe('learn')
    expect(hostWorkspace('RESEARCH.example.com')).toBe('research')
  })

  it('单域部署返回 null(路由里的 workspace 字段照常工作)', () => {
    expect(hostWorkspace('localhost')).toBeNull()
    expect(hostWorkspace('mg.example.com')).toBeNull()
  })

  it('路由 → 工作区', () => {
    expect(workspaceOfRoute('/research')).toBe('research')
    expect(workspaceOfRoute('/research/search')).toBe('research')
    expect(workspaceOfRoute('/learn/chat')).toBe('learn')
    expect(workspaceOfRoute('/home')).toBeNull()
    expect(workspaceOfRoute('/settings')).toBeNull()
  })

  it('同区或单域时不跨域跳转', () => {
    // happy-dom 默认 localhost → 单域,返回原路径
    expect(isSameWorkspaceHost('learn')).toBe(true)
    expect(crossWorkspaceHref('research', '/research/search')).toBe('/research/search')
  })

  it('跨子域时切到目标子域并保留路径,丢掉查询与锚点', () => {
    const happy = window as unknown as { happyDOM?: { setURL(url: string): void } }
    happy.happyDOM?.setURL('https://learn.example.com/learn/chat?x=1#top')

    expect(hostWorkspace()).toBe('learn')
    expect(isSameWorkspaceHost('research')).toBe(false)
    expect(isSameWorkspaceHost('learn')).toBe(true)
    expect(crossWorkspaceHref('research', '/research/search'))
      .toBe('https://research.example.com/research/search')
  })
})
