/**
 * UI-1 工作台首页（仪表盘）
 *
 * 区域划分（原型 README UI-1）：
 * - 案件统计区：笔录总数与四阶段计数（GET /sessions/statistics）；
 * - 快速操作入口：新增笔录 / 导入历史笔录；
 * - 待办事项：问询进行中的会话（断点续问入口，4.5 restore 路由）；
 * - 通知中心：LLM 私有化接入状态（GET /ai/llm/status）；
 * - 最近笔录列表：台账前 8 条（GET /sessions）。
 */
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { getLLMStatus } from '@/api/ai'
import { getStatistics, listSessions, restoreSession } from '@/api/sessions'
import AppIcon from '@/components/AppIcon.vue'
import TopBar from '@/components/TopBar.vue'
import { useAuthStore } from '@/stores/auth'
import type { LLMStatusOut, SessionListItem } from '@/types'
import { fmtDateTime, restoreRoute, STAGE_META } from '@/utils/format'

const router = useRouter()
const auth = useAuthStore()

const stats = ref<Record<string, number>>({})
const recents = ref<SessionListItem[]>([])
const llm = ref<LLMStatusOut | null>(null)
const loading = ref(true)

/** 统计卡片定义（key 对应后端 statistics 字典键） */
const STAT_CARDS = [
  { key: 'total', label: '笔录总数', icon: 'file', tone: 'primary' },
  { key: 'intake', label: '接报录入', icon: 'edit', tone: 'warning' },
  { key: 'templates', label: '模板选择', icon: 'list', tone: 'warning' },
  { key: 'inquiry', label: '问询进行中', icon: 'chat', tone: 'primary' },
  { key: 'completed', label: '已完成', icon: 'check-circle', tone: 'success' },
]

onMounted(async () => {
  try {
    const [statRes, listRes] = await Promise.all([
      getStatistics(),
      listSessions({ page: 1, page_size: 8 }),
    ])
    stats.value = statRes
    recents.value = listRes.items
    // LLM 状态仅 best-effort 展示，失败不影响工作台
    getLLMStatus()
      .then((res) => (llm.value = res))
      .catch(() => undefined)
  } finally {
    loading.value = false
  }
})

/** 断点续问：按阶段恢复目标界面（4.5/BP-5） */
async function continueSession(item: SessionListItem) {
  try {
    const res = await restoreSession(item.id)
    await router.push(restoreRoute(res.target_view, item.id))
  } catch {
    // 拦截器已提示
  }
}

/** 待办：问询进行中的会话 */
function todoItems() {
  return recents.value.filter((s) => s.stage === 'inquiry' || s.stage === 'templates')
}

async function goImport() {
  await router.push('/history?import=1')
}
</script>

<template>
  <div class="page">
    <TopBar />
    <div class="page-body">
      <!-- 欢迎区 + 快速操作 -->
      <div class="row welcome">
        <div>
          <h2 class="hello">{{ auth.userName }}，欢迎回来</h2>
          <p class="muted hello-sub">今日问询任务与笔录动态一览，可快速发起新笔录或继续未完成问询</p>
        </div>
        <div class="spacer"></div>
        <button class="btn btn-ghost" @click="goImport">
          <AppIcon name="upload" :size="15" /> 导入历史笔录
        </button>
        <button class="btn btn-primary" @click="router.push('/intake')">
          <AppIcon name="plus" :size="15" /> 新增笔录
        </button>
      </div>

      <!-- 案件统计区 -->
      <div class="stat-grid">
        <div v-for="card in STAT_CARDS" :key="card.key" class="card stat-card">
          <div :class="['stat-icon', card.tone]"><AppIcon :name="card.icon" :size="18" /></div>
          <div>
            <div class="stat-num">{{ stats[card.key] ?? 0 }}</div>
            <div class="muted stat-label">{{ card.label }}</div>
          </div>
        </div>
      </div>

      <div class="dash-grid">
        <!-- 最近笔录 -->
        <div class="card">
          <h3 class="card-title bar">
            最近笔录
            <span class="spacer"></span>
            <RouterLink to="/history" class="muted link">查看全部</RouterLink>
          </h3>
          <div v-if="loading" class="loading-mask"><span class="spinner"></span>加载中...</div>
          <div v-else-if="recents.length === 0" class="empty">暂无笔录，点击右上角"新增笔录"开始</div>
          <div v-else class="recent-list">
            <div v-for="item in recents" :key="item.id" class="recent-item">
              <div class="row" style="gap: 10px">
                <span class="mono case-no">{{ item.case_no }}</span>
                <span class="tag">{{ item.case_category }}</span>
                <span :class="['tag', STAGE_META[item.stage].tone]">
                  <span class="dot" :style="{ background: 'currentColor' }"></span>
                  {{ STAGE_META[item.stage].label }}
                </span>
              </div>
              <div class="row" style="gap: 14px; margin-top: 6px">
                <span class="muted small"><AppIcon name="user" :size="12" /> {{ item.reporter_name || '-' }}</span>
                <span class="muted small"><AppIcon name="clock" :size="12" /> {{ fmtDateTime(item.updated_at) }}</span>
                <span class="spacer"></span>
                <span class="muted small">进度 {{ item.progress }}%</span>
                <div class="progress" style="width: 90px"><i :style="{ width: item.progress + '%' }"></i></div>
                <button class="btn btn-ghost btn-sm" @click="continueSession(item)">
                  <AppIcon name="chevron-right" :size="13" /> 继续
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="col" style="gap: 20px">
          <!-- 待办事项 -->
          <div class="card">
            <h3 class="card-title bar">待办事项</h3>
            <div v-if="todoItems().length === 0" class="empty">暂无待办问询</div>
            <div v-else class="col" style="gap: 10px">
              <div v-for="item in todoItems()" :key="item.id" class="todo-item" @click="continueSession(item)">
                <AppIcon name="warning" :size="15" class="todo-icon" />
                <div>
                  <div class="mono case-no">{{ item.case_no }}</div>
                  <div class="muted small">{{ STAGE_META[item.stage].label }} · 进度 {{ item.progress }}%，点击继续问询</div>
                </div>
              </div>
            </div>
          </div>

          <!-- 通知中心：LLM 私有化接入状态 -->
          <div class="card">
            <h3 class="card-title bar">通知中心</h3>
            <div v-if="llm" class="col" style="gap: 10px">
              <div class="row" style="gap: 8px">
                <span :class="['tag', llm.enabled && llm.reachable ? 'success' : 'warning']">
                  <span class="dot" style="background: currentColor"></span>
                  {{ llm.enabled ? (llm.reachable ? '大模型已接入' : '大模型不可达（规则降级）') : '大模型未启用（规则模式）' }}
                </span>
              </div>
              <div class="muted small">
                对话模型 {{ llm.chat_model }} · 向量模型 {{ llm.embedding_model }}
              </div>
              <div class="row wrap" style="gap: 6px">
                <span class="tag">语义匹配 {{ llm.capabilities.semantic_match ? '开' : '关' }}</span>
                <span class="tag">侦查研判 {{ llm.capabilities.analysis ? '开' : '关' }}</span>
                <span class="tag">要素抽取 {{ llm.capabilities.extraction ? '开' : '关' }}</span>
                <span class="tag">导入解析 {{ llm.capabilities.import_parse ? '开' : '关' }}</span>
              </div>
            </div>
            <div v-else class="empty">正在获取 AI 接入状态...</div>
            <div class="muted small notice">
              <AppIcon name="shield" :size="12" />
              案情数据仅发送至内网模型端点，全程不出公安内网。
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  margin-bottom: 24px;
}

.hello {
  margin: 0 0 6px;
  font-size: 24px;
}

.hello-sub {
  margin: 0;
  font-size: 13px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 18px;
  margin-bottom: 22px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon.primary {
  background: var(--primary-dim);
  color: var(--primary-hover);
}
.stat-icon.success {
  background: rgba(34, 197, 94, 0.14);
  color: var(--success);
}
.stat-icon.warning {
  background: rgba(245, 158, 11, 0.14);
  color: var(--warning);
}

.stat-num {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}

.stat-label {
  font-size: 12.5px;
}

.dash-grid {
  display: grid;
  grid-template-columns: 1.7fr 1fr;
  gap: 20px;
  align-items: start;
}

.recent-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.recent-item {
  background: var(--bg-3);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-m);
  padding: 14px 16px;
}

.case-no {
  font-weight: 700;
  font-size: 14px;
}

.small {
  font-size: 12.5px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.link {
  font-size: 12.5px;
  font-weight: 400;
}

.todo-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  background: var(--bg-3);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-m);
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.todo-item:hover {
  border-color: var(--primary);
}

.todo-icon {
  color: var(--warning);
  margin-top: 3px;
}

.notice {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--border-2);
  display: flex;
  gap: 6px;
  align-items: center;
}
</style>
