/**
 * 全局顶部导航栏（UI-1 工作台 / UI-6 历史笔录共用）
 *
 * 左侧品牌标识 + 主导航（工作台/历史笔录），右侧用户身份与登出。
 */
<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppIcon from '@/components/AppIcon.vue'
import { useAuthStore } from '@/stores/auth'
import { ROLE_LABEL } from '@/utils/format'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const NAVS = [
  { path: '/', label: '工作台', icon: 'grid' },
  { path: '/history', label: '历史笔录', icon: 'history' },
]

const activePath = computed(() => (route.path.startsWith('/history') ? '/history' : '/'))

async function onLogout() {
  await auth.logout()
  await router.push('/login')
}
</script>

<template>
  <header class="topbar no-print">
    <div class="topbar-title">
      <span class="logo"><AppIcon name="shield" :size="18" /></span>
      智能问询笔录平台
    </div>
    <div class="topbar-divider"></div>
    <nav class="nav">
      <RouterLink v-for="nav in NAVS" :key="nav.path" :to="nav.path" :class="['nav-item', { on: activePath === nav.path }]">
        <AppIcon :name="nav.icon" :size="15" />
        {{ nav.label }}
      </RouterLink>
    </nav>
    <div class="topbar-spacer"></div>
    <div class="row" style="gap: 8px">
      <span class="tag primary"><AppIcon name="user" :size="12" />{{ auth.userName }}</span>
      <span class="tag">{{ ROLE_LABEL[auth.user?.role ?? ''] ?? auth.user?.role }}</span>
      <span class="muted topbar-muted">{{ auth.user?.org_name }}</span>
      <button class="btn btn-ghost btn-icon" title="退出登录" @click="onLogout">
        <AppIcon name="logout" :size="15" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.logo {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: linear-gradient(135deg, var(--primary), var(--accent));
}

.nav {
  display: flex;
  gap: 6px;
}

.nav-item {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 16px;
  border-radius: 9px;
  color: var(--text-2);
  font-size: 13.5px;
  transition: all 0.15s;
}

.nav-item:hover {
  color: var(--text-1);
  background: var(--bg-3);
}

.nav-item.on {
  color: #fff;
  background: var(--primary-dim);
  border: 1px solid rgba(59, 109, 255, 0.4);
  padding: 6px 15px;
}
</style>
