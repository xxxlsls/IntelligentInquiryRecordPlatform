/**
 * 路由配置（对应原型图 6 个核心页面 + 登录页）
 *
 * UI-1 登录/工作台 → /login、/
 * UI-2 案件信息采集 → /intake、/intake/:sessionId
 * UI-3 模板智能匹配 → /templates/:sessionId
 * UI-4 三栏问询工作台 → /workbench/:sessionId
 * UI-5 笔录预览与导出 → /document/:sessionId
 * UI-6 历史笔录导入与回溯 → /history
 */
import { createRouter, createWebHistory } from 'vue-router'

import { getToken } from '@/api/request'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { title: '工作台' },
    },
    {
      path: '/intake',
      name: 'intake-new',
      component: () => import('@/views/CaseIntakeView.vue'),
      meta: { title: '案件基础信息采集' },
    },
    {
      path: '/intake/:sessionId',
      name: 'intake-edit',
      component: () => import('@/views/CaseIntakeView.vue'),
      meta: { title: '案件基础信息采集' },
    },
    {
      path: '/templates/:sessionId',
      name: 'template-match',
      component: () => import('@/views/TemplateMatchView.vue'),
      meta: { title: '问询模板智能匹配' },
    },
    {
      path: '/workbench/:sessionId',
      name: 'workbench',
      component: () => import('@/views/WorkbenchView.vue'),
      meta: { title: '问询工作台' },
    },
    {
      path: '/document/:sessionId',
      name: 'document',
      component: () => import('@/views/DocumentView.vue'),
      meta: { title: '笔录生成与编辑' },
    },
    {
      path: '/history',
      name: 'history',
      component: () => import('@/views/HistoryView.vue'),
      meta: { title: '历史笔录管理' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

// 全局前置守卫：未登录跳转登录页；已登录访问登录页跳转工作台
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !getToken()) {
    return { path: '/login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  if (to.meta.public && getToken()) return { path: '/' }
  // 刷新后恢复用户身份
  if (!to.meta.public && !auth.user) await auth.fetchMe()
  return true
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} - 智能问询笔录平台` : '智能问询笔录平台'
})

export default router
