// @vitest-environment happy-dom
/**
 * ChatWorkspace 组件级测试(vitest + happy-dom + @vue/test-utils)。
 *
 * 目的:给 SSE / 持久化 / 附件这三块「只能人工冒烟」的逻辑建立可重复的断言基线,
 * 之后把它们抽成 composable 时,行为一旦变化就会被这里拦住。
 *
 * 驱动方式刻意只用**公开面**:挂载、改输入框、按回车、读 localStorage 与 fetch 调用,
 * 不去碰组件内部状态(`<script setup>` 也不暴露)—— 这样提取 composable 后测试无需改写。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { shallowMount } from '@vue/test-utils'
import ChatWorkspace from '@/components/chat/ChatWorkspace.vue'
import { SESSIONS_KEYS, clearAllSessions, sessionStore } from '@/stores/sessions'

/** 后端「欢迎语」是罐头文案,这里用两段增量模拟,末帧必须是 [DONE] */
const REPLY = ['你好,我是', '数学助手']

/** 构造一个 postSSE 能消费的最小响应:body.getReader() 逐块返回 data: 行 */
function sseResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  const parts = [
    ...chunks.map((chunk) => encoder.encode(`data: ${JSON.stringify(chunk)}\n`)),
    encoder.encode('data: [DONE]\n'),
  ]
  let index = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => (index < parts.length
          ? { done: false, value: parts[index++] }
          : { done: true, value: undefined }),
      }),
    },
  }
}

type StreamCall = { prompt?: string; workspace?: string; profile?: string; verify?: boolean }
const calls: StreamCall[] = []

function stubFetch(chunks: string[] = REPLY) {
  vi.stubGlobal('fetch', vi.fn(async (url: unknown, init?: { body?: string }) => {
    if (String(url).includes('/api/chat/stream')) {
      try {
        calls.push(JSON.parse(init?.body ?? '{}') as StreamCall)
      } catch {
        calls.push({})
      }
      return sseResponse(chunks)
    }
    return { ok: true, status: 200, json: async () => ({}), text: async () => '{}' }
  }))
}

const wait = (ms = 60) => new Promise((resolve) => setTimeout(resolve, ms))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/:pathMatch(.*)*', component: { template: '<div />' } },
    ],
  })
}

async function mountWorkspace(workspace: 'learn' | 'research' = 'learn') {
  const router = makeRouter()
  await router.push('/')
  await router.isReady()
  const wrapper = shallowMount(ChatWorkspace, {
    props: { workspace },
    global: { plugins: [router] },
  })
  return wrapper
}

function savedSessions(workspace: 'learn' | 'research') {
  const raw = localStorage.getItem(SESSIONS_KEYS[workspace])
  return (JSON.parse(raw ?? '{"sessions":[]}') as {
    sessions: Array<{ id: number; messages: Array<{ role: string; content: string; streaming?: boolean }> }>
  }).sessions
}

beforeEach(() => {
  calls.length = 0
  vi.unstubAllGlobals()
  clearAllSessions()
  localStorage.clear()
  stubFetch()
})

describe('ChatWorkspace 挂载与外壳', () => {
  it('学习区能挂载并渲染对话列表与输入框', async () => {
    const wrapper = await mountWorkspace('learn')
    expect(wrapper.find('.learn').exists()).toBe(true)
    expect(wrapper.find('.chat-list').exists()).toBe(true)
    expect(wrapper.find('textarea.input').exists()).toBe(true)
    wrapper.unmount()
  })

  it('科研区能挂载(走独占的检索链路)', async () => {
    const wrapper = await mountWorkspace('research')
    expect(wrapper.find('.learn.ws-research').exists()).toBe(true)
    expect(wrapper.find('.sci-rail').exists()).toBe(true)
    expect(wrapper.find('.chat-list').exists()).toBe(true)
    wrapper.unmount()
  })

  it('左侧科研仪器栏支持折叠展开并持久化状态', async () => {
    const wrapper = await mountWorkspace('learn')
    expect(wrapper.find('.learn.ws-learn.rail-open').exists()).toBe(true)
    const toggle = wrapper.find('button.rail-toggle')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    expect(wrapper.find('.learn.rail-open').exists()).toBe(false)
    expect(localStorage.getItem('mg-rail-open')).toBe('0')

    await toggle.trigger('click')
    expect(wrapper.find('.learn.rail-open').exists()).toBe(true)
    expect(localStorage.getItem('mg-rail-open')).toBe('1')
    wrapper.unmount()
  })

  it('右侧科研演示台支持开关、多子窗口排版、折叠最大化与持久化', async () => {
    const wrapper = await mountWorkspace('research')
    try {
      const stageBtn = wrapper.find('button.stage-toggle')
      expect(stageBtn.exists()).toBe(true)
      expect(wrapper.find('.learn.stage-open').exists()).toBe(false)

      await stageBtn.trigger('click')
      expect(wrapper.find('.learn.stage-open').exists()).toBe(true)
      expect(wrapper.find('.stage-pane').exists()).toBe(true)
      expect(localStorage.getItem('mg-stage-open')).toBe('1')

      // 科研区有 图解 / 文件与资料 / 文献阅读 三个标签
      const tabs = wrapper.findAll('.stage-tab')
      expect(tabs.length).toBe(3)
      await tabs[1].trigger('click')
      expect(tabs[1].classes()).toContain('on')

      // 方案 A: 默认上下双窗模式同时承载 2 个子窗口 + 横向分隔条
      expect(wrapper.find('.stage-h-divider').exists()).toBe(true)
      expect(wrapper.find('[data-subwin="figures"]').attributes('style') ?? '').not.toContain('display: none')
      expect(wrapper.find('[data-subwin="files"]').attributes('style') ?? '').not.toContain('display: none')

      // 切换单窗 / 多窗布局并持久化
      await wrapper.find('.layout-btn[data-layout="single"]').trigger('click')
      expect(localStorage.getItem('mg-stage-layout')).toBe('single')
      expect(wrapper.find('.stage-h-divider').exists()).toBe(false)

      await wrapper.find('.layout-btn[data-layout="stack"]').trigger('click')
      expect(localStorage.getItem('mg-stage-layout')).toBe('stack')

      // 打开第三个子窗(文献阅读)并测试独立折叠与最大化
      await tabs[2].trigger('click')
      expect(wrapper.find('[data-subwin="reader"]').attributes('style') ?? '').not.toContain('display: none')
      await wrapper.find('[data-subwin="files"] .subwin-collapse').trigger('click')
      expect(wrapper.find('[data-subwin="files"]').classes()).toContain('subwin--collapsed')

      await wrapper.find('[data-subwin="figures"] .subwin-max').trigger('click')
      expect(wrapper.find('[data-subwin="figures"] .subwin-max').text()).toBe('⤡')
      expect(wrapper.find('[data-subwin="figures"]').attributes('style') ?? '').not.toContain('display: none')
      expect(wrapper.find('[data-subwin="files"]').attributes('style') ?? '').toContain('display: none')

      // 还原并关闭单个子窗
      await wrapper.find('[data-subwin="figures"] .subwin-max').trigger('click')
      await wrapper.find('[data-subwin="files"] .subwin-close').trigger('click')
      expect(wrapper.find('[data-subwin="files"]').attributes('style') ?? '').toContain('display: none')
      expect(wrapper.find('.learn.stage-open').exists()).toBe(true)

      await wrapper.find('button.stage-close').trigger('click')
      expect(wrapper.find('.learn.stage-open').exists()).toBe(false)
      expect(localStorage.getItem('mg-stage-open')).toBe('0')
    } finally {
      wrapper.unmount()
    }
  })
})

describe('ChatWorkspace 流式回复', () => {
  it('进入面板即请求欢迎语,流结束后内容落盘且不再是生成中', async () => {
    const wrapper = await mountWorkspace('learn')
    await wait(80)

    expect(calls.length).toBeGreaterThan(0)
    expect(calls[0].prompt).toBe('')
    expect(calls[0].workspace).toBe('learn')

    // 内存态:流已收尾。streaming / thinking 是瞬时标记,故意不落盘(见 sessions.ts 白名单)
    const live = sessionStore('learn').state.sessions[0]?.messages.at(-1)
    expect(live?.content).toBe('你好,我是数学助手')
    expect(live?.streaming).toBe(false)

    // 落盘:persistSessions 是 120ms debounce,等它写完
    await wait(200)
    expect(savedSessions('learn')[0].messages.at(-1)?.content).toBe('你好,我是数学助手')
    wrapper.unmount()
  })

  it('输入框回车发出一次流式请求,请求体带问句与工作区', async () => {
    const wrapper = await mountWorkspace('learn')
    await wait()

    const textarea = wrapper.find('textarea.input')
    await textarea.setValue('什么是导数')
    await textarea.trigger('keydown.enter')
    // 用户提问后先「思考」450ms 再开始流式
    await wait(600)

    const sent = calls.find((c) => c.prompt === '什么是导数')
    expect(sent).toBeTruthy()
    expect(sent?.workspace).toBe('learn')

    const messages = savedSessions('learn').flatMap((s) => s.messages)
    const asked = messages.find((m) => m.role === 'user' && m.content === '什么是导数')
    expect(asked).toBeTruthy()
    wrapper.unmount()
  })

  it('标题在目录和正文均出现时提示无法定位,不请求通用知识', async () => {
    const books = await import('@/utils/bookStore')
    const load = vi.spyOn(books, 'loadBook').mockResolvedValue({
      hash: 'ambiguous-book', name: 'book.pdf', pageCount: 2,
      pages: ['目录\n第一章 .... 2', '第一章\n正文'], outline: [],
      createdAt: 0, lastUsedAt: 0, size: 20,
    })
    const touch = vi.spyOn(books, 'touchBook').mockResolvedValue(undefined)
    const wrapper = await mountWorkspace('learn')
    await wait(100)
    const session = sessionStore('learn').state.sessions[0]
    session.messages.push({ id: 987653, role: 'user', content: 'book.pdf',
      attachment: { kind: 'file', name: 'book.pdf', bookId: 'ambiguous-book' } })
    const priorCalls = calls.length
    const vm = wrapper.vm as unknown as { onNavChapter: (name: string) => void }
    vm.onNavChapter('第一章')
    await vi.waitFor(() => {
      expect(session.messages.at(-1)?.content).toContain('无法可靠定位该章节')
    })
    await wait(500)
    expect(calls).toHaveLength(priorCalls)
    expect(session.messages.at(-1)?.navGuideFor).toBeUndefined()
    wrapper.unmount()
    load.mockRestore()
    touch.mockRestore()
  })

  it('教材缓存丢失时提示重新上传,不请求通用知识冒充章节', async () => {
    const wrapper = await mountWorkspace('learn')
    await wait(100)
    const session = sessionStore('learn').state.sessions[0]
    session.messages.push({
      id: 987654, role: 'user', content: 'book.pdf',
      attachment: { kind: 'file', name: 'book.pdf', bookId: 'missing-book' },
    })
    const priorCalls = calls.length
    const vm = wrapper.vm as unknown as { onNavChapter: (name: string) => void }
    vm.onNavChapter('第一章')
    await vi.waitFor(() => {
      expect(session.messages.at(-1)?.content).toContain('教材缓存已失效')
    })
    await wait(500)
    expect(calls).toHaveLength(priorCalls)
    expect(session.messages.at(-1)?.navGuideFor).toBeUndefined()
    wrapper.unmount()
  })

  it('两个工作区各自存档,互不串档', async () => {
    const learn = await mountWorkspace('learn')
    await wait()
    learn.unmount()

    const research = await mountWorkspace('research')
    await wait()
    research.unmount()

    expect(savedSessions('learn').length).toBeGreaterThan(0)
    expect(savedSessions('research').length).toBeGreaterThan(0)
    const learnId = savedSessions('learn')[0].id
    const researchId = savedSessions('research')[0].id
    expect(learnId).not.toBe(researchId)
  })

  it('以研促学桥接:学习区挂载时自动消费 mg-learn-seed 与 mg-learn-origin 并展示回跳条', async () => {
    sessionStorage.setItem('mg-learn-seed', '请帮我夯实谱隙估计的前置理论')
    sessionStorage.setItem('mg-learn-origin', JSON.stringify({
      workspace: 'research',
      sessionId: 42,
      label: 'Spectral Gap Paper',
    }))
    const wrapper = await mountWorkspace('learn')
    try {
      await wait(600)
      expect(sessionStorage.getItem('mg-learn-seed')).toBeNull()
      expect(sessionStorage.getItem('mg-learn-origin')).toBeNull()
      const sent = calls.find((c) => c.prompt === '请帮我夯实谱隙估计的前置理论')
      expect(sent).toBeTruthy()
      expect(sent?.workspace).toBe('learn')
      expect(wrapper.find('.origin-banner').exists()).toBe(true)
      expect(wrapper.find('.origin-banner').text()).toContain('Spectral Gap Paper')
    } finally {
      wrapper.unmount()
    }
  })

  it('科研区 AI4S 工具条:开启双角色复核后透传 verify=true,且不渲染多余人设模式栏与侧栏图谱按钮', async () => {
    const wrapper = await mountWorkspace('research')
    try {
      await wait()
      expect(wrapper.find('.profile-strip').exists()).toBe(false)
      const verifyBtn = wrapper.find('[data-ai4s-tool="verify"]')
      expect(verifyBtn.exists()).toBe(true)
      await verifyBtn.trigger('click')
      const input = wrapper.find('textarea.input')
      await input.setValue('核验谱隙定理的收敛边界')
      await input.trigger('keydown.enter')
      await wait(600)
      const sent = calls.find((c) => c.prompt === '核验谱隙定理的收敛边界')
      expect(sent?.verify).toBe(true)
    } finally {
      wrapper.unmount()
    }
  })
})
