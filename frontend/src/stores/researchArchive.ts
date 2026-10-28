/**
 * 科研档案:科学研究工作区的研究目标、思路与资料库。
 * - 与学习辅助的归纳本彻底分开,独立存于 mg-research-archive;
 * - 一个工作区可有多项研究,当前选中项为 activeId;
 * - 资料文件只保存元信息与可提取的正文(浏览器存储配额有限),
 *   二进制原文件不上传,重新获取请回到聊天附件或原出处。
 */
import { reactive } from 'vue'

export type ResearchStatus = 'exploring' | 'active' | 'paused' | 'done'
export type ResearchFileKind = 'image' | 'file'

export interface ResearchProject {
  id: number
  title: string
  goal: string
  approach: string
  notes: string
  status: ResearchStatus
  createdAt: number
  updatedAt: number
}

export interface ResearchFile {
  id: number
  projectId: number | null
  name: string
  size: number
  kind: ResearchFileKind
  /** 可提取的正文(PDF 文本层 / 文本文件),截断保存 */
  text?: string
  addedAt: number
  /** 来源会话与消息(聊天附件自动登记时有值) */
  sessionId?: number
  msgId?: number
}

interface ArchiveState {
  projects: ResearchProject[]
  activeId: number | null
  files: ResearchFile[]
}

const KEY = 'mg-research-archive'
const PROJECT_MAX = 30
const FILE_MAX = 60
export const FILE_TEXT_MAX = 30000

function load(): ArchiveState {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) {
      const p = JSON.parse(raw) as Partial<ArchiveState> | null
      if (p && Array.isArray(p.projects) && Array.isArray(p.files)) {
        return {
          projects: p.projects.filter((x) => x && typeof x.id === 'number') as ResearchProject[],
          activeId: typeof p.activeId === 'number' ? p.activeId : null,
          files: p.files.filter((x) => x && typeof x.id === 'number') as ResearchFile[],
        }
      }
    }
  } catch {
    /* 数据损坏时重置 */
  }
  return { projects: [], activeId: null, files: [] }
}

export const archiveState = reactive<ArchiveState>(load())

function persist(): boolean {
  try {
    localStorage.setItem(KEY, JSON.stringify(archiveState))
    return true
  } catch {
    /* 存储超限(通常是正文过多)时返回 false,由界面提示 */
    return false
  }
}

export function activeProject(): ResearchProject | null {
  return archiveState.projects.find((p) => p.id === archiveState.activeId) ?? null
}

export function createProject(title = ''): ResearchProject {
  const now = Date.now()
  const project: ResearchProject = {
    id: now + Math.floor(Math.random() * 1000),
    title: title.trim() || '未命名研究',
    goal: '',
    approach: '',
    notes: '',
    status: 'exploring',
    createdAt: now,
    updatedAt: now,
  }
  archiveState.projects.unshift(project)
  if (archiveState.projects.length > PROJECT_MAX) archiveState.projects.pop()
  archiveState.activeId = project.id
  persist()
  return project
}

export function updateProject(id: number, patch: Partial<Omit<ResearchProject, 'id' | 'createdAt'>>): void {
  const project = archiveState.projects.find((p) => p.id === id)
  if (!project) return
  Object.assign(project, patch)
  project.updatedAt = Date.now()
  persist()
}

export function removeProject(id: number): void {
  archiveState.projects = archiveState.projects.filter((p) => p.id !== id)
  archiveState.files = archiveState.files.filter((f) => f.projectId !== id)
  if (archiveState.activeId === id) archiveState.activeId = archiveState.projects[0]?.id ?? null
  persist()
}

export function setActiveProject(id: number | null): void {
  archiveState.activeId = id
  persist()
}

/** 登记资料;同名同大小同项目视为同一份,重复导入直接返回已有条目 */
export function addResearchFile(input: Omit<ResearchFile, 'id' | 'addedAt'>): ResearchFile {
  const dup = archiveState.files.find(
    (f) => f.name === input.name && f.size === input.size && f.projectId === input.projectId,
  )
  if (dup) return dup
  const file: ResearchFile = {
    ...input,
    text: input.text?.slice(0, FILE_TEXT_MAX),
    id: Date.now() + Math.floor(Math.random() * 1000),
    addedAt: Date.now(),
  }
  archiveState.files.unshift(file)
  if (archiveState.files.length > FILE_MAX) archiveState.files.pop()
  persist()
  return file
}

export function removeResearchFile(id: number): void {
  archiveState.files = archiveState.files.filter((f) => f.id !== id)
  persist()
}

/** 清空科研档案(设置 → 隐私与安全使用) */
export function clearResearchArchive(): void {
  archiveState.projects = []
  archiveState.activeId = null
  archiveState.files = []
  localStorage.removeItem(KEY)
}
