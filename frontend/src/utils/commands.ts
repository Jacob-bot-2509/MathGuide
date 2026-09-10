/**
 * 学习辅助模块的指令定义。
 * 六个模块合并进智能答疑对话:智能答疑是对话本身,
 * 其余五个模块以"指令"形式挂在指令栏,点击即执行。
 */
export interface Command {
  /** 契约键:与后端 cmd 字段一致,也是 i18n 文案表的查表键 */
  key: string
  icon: string
}

/** 指令栏条目:只留结构与图标,文案(名称/提示/默认提问)统一由
 * utils/i18n.ts 的 CMD_NAMES / CMD_HINTS / CMD_DEFAULTS 提供 —— 那里才有中英双语。
 * 曾在这里挂过一份中文 label/hint,结果两处说法逐渐分叉且英文界面无文案可用 */
export const COMMANDS: Command[] = [
  { key: '概念动画演示', icon: '▶' },
  { key: '章节知识导航', icon: '◈' },
  { key: '问题记录', icon: '📓' },
  { key: '公式查询手册', icon: '∫' },
  { key: '搜索范围', icon: '⌘' },
]
