/**
 * 认证状态管理（Pinia）
 *
 * 持有 JWT 会话凭证与当前用户身份（SE-1），
 * 登录态持久化于 localStorage，路由守卫据此拦截。
 */
import { defineStore } from 'pinia'

import * as authApi from '@/api/auth'
import { clearToken, getToken, setToken } from '@/api/request'
import type { UserInfo } from '@/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null as UserInfo | null,
  }),
  getters: {
    isLogin: (state) => !!state.token,
    /** 是否办案民警（笔录写操作角色） */
    isOfficer: (state) => state.user?.role === 'case_officer',
    userName: (state) => state.user?.name ?? '',
  },
  actions: {
    /** 登录并持久化凭证 */
    async login(officerNo: string, password: string) {
      const res = await authApi.login(officerNo, password)
      this.token = res.access_token
      this.user = res.user
      setToken(res.access_token)
    },
    /** 拉取当前用户（刷新页面后恢复身份） */
    async fetchMe() {
      if (!this.token) return
      try {
        this.user = await authApi.fetchMe()
      } catch {
        // 凭证失效由拦截器统一处理（清 token + 跳登录）
        this.user = null
      }
    },
    /** 登出（后端会话注销 + 本地清理） */
    async logout() {
      try {
        await authApi.logout()
      } finally {
        this.token = ''
        this.user = null
        clearToken()
      }
    },
  },
})
