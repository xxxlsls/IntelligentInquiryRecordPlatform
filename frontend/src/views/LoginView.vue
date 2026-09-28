/**
 * UI-1 登录页（FR-3.1.1 用户认证登录）
 *
 * 深色现代化登录界面：警号 + 密码登录，演示账号快捷填充；
 * 登录成功后跳转工作台（或 redirect 回原目标页）。
 */
<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/utils/toast'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const officerNo = ref('')
const password = ref('')
const loading = ref(false)

/** 演示账号（AC-1 验收账号，一键填充便于演示） */
const DEMO_ACCOUNTS = [
  { no: 'P10001', pwd: 'Officer@123', label: '办案民警' },
  { no: 'A20001', pwd: 'Analyst@123', label: '反诈研判员' },
  { no: 'ADMIN001', pwd: 'Admin@12345', label: '系统管理员' },
]

function fill(no: string, pwd: string) {
  officerNo.value = no
  password.value = pwd
}

/** 提交登录（前端基础校验 + 后端认证） */
async function submit() {
  if (!officerNo.value.trim()) return toast.error('请输入警号')
  if (password.value.length < 8) return toast.error('密码长度至少 8 位')
  loading.value = true
  try {
    await auth.login(officerNo.value.trim(), password.value)
    toast.success('登录成功')
    const redirect = route.query.redirect as string | undefined
    await router.push(redirect || '/')
  } catch {
    // 错误提示已由拦截器统一弹出
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-bg"></div>
    <div class="login-card">
      <div class="brand">
        <div class="brand-logo">
          <AppIcon name="shield" :size="26" />
        </div>
        <h1>智能问询笔录平台</h1>
        <p class="muted">面向公安执法与电信网络诈骗侦查场景的智能笔录制作系统</p>
      </div>

      <form class="login-form" @submit.prevent="submit">
        <label class="field-label">警号</label>
        <input v-model="officerNo" class="input" placeholder="请输入警号（登录账号）" autocomplete="username" />
        <label class="field-label">密码</label>
        <input
          v-model="password"
          class="input"
          type="password"
          placeholder="请输入密码（长度≥8）"
          autocomplete="current-password"
          @keyup.enter="submit"
        />
        <button class="btn btn-primary login-btn" type="submit" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>

      <div class="demo">
        <div class="muted demo-title">演示账号（点击填充）</div>
        <div class="row wrap">
          <button
            v-for="acc in DEMO_ACCOUNTS"
            :key="acc.no"
            type="button"
            class="tag demo-tag"
            @click="fill(acc.no, acc.pwd)"
          >
            <AppIcon name="user" :size="12" />
            {{ acc.label }} {{ acc.no }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--bg-0);
}

/* 多层次深色背景 + 蓝色光晕（原型深色主题） */
.login-bg {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(600px 320px at 20% 10%, rgba(59, 109, 255, 0.16), transparent 60%),
    radial-gradient(700px 380px at 85% 90%, rgba(56, 189, 248, 0.1), transparent 60%),
    linear-gradient(160deg, #05070c 0%, #0b0f17 55%, #101725 100%);
}

.login-card {
  position: relative;
  width: 420px;
  max-width: calc(100vw - 40px);
  background: rgba(20, 26, 38, 0.86);
  border: 1px solid var(--border-2);
  border-radius: 18px;
  padding: 40px 36px 30px;
  backdrop-filter: blur(10px);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
}

.brand {
  text-align: center;
  margin-bottom: 28px;
}

.brand-logo {
  width: 56px;
  height: 56px;
  margin: 0 auto 14px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, var(--primary), var(--accent));
  box-shadow: 0 8px 24px rgba(59, 109, 255, 0.35);
}

.brand h1 {
  margin: 0 0 8px;
  font-size: 24px;
  letter-spacing: 2px;
}

.brand p {
  margin: 0;
  font-size: 12px;
}

.login-form .field-label {
  margin: 14px 0 8px;
}

.login-btn {
  width: 100%;
  margin-top: 24px;
  padding: 12px;
  font-size: 15px;
  letter-spacing: 4px;
}

.demo {
  margin-top: 26px;
  padding-top: 18px;
  border-top: 1px dashed var(--border-2);
}

.demo-title {
  font-size: 12px;
  margin-bottom: 10px;
}

.demo-tag {
  cursor: pointer;
}

.demo-tag:hover {
  border-color: var(--primary);
  color: var(--text-1);
}
</style>
