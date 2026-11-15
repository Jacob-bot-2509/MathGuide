/** 左右分栏:比例与像素下限的换算、本地比例的读取。
 *
 * 检索分栏(`mg-research-split`)与图解放大(`mg-diagram-split`)都把「右栏宽度」
 * 存成 0..1 的比例,换算规则一致却原本分散在两个组件函数里,因此集中到此,
 * 由单测固定边界 —— 尤其是「容器还没量到宽度」的那一刻。
 */

export const SPLIT_DEFAULT = 0.4
export const SEARCH_MIN_PX = 320
export const CHAT_MIN_PX = 380
/** 低于这个窗口宽度不再并排分栏,改用浮层或独立页面。 */
export const SPLIT_MIN_WIDTH = 1100

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value))
}

/**
 * 把右栏比例夹到「左右两栏都放得下各自最小宽度」的区间。
 *
 * `width` 为 0 表示容器还没挂载、还没量到宽:此时只做 0..1 兜底,不按像素夹取。
 * 早期实现这一步也按 [0.4, 0.6] 夹,于是存下来的 0.68 一刷新就被改成 0.6
 * (用户以为拖拽没被记住)。真正的像素夹取应发生在拿到实测宽度之后。
 */
export function clampSplitRatio(value: number, width: number): number {
  if (!Number.isFinite(value)) return SPLIT_DEFAULT
  if (!Number.isFinite(width) || width <= 0) return clamp(value, 0, 1)
  if (width >= SEARCH_MIN_PX + CHAT_MIN_PX) {
    return clamp(value, SEARCH_MIN_PX / width, 1 - CHAT_MIN_PX / width)
  }
  // 空间不够并排:收在一个居中窄区间,至少不把聊天区挤没
  return clamp(value, 0.4, 0.6)
}

/** 解析 localStorage 里的比例字符串;空值、NaN、非正数一律回退默认值。 */
export function parseStoredRatio(raw: string | null, fallback: number): number {
  const value = Number(raw)
  return Number.isFinite(value) && value > 0 ? value : fallback
}
