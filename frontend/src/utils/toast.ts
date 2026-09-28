/**
 * 轻量 Toast 轻提示（无 UI 组件库依赖）
 *
 * 全局单例容器，供 API 拦截器与各视图统一调用：
 * toast.success / toast.error / toast.info
 */

type ToastType = 'success' | 'error' | 'info'

let wrap: HTMLDivElement | null = null

/** 获取（懒创建）Toast 容器 */
function getWrap(): HTMLDivElement {
  if (wrap && document.body.contains(wrap)) return wrap
  wrap = document.createElement('div')
  wrap.className = 'toast-wrap'
  document.body.appendChild(wrap)
  return wrap
}

/** 展示一条轻提示，duration 毫秒后自动消失 */
function show(type: ToastType, message: string, duration = 2600): void {
  const el = document.createElement('div')
  el.className = `toast ${type}`
  // 状态圆点 + 文本
  const dot = document.createElement('span')
  dot.className = 'dot'
  dot.style.background =
    type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--error)' : 'var(--primary)'
  const text = document.createElement('span')
  text.textContent = message
  el.appendChild(dot)
  el.appendChild(text)
  getWrap().appendChild(el)
  window.setTimeout(() => el.remove(), duration)
}

export const toast = {
  success: (msg: string, duration?: number) => show('success', msg, duration),
  error: (msg: string, duration?: number) => show('error', msg, duration),
  info: (msg: string, duration?: number) => show('info', msg, duration),
}
