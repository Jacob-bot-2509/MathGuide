/**
 * 聊天工作区的指令定义(学习辅助 / 科学研究共用)。
 * 功能模块合并进智能答疑对话,以"指令"形式挂在指令栏,点击即执行;
 * 「搜索范围」只属于科研链路,由 ChatWorkspace 按 workspace 过滤,学习区不显示。
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
  { key: '待办清单', icon: '☑' },
  { key: '生成文档', icon: '✎' },
]

/** 科研区指令:不设问题归纳,「问题记录」换成「研究档案」;
 *  「搜索范围」是本区专属链路,保留。 */
export const RESEARCH_COMMANDS: Command[] = [
  { key: '研究档案', icon: '◫' },
  { key: '搜索范围', icon: '⌘' },
  { key: '待办清单', icon: '☑' },
]
