/**
 * 双域部署的工作区判定与跨区跳转。
 *
 * 生产环境:
 *   learn.example.com     → 学习辅助
 *   research.example.com  → 科学研究
 * 浏览器按 origin 分区存储,两个子域的 localStorage/IndexedDB 天然隔离;
 * 登录态走父域 Cookie(MG_COOKIE_DOMAIN),两边共享。
 *
 * 本机/单域部署(localhost、mg.example.com)没有子域区分,
 * 返回 null,路由与请求体里的 workspace 字段照常工作。
 */
import type { Workspace } from '@/stores/sessions'

/** 当前主机对应的固定工作区;未启用子域时返回 null */
export function hostWorkspace(hostname = window.location.hostname): Workspace | null {
  const host = hostname.toLowerCase()
  if (host.startsWith('research.')) return 'research'
  if (host.startsWith('learn.')) return 'learn'
  return null
}

/** 目标区在当前主机是否可直达(单域部署恒为 true) */
export function isSameWorkspaceHost(workspace: Workspace): boolean {
  const current = hostWorkspace()
  return current === null || current === workspace
}

/** 切换子域,保留协议、端口与路径;单域部署返回原路径 */
export function crossWorkspaceHref(workspace: Workspace, path: string): string {
  const current = hostWorkspace()
  if (current === null || current === workspace) return path
  const url = new URL(window.location.href)
  const parts = url.hostname.split('.')
  parts[0] = workspace
  url.hostname = parts.join('.')
  url.pathname = path
  url.search = ''
  url.hash = ''
  return url.toString()
}

/** 路由 → 所属工作区;非两区路由(首页/设置/图谱)返回 null */
export function workspaceOfRoute(path: string): Workspace | null {
  if (path === '/research' || path.startsWith('/research/')) return 'research'
  if (path === '/learn' || path.startsWith('/learn/')) return 'learn'
  return null
}
