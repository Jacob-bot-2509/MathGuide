/** 自动拆分自 utils/i18n.ts(按 key 前缀分组,保持键名与顺序不变)。
 *  改文案直接改这里;键的完整性由 `scripts/i18n-test.ts` 与 vitest 守护。
 */
type Dict = Record<string, string>

export const zh: Dict = {
  'common.back': '← 返回',
  'common.backHome': '← 返回首页',
  'common.modelPending': 'MODEL · MG-CORE(待接入)',
  'common.planned': '规划中',
  'common.tbd': '待开发',
  'common.settings': '设置',
  'common.mgLearn': 'MG · LEARN',
  'common.mgResearch': 'MG · RESEARCH',
  'common.cancel': '取消',
  'common.close': '关闭',
}

export const en: Dict = {
  'common.back': '← Back',
  'common.backHome': '← Home',
  'common.modelPending': 'MODEL · MG-CORE (PENDING)',
  'common.planned': 'Planned',
  'common.tbd': 'TBD',
  'common.settings': 'Settings',
  'common.mgLearn': 'MG · LEARN',
  'common.mgResearch': 'MG · RESEARCH',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
}

