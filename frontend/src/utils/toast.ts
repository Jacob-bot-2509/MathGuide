/**
 * 全局轻提示:任何页面调用 showToast 即可,App.vue 统一渲染。
 */
import { reactive } from 'vue'

export const toast = reactive({ msg: '' })

let timer: ReturnType<typeof setTimeout> | null = null

export function showToast(msg: string, dur = 2200) {
  toast.msg = msg
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    toast.msg = ''
  }, dur)
}
