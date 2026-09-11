/**
 * SSE 收尾契约自测(前端无运行时,经 esbuild 打包后用 node 执行):
 *   npx esbuild scripts/sse-stream-test.ts --bundle --format=cjs --define:import.meta.env='{}' --outfile=.sse-stream-test.cjs && node .sse-stream-test.cjs
 *
 * 盯的是这个 bug:后端连接断在 [DONE] 之前时,前端原先无从分辨,
 * 把半截回答当完整回答交付(存进历史、写进语音转换缓存)。
 * 用例覆盖 postSSE 的四种收尾:完整 / 截断 / 截断且用户已取消 / 读取报错。
 */
/* eslint-disable */
declare const process: { exit(code: number): void }

import { postSSE } from '../src/api/http'

const enc = new TextEncoder()

interface FakeOpts {
  /** 读到第 n 帧时让流报错(模拟网络中断) */
  errorAt?: number
  /** 读到第 n 帧时触发 AbortController(模拟用户点停止) */
  abortAt?: number
  controller?: AbortController
}

/** 造一个只吐给定帧的假响应:帧发完就干净关闭(不补 [DONE],交给用例自己带) */
function fakeResponse(frames: string[], opts: FakeOpts = {}) {
  let i = 0
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (opts.errorAt !== undefined && i === opts.errorAt) {
        controller.error(new Error('connection dropped'))
        return
      }
      if (opts.abortAt !== undefined && i === opts.abortAt) {
        opts.controller?.abort()
        controller.error(new Error('aborted'))
        return
      }
      if (i >= frames.length) {
        controller.close()
        return
      }
      controller.enqueue(enc.encode(frames[i++]))
    },
  })
  return { ok: true, status: 200, body } as unknown as Response
}

interface Outcome {
  full: string
  complete: boolean | null
  errors: number
  meta: Record<string, unknown> | null
}

/** 跑一次 postSSE,回收它回调出来的事实 */
async function run(frames: string[], opts: FakeOpts = {}): Promise<Outcome> {
  const out: Outcome = { full: '', complete: null, errors: 0, meta: null }
  const controller = opts.controller ?? new AbortController()
  const realFetch = globalThis.fetch
  globalThis.fetch = (() => Promise.resolve(fakeResponse(frames, { ...opts, controller }))) as typeof fetch
  try {
    await postSSE(
      '/api/chat/stream',
      {},
      {
        onDelta: () => {},
        onDone: (full, complete) => {
          out.full = full
          out.complete = complete
        },
        onMeta: (meta) => {
          out.meta = meta
        },
        onError: () => {
          out.errors++
        },
      },
      { controller },
    ).catch(() => {
      /* 读取失败由 onError 记录 */
    })
  } finally {
    globalThis.fetch = realFetch
  }
  return out
}

const frame = (s: string) => `data: ${JSON.stringify(s)}\n\n`
const DONE = 'data: [DONE]\n\n'

let passed = 0
const failed: string[] = []

function check(name: string, got: unknown, want: unknown) {
  if (JSON.stringify(got) === JSON.stringify(want)) {
    passed++
  } else {
    failed.push(`✗ ${name}\n    期望: ${JSON.stringify(want)}\n    实际: ${JSON.stringify(got)}`)
  }
}

async function main() {
  // ① 完整流:有 [DONE] 收尾
  let r = await run([frame('泰'), frame('勒'), DONE])
  check('完整流:文字拼齐', r.full, '泰勒')
  check('完整流:complete=true', r.complete, true)
  check('完整流:无错误', r.errors, 0)

  // ② 截断流:帧发完就干净关闭,没有 [DONE] —— 这正是后端被重启时的样子
  r = await run([frame('泰'), frame('勒')])
  check('截断流:已收到的字保留', r.full, '泰勒')
  check('截断流:complete=false(不得当完整回答)', r.complete, false)
  check('截断流:干净关闭不报错', r.errors, 0)

  // ③ 截断且用户已取消:自己掐的不算被中断,否则界面会误标「已中断」
  const ac = new AbortController()
  r = await run([frame('泰'), frame('勒')], { abortAt: 1, controller: ac })
  check('用户取消:complete=true(不算中断)', r.complete, true)
  check('用户取消:不触发 onError', r.errors, 0)

  // ④ 读取中途报错:按错误收尾,同样不许当完整
  r = await run([frame('泰'), frame('勒')], { errorAt: 1 })
  check('读取报错:触发 onError', r.errors, 1)
  check('读取报错:complete=false', r.complete, false)

  // ⑤ 空流:后端全程无内容但补了 [DONE](如空语音转写)
  r = await run([DONE])
  check('空流:full 为空', r.full, '')
  check('空流:complete=true', r.complete, true)

  // ⑥ [DONE] 与数据同批到达:分帧边界不该影响判定
  r = await run([frame('泰') + DONE])
  check('同批到达:文字不漏', r.full, '泰')
  check('同批到达:complete=true', r.complete, true)

  // ⑦ 元信息对象帧:单独回调 onMeta,不混进正文
  r = await run(['data: {"mg_meta":{"research":true}}\n\n', frame('泰'), DONE])
  check('meta 帧:onMeta 收到研究标记', r.meta, { mg_meta: { research: true } })
  check('meta 帧:不混入正文', r.full, '泰')
  check('meta 帧:complete 正常', r.complete, true)

  console.log(`\nSSE 收尾契约自测:${passed}/${passed + failed.length} 通过`)
  for (const f of failed) console.log(f)
  if (failed.length) process.exit(1)
}

void main()
