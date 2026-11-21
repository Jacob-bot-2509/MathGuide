import { describe, expect, it } from 'vitest'

import {
  buildChapterMarkdown,
  chapterKey,
  locateChapter,
  normalizeTitle,
  sliceChapter,
  withRanges,
} from '@/utils/bookChapters'

const PAGES = [
  '封面',
  '第一章 极限\n1.1 数列极限\n正文',
  '第一章正文续',
  '第二章 导数\n2.1 导数定义',
  '第二章正文续',
  '第三章 积分',
]

describe('withRanges:书签补页码范围', () => {
  it('每章到下一个同级章之前结束', () => {
    const chapters = withRanges([
      { title: '第一章 极限', depth: 0, startPage: 1 },
      { title: '第二章 导数', depth: 0, startPage: 3 },
      { title: '第三章 积分', depth: 0, startPage: 5 },
    ], PAGES.length)
    expect(chapters.map((c) => [c.startPage, c.endPage])).toEqual([[1, 2], [3, 4], [5, 5]])
  })

  it('父章包含子节,子节到下一个更高级标题前结束', () => {
    const chapters = withRanges([
      { title: '第一章 极限', depth: 0, startPage: 1 },
      { title: '1.1 数列极限', depth: 1, startPage: 1 },
      { title: '第二章 导数', depth: 0, startPage: 3 },
    ], PAGES.length)
    expect(chapters.map((c) => [c.title, c.endPage])).toEqual([
      ['第一章 极限', 2],
      ['1.1 数列极限', 2],
      ['第二章 导数', 5],
    ])
  })
})

describe('locateChapter:章节定位', () => {
  it('书签精确匹配优先,忽略空格与标点', () => {
    const chapters = withRanges([
      { title: '第一章 极限', depth: 0, startPage: 1 },
      { title: '第二章 导数', depth: 0, startPage: 3 },
    ], PAGES.length)
    const found = locateChapter(PAGES, chapters, '第一章极限')
    expect(found?.startPage).toBe(1)
    expect(found?.endPage).toBe(2)
  })

  it('没有书签时逐页搜索标题', () => {
    const found = locateChapter(PAGES, [], '第二章 导数')
    expect(found?.startPage).toBe(3)
    expect(found?.endPage).toBe(4)
  })

  it('同名章节按页码范围区分,不会串章', () => {
    const chapters = withRanges([
      { title: '习题', depth: 1, startPage: 1 },
      { title: '习题', depth: 1, startPage: 3 },
    ], PAGES.length)
    expect(chapters[0].endPage).toBe(2)
    expect(chapters[1].endPage).toBe(5)
    expect(chapterKey(chapters[0])).not.toBe(chapterKey(chapters[1]))
    expect(locateChapter(PAGES, chapters, '习题', 1)).toEqual(chapters[0])
    expect(locateChapter(PAGES, chapters, '习题', 3)).toEqual(chapters[1])
    expect(locateChapter(PAGES, chapters, '习题', 4)).toBeNull()
    expect(locateChapter(PAGES, chapters, '习题')).toBeNull()
  })

  it('目录和正文都包含标题时不把目录误认成章节正文', () => {
    const pages = ['目录\n第一章 极限 .... 5', '前言', '第一章 极限\n正文']
    expect(locateChapter(pages, [], '第一章 极限')).toBeNull()
  })

  it('无法确定章节末尾时,不会静默截掉 30 页之后的内容', () => {
    const pages = ['第一章 极限\n正文', ...Array.from({ length: 35 }, () => '正文')]
    expect(locateChapter(pages, [], '第一章 极限')).toBeNull()
  })

  it('找不到返回 null', () => {
    expect(locateChapter(PAGES, [], '不存在的章节')).toBeNull()
  })
})

describe('sliceChapter:章节切片', () => {
  it('只切本章页,不跨到下一章', () => {
    const chapter = { title: '第一章 极限', depth: 0, startPage: 1, endPage: 2 }
    const { text, truncated } = sliceChapter(PAGES, chapter)
    expect(text).toContain('第一章 极限')
    expect(text).toContain('第一章正文续')
    expect(text).not.toContain('第二章')
    expect(truncated).toBe(false)
  })

  it('截断位置不拆开 Unicode 字符', () => {
    const chapter = { title: '章', depth: 0, startPage: 0, endPage: 0 }
    expect(sliceChapter(['甲😀乙'], chapter, 2)).toEqual({ text: '甲', truncated: true })
    expect(sliceChapter(['甲😀乙'], chapter, 3)).toEqual({ text: '甲😀', truncated: true })
  })

  it('超上限截断并标记', () => {
    const chapter = { title: '第一章 极限', depth: 0, startPage: 1, endPage: 2 }
    const { text, truncated } = sliceChapter(PAGES, chapter, 10)
    expect(text).toHaveLength(10)
    expect(truncated).toBe(true)
  })
})

describe('buildChapterMarkdown:本地目录链接', () => {
  it('同名书签的链接包含各自的本地页码', () => {
    const markdown = buildChapterMarkdown([
      { title: '习题', depth: 1, startPage: 1, endPage: 2 },
      { title: '习题', depth: 1, startPage: 3, endPage: 5 },
    ])
    expect(markdown).toContain(encodeURIComponent('习题') + '?page=1')
    expect(markdown).toContain(encodeURIComponent('习题') + '?page=3')
  })

  it('每章一行,标题编码进 cmd 链接', () => {
    const markdown = buildChapterMarkdown([
      { title: '第一章 极限', depth: 0, startPage: 1, endPage: 2 },
      { title: '1.1 数列 [上]', depth: 1, startPage: 1, endPage: 2 },
    ])
    expect(markdown).toContain('[第一章 极限](cmd://chapter/' + encodeURIComponent('第一章 极限') + ')')
    expect(markdown).toContain('1.1 数列 \\[上\\]')
  })
})

describe('normalizeTitle', () => {
  it('去掉空白与标点,保留中英文数字', () => {
    expect(normalizeTitle(' 第 1 章 · 极限 ')).toBe(normalizeTitle('第1章极限'))
  })
})
