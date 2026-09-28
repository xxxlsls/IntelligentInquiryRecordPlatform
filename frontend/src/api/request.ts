/**
 * Axios 请求封装（统一处理后端 ApiResponse 包装与鉴权头）
 *
 * 约定（对应 backend/app/schemas/common.py）：
 * - 所有 JSON 接口响应结构为 { success, code, message, data }；
 * - 拦截器统一解包：success=false 时弹提示并 reject；
 * - 401 会话过期：清除本地凭证并跳转登录页（SE-3）；
 * - 文件下载类接口（responseType=blob）不做 JSON 解包。
 */
import axios, { type AxiosRequestConfig } from 'axios'

import type { ApiResponse } from '@/types'
import { toast } from '@/utils/toast'

/** 本地会话凭证存储键 */
export const TOKEN_KEY = 'ip_token'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 60000,
})

// 请求拦截：附加 JWT 会话凭证（SE-1）
request.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：统一解包 ApiResponse 与错误提示
request.interceptors.response.use(
  (response) => {
    // 文件流响应直接透传
    if (response.config.responseType === 'blob') return response
    const body = response.data as ApiResponse<unknown>
    if (body && body.success === false) {
      toast.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return response
  },
  (error) => {
    const status = error.response?.status
    const message = error.response?.data?.message
    if (status === 401) {
      clearToken()
      toast.error('会话已过期，请重新登录')
      if (!location.hash.startsWith('#/login') && location.pathname !== '/login') {
        location.href = '/login'
      }
    } else {
      toast.error(message || error.message || '网络异常')
    }
    return Promise.reject(error)
  },
)

/** 解包后的 GET 请求：直接返回 data 载荷 */
export async function httpGet<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  const res = await request.get<ApiResponse<T>>(url, { params })
  return res.data.data as T
}

/** 解包后的 POST 请求 */
export async function httpPost<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  const res = await request.post<ApiResponse<T>>(url, data, config)
  return res.data.data as T
}

/** 解包后的 PUT 请求 */
export async function httpPut<T>(url: string, data?: unknown): Promise<T> {
  const res = await request.put<ApiResponse<T>>(url, data)
  return res.data.data as T
}

/** 解包后的 DELETE 请求 */
export async function httpDelete<T>(url: string): Promise<T> {
  const res = await request.delete<ApiResponse<T>>(url)
  return res.data.data as T
}

/** 文件下载：blob 响应转浏览器下载（DOCX 导出 / 材料下载） */
export async function httpDownload(url: string, data?: unknown, fallbackName = 'download'): Promise<void> {
  const res = await request.post<Blob>(url, data, { responseType: 'blob' })
  saveBlob(res.data, parseFileName(res.headers['content-disposition'], fallbackName))
}

/** GET 方式文件下载 */
export async function httpDownloadGet(url: string, fallbackName = 'download'): Promise<void> {
  const res = await request.get<Blob>(url, { responseType: 'blob' })
  saveBlob(res.data, parseFileName(res.headers['content-disposition'], fallbackName))
}

/** 将 Blob 触发浏览器下载 */
function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** 从 Content-Disposition 解析文件名（后端 expose_headers 已暴露） */
function parseFileName(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (star) return decodeURIComponent(star[1])
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1] : fallback
}

export default request
