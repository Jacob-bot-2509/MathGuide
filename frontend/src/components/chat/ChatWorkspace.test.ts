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

type StreamCall = { prompt?: string; workspace?: string }
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
    expect(wrapper.find('.learn').exists()).toBe(true)
    expect(wrapper.find('.chat-list').exists()).toBe(true)
    wrapper.unmount()
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
})
