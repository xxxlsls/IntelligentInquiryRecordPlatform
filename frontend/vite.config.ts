/**
 * Vite 构建配置
 *
 * - 别名 @ → src，简化模块导入；
 * - 开发服务器将 /api 代理到后端 FastAPI（默认 http://127.0.0.1:8000），
 *   与后端 CORS 配置互补，前端统一使用相对路径 /api/v1 调用接口。
 */
import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // 后端 API 代理（backend/app/main.py 挂载前缀 /api/v1）
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
