/**
 * i18n 运行时查询测试(字典本身由 i18n.test.ts 守护键集合)。
 *
 * 这一层负责「按当前语言取值 + 缺词回退」:查不到时必须退回中文再退回 key,
 * 绝不能把 undefined 渲染到界面上;动态名字(板块/指令/登录方式)同理。
 */
import { afterEach, describe, expect, it } from 'vitest'
import { settingsState } from '@/stores/settings'
import { authName, catName, cmdDefault, cmdHint, cmdName, realnameText, t } from '@/utils/i18n'

const original = settingsState.language

afterEach(() => {
  settingsState.language = original
})

function useLanguage(language: 'zh' | 'en') {
  settingsState.language = language
}

describe('t / 基础取值', () => {
  it('中文为默认语言', () => {
    useLanguage('zh')
    expect(t('settings.items', { n: 3 })).toBe('3 条')
  })

  it('切到英文后取英文词条', () => {
    useLanguage('en')
    // 英文文案省略量词,只有占位符
    expect(t('settings.items', { n: 3 })).toBe('3')
    expect(t('acc.deleteWordPh', { word: 'DELETE' })).toContain('DELETE')
  })

  it('缺词回退顺序:当前语言 → 中文 → key 原文', () => {
    useLanguage('en')
    // 两边都没有的 key 原样返回,便于在界面上一眼看出漏翻译
    expect(t('no.such.key')).toBe('no.such.key')
    useLanguage('zh')
    expect(t('no.such.key')).toBe('no.such.key')
  })

  it('占位符按参数替换;同一占位符出现多次只替换第一处(既有行为)', () => {
    useLanguage('zh')
    expect(t('settings.items', { n: 7, extra: 'x' })).toBe('7 条')
    expect(t('acc.deleteWarnWord', { word: '删除' })).toContain('删除')
    // 未提供参数时保留 {n} 原文,而不是抛错
    expect(t('settings.items')).toBe('{n} 条')
  })

  it('数字参数自动转字符串', () => {
    useLanguage('zh')
    expect(t('privacy.serverTotal', { total: 0 })).toContain('0')
  })
})

describe('catName / 板块名', () => {
  it('已知板块双语可用', () => {
    useLanguage('zh')
    expect(catName('analysis')).toBe('数学分析')
    useLanguage('en')
    expect(catName('analysis')).toBe('Mathematical Analysis')
    expect(catName('other')).toBe('Uncategorized')
  })

  it('未知板块返回 key 本身(数据库里的新板块不会显示空白)', () => {
    expect(catName('quantum')).toBe('quantum')
  })

  it('全部已知板块都有两种语言', () => {
    for (const key of ['analysis', 'algebra', 'numberTheory', 'geometry', 'ode', 'probability', 'complex', 'topology']) {
      useLanguage('zh')
      const zh = catName(key)
      useLanguage('en')
      const en = catName(key)
      expect(zh.length).toBeGreaterThan(0)
      expect(en.length).toBeGreaterThan(0)
      expect(en).not.toBe(zh)
    }
  })
})

describe('cmdName / cmdHint / cmdDefault', () => {
  it('已知指令返回双语文案', () => {
    useLanguage('zh')
    expect(cmdName('待办清单')).toBe('待办清单')
    expect(cmdHint('待办清单').length).toBeGreaterThan(0)
    expect(cmdDefault('待办清单')).toBe('待办清单')
    useLanguage('en')
    expect(cmdName('待办清单')).toBe('To-do List')
  })

  it('未知指令:名字与默认值退回 key,提示语为空串', () => {
    expect(cmdName('不存在')).toBe('不存在')
    expect(cmdDefault('不存在')).toBe('不存在')
    expect(cmdHint('不存在')).toBe('')
  })

  it('没有默认值的指令退回 key(如 搜索范围)', () => {
    useLanguage('zh')
    expect(cmdName('搜索范围')).toBe('搜索范围')
    expect(cmdDefault('搜索范围')).toBe('搜索范围')
  })
})

describe('authName / realnameText', () => {
  it('四种登录方式都有名称与实名说明', () => {
    useLanguage('zh')
    expect(authName('phone-pass')).toBe('手机号 + 密码')
    expect(authName('phone-code')).toBe('手机号 + 验证码')
    expect(authName('wechat')).toBe('微信登录')
    expect(authName('qq')).toBe('QQ 登录')
    expect(realnameText('wechat')).toContain('模拟授权')
    expect(realnameText('phone-pass')).toContain('手机号')
  })

  it('英文界面下返回英文', () => {
    useLanguage('en')
    expect(authName('wechat')).toBe('WeChat')
    expect(authName('qq')).toBe('QQ')
    expect(realnameText('qq')).toContain('Simulated')
  })

  it('未知登录方式:名称退回 key,实名说明为空串', () => {
    expect(authName('unknown' as never)).toBe('unknown')
    expect(realnameText('unknown' as never)).toBe('')
  })
})
