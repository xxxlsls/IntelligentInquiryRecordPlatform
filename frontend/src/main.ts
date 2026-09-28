/**
 * 前端应用入口
 *
 * 装配 Pinia 状态管理、Vue Router 路由与全局样式（深色主题）。
 */
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from '@/App.vue'
import router from '@/router'
import '@/styles/theme.css'

createApp(App).use(createPinia()).use(router).mount('#app')
