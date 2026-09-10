/**
 * 学习辅助模块的指令定义。
 * 六个模块合并进智能答疑对话:智能答疑是对话本身,
 * 其余五个模块以"指令"形式挂在指令栏,点击即执行。
 */
export interface Command {
  key: string
  label: string
  icon: string
  hint: string
}

export const COMMANDS: Command[] = [
  { key: '概念动画演示', label: '概念动画演示', icon: '▶', hint: '输入想看的数学概念,演示其几何意义' },
  { key: '章节知识导航', label: '章节知识导航', icon: '◈', hint: '查看高等数学章节知识结构' },
  { key: '问题记录', label: '问题记录', icon: '📓', hint: '归纳本:已收纳的问题与参考解答,温故知新' },
  { key: '公式查询手册', label: '公式查询手册', icon: '∫', hint: '查询常用公式与定理' },
  { key: '搜索范围', label: '搜索范围', icon: '⌘', hint: '勾选研究型提问检索的平台,全选即全平台' },
]
// 注:指令的默认提问与多语言提示统一在 utils/i18n.ts(CMD_DEFAULTS / CMD_HINTS),
// 避免两处维护同一份文案;空输入时 LearnView 通过 cmdDefault(cmd) 读取。
