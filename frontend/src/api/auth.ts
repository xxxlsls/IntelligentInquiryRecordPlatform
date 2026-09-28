/**
 * BE-1 认证与权限接口（/auth）
 */
import { httpGet, httpPost } from '@/api/request'
import type { LoginResponse, UserInfo } from '@/types'

/** 用户认证登录（FR-3.1.1） */
export function login(officer_no: string, password: string) {
  return httpPost<LoginResponse>('/auth/login', { officer_no, password })
}

/** 会话校验与当前用户 */
export function fetchMe() {
  return httpGet<UserInfo>('/auth/me')
}

/** 登出 */
export function logout() {
  return httpPost<null>('/auth/logout')
}

/** 当前用户权限清单 */
export function fetchPermissions() {
  return httpGet<string[]>('/auth/permissions')
}
