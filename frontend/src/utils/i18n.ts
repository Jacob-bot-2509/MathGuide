/**
 * 国际化(简体中文 / English)。
 *
 * 语言由 设置 → 应用 → 语言 控制,存于 settingsState.language;
 * 模板中调用 t('key'),语言切换后自动重新渲染。
 *
 * 词条在 `./i18n/*.ts`(按领域拆:account / chat / common / learn / research),
 * 本文件只负责合并与查询 —— 原先是 2027 行的巨型字典,改一条文案要滚很久。
 * 键的完整性由 `scripts/i18n-test.ts`(ZH/EN 键集合一致 + t() 引用必存在)守护。
 */
import { en as enAccount, zh as zhAccount } from './i18n/account'
import { en as enChat, zh as zhChat } from './i18n/chat'
import { en as enCommon, zh as zhCommon } from './i18n/common'
import { en as enLearn, zh as zhLearn } from './i18n/learn'
import { en as enResearch, zh as zhResearch } from './i18n/research'
import { settingsState } from '@/stores/settings'
import type { AuthMethod } from '@/stores/user'

type Dict = Record<string, string>

const ZH: Dict = {
  ...zhAccount,
  ...zhChat,
  ...zhCommon,
  ...zhLearn,
  ...zhResearch,
}

const EN: Dict = {
  ...enAccount,
  ...enChat,
  ...enCommon,
  ...enLearn,
  ...enResearch,
}

export function t(key: string, params?: Record<string, string | number>): string {
  const raw = settingsState.language === 'en' ? EN[key] : ZH[key]
  let s = raw ?? ZH[key] ?? key
  if (params) {
    for (const [k, v] of Object.entries(params)) s = s.replace(`{${k}}`, String(v))
  }
  return s
}

/* ---------- 动态内容:板块 / 指令 / 登录方式 ---------- */

const CAT_NAMES: Record<string, [string, string]> = {
  analysis: ['数学分析', 'Mathematical Analysis'],
  algebra: ['高等代数', 'Advanced Algebra'],
  numberTheory: ['数论', 'Number Theory'],
  geometry: ['空间解析几何', 'Analytic Geometry'],
  ode: ['微分方程', 'Differential Equations'],
  probability: ['概率论与数理统计', 'Probability & Mathematical Statistics'],
  complex: ['复变函数', 'Complex Analysis'],
  topology: ['拓扑学', 'Topology'],
  other: ['未归类', 'Uncategorized'],
}

export function catName(key: string): string {
  const pair = CAT_NAMES[key]
  return pair ? (settingsState.language === 'en' ? pair[1] : pair[0]) : key
}

const CMD_NAMES: Record<string, [string, string]> = {
  学习分析: ['学习分析', 'Learning Analysis'],
  章节知识导航: ['章节知识导航', 'Chapter Navigator'],
  问题记录: ['问题记录', 'Question Notebook'],
  研究档案: ['研究档案', 'Research Archive'],
  公式查询手册: ['公式查询手册', 'Formula Handbook'],
  搜索范围: ['搜索范围', 'Search Scope'],
  待办清单: ['待办清单', 'To-do List'],
  生成文档: ['生成文档', 'Generate Document'],
}

const CMD_HINTS: Record<string, [string, string]> = {
  学习分析: ['根据知识图谱上的诊断进度,分析掌握结构、瓶颈与下一步', 'Analyze mastery structure, bottlenecks and next steps from your graph progress'],
  章节知识导航: ['上传或粘贴教材后,一键划分章节;点击章节查看知识指引', 'Upload or paste a textbook to get its chapter list; tap a chapter for guidance'],
  问题记录: ['归纳本:已收纳的问题与参考解答,温故知新', 'Notebook: saved questions with answers and approaches for review'],
  研究档案: ['研究目标、思路与资料库:记录项目、导入论文与笔记', 'Research goals, approach and a materials library for each project'],
  公式查询手册: ['查询常用公式与定理', 'Look up common formulas and theorems'],
  搜索范围: ['勾选研究型提问要检索的平台(全选即全平台)', 'Pick which platforms research questions search'],
  待办清单: ['设置一次性 / 每天 / 周期性任务,到点提醒', 'Set one-off, daily or weekly reminders'],
  生成文档: ['按当前对话、问题归纳或自定义要求生成文档', 'Generate a document from this chat, notebook or a custom request'],
}

const CMD_DEFAULTS: Record<string, [string, string]> = {
  学习分析: ['分析我的学习进度', 'Analyze my learning progress'],
  章节知识导航: ['高等数学章节结构', 'Chapter structure of higher mathematics'],
  问题记录: ['问题记录本', 'My question notebook'],
  公式查询手册: ['常用公式速查', 'Common formulas at a glance'],
  待办清单: ['待办清单', 'To-do list'],
}

function pick(pair: [string, string] | undefined, key: string): string {
  return pair ? (settingsState.language === 'en' ? pair[1] : pair[0]) : key
}

export function cmdName(key: string): string {
  return pick(CMD_NAMES[key], key)
}

export function cmdHint(key: string): string {
  return pick(CMD_HINTS[key], '')
}

export function cmdDefault(key: string): string {
  return pick(CMD_DEFAULTS[key], key)
}

const AUTH_NAMES: Record<AuthMethod, [string, string]> = {
  'phone-pass': ['手机号 + 密码', 'Phone + Password'],
  'phone-code': ['手机号 + 验证码', 'Phone + SMS Code'],
  wechat: ['微信登录', 'WeChat'],
  qq: ['QQ 登录', 'QQ'],
}

const REALNAME_TEXTS: Record<AuthMethod, [string, string]> = {
  'phone-pass': ['仅手机号登录,未做实名核验', 'Phone sign-in only; no identity verification'],
  'phone-code': ['仅手机号登录,未做实名核验', 'Phone sign-in only; no identity verification'],
  wechat: ['模拟授权,未做实名核验', 'Simulated authorization; no identity verification'],
  qq: ['模拟授权,未做实名核验', 'Simulated authorization; no identity verification'],
}

export function authName(method: AuthMethod): string {
  return pick(AUTH_NAMES[method], method)
}

export function realnameText(method: AuthMethod): string {
  return pick(REALNAME_TEXTS[method], '')
}
