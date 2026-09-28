/**
 * UI-6 历史笔录导入与回溯页（6.1 台账检索 + FR-3.5.3 历史笔录解析导入）
 *
 * 布局（原型 xT4cW / 需求 6.6）：
 * - 顶部：历史笔录管理 + 导入笔录入口；
 * - 左侧筛选面板：关键字搜索、案件类型、时间范围、笔录状态（单选组 + 重置）；
 * - 右侧笔录列表：卡片式展示（编号/类别/状态/报案人/日期/评分）+ 查看/下载/归档 + 分页；
 * - 导入抽屉：粘贴文本 / 上传 Word → 解析结果（问答对 + 五流分析报告 + 缺失流 +
 *   缺口追问草稿）→ 转存为新问询会话（支持针对缺口二次补充问询）。
 */
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { exportDocument } from '@/api/documents'
import { parseDocx, parseText, rebuildSession } from '@/api/imports'
import { archiveSession, listSessions, restoreSession } from '@/api/sessions'
import AppIcon from '@/components/AppIcon.vue'
import TopBar from '@/components/TopBar.vue'
import type { ParseResult, SessionListItem } from '@/types'
import { fmtDate, restoreRoute, STAGE_META } from '@/utils/format'
import { toast } from '@/utils/toast'

const router = useRouter()
const route = useRoute()

// ---------- 台账列表与筛选 ----------
const all = ref<SessionListItem[]>([])
const loading = ref(true)
const keyword = ref('')
const categoryFilter = ref('')
const timeFilter = ref('7')
const page = ref(1)
const PAGE_SIZE = 6

/** 状态筛选值：空=全部；draft=草稿（intake+templates）；其余为阶段 */
type StatusKey = '' | 'inquiry' | 'completed' | 'draft'
const statusFilter = ref<StatusKey>('')

onMounted(async () => {
  await reload()
  // 支持 /history?import=1 直接拉起导入抽屉
  if (route.query.import === '1') drawerOpen.value = true
})

async function reload() {
  loading.value = true
  try {
    // 后端台账仅支持关键字/阶段过滤，类型与时间范围在前端二次过滤（演示数据量可控）
    const res = await listSessions({ keyword: keyword.value || undefined, page: 1, page_size: 100 })
    all.value = res.items
  } finally {
    loading.value = false
  }
}

const categories = computed(() => [...new Set(all.value.map((s) => s.case_category))])

/** 筛选管道：类型 → 时间范围 → 状态 */
const filtered = computed(() => {
  const now = Date.now()
  const days = timeFilter.value === 'custom' ? Infinity : Number(timeFilter.value)
  return all.value.filter((s) => {
    if (categoryFilter.value && s.case_category !== categoryFilter.value) return false
    if (Number.isFinite(days) && now - new Date(s.updated_at).getTime() > days * 86400000) return false
    if (statusFilter.value === 'draft') return s.stage === 'intake' || s.stage === 'templates'
    if (statusFilter.value && s.stage !== statusFilter.value) return false
    return true
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

function resetFilters() {
  keyword.value = ''
  categoryFilter.value = ''
  timeFilter.value = '7'
  statusFilter.value = ''
  page.value = 1
}

/** 状态展示：草稿=intake/templates，其余按阶段映射（6.1 状态标识） */
function statusOf(item: SessionListItem): { label: string; tone: string } {
  if (item.stage === 'intake' || item.stage === 'templates') return { label: '草稿', tone: 'warning' }
  return STAGE_META[item.stage]
}

/** 查看：断点续问恢复目标界面 */
async function view(item: SessionListItem) {
  const res = await restoreSession(item.id)
  await router.push(restoreRoute(res.target_view, item.id))
}

/** 下载：DOCX 文书导出 */
async function download(item: SessionListItem) {
  await exportDocument(item.id)
  toast.success('文书已下载')
}

/** 归档（completed 会话） */
async function archive(item: SessionListItem) {
  if (!window.confirm(`确认归档笔录 ${item.case_no}？`)) return
  await archiveSession(item.id)
  toast.success('笔录已归档')
  await reload()
}

// ---------- 导入抽屉（FR-3.5.3） ----------
const drawerOpen = ref(false)
const importTab = ref<'text' | 'file'>('text')
const importText = ref('')
const parsing = ref(false)
const parseResult = ref<ParseResult | null>(null)

/** 转存新会话表单 */
const rebuildForm = ref({ case_no: '', case_category: '电信网络诈骗', brief: '', reporter_name: '' })
const rebuilding = ref(false)

async function doParse() {
  parsing.value = true
  parseResult.value = null
  try {
    parseResult.value = importTab.value === 'text' ? await parseText(importText.value) : parseResult.value
  } finally {
    parsing.value = false
  }
}

async function onParseFile(file: File) {
  parsing.value = true
  parseResult.value = null
  try {
    parseResult.value = await parseDocx(file)
    toast.success(`解析完成：${parseResult.value.qa_count} 组问答`)
  } finally {
    parsing.value = false
  }
}

/** 转存为新问询会话（历史笔录不覆盖现有会话） */
async function doRebuild() {
  const f = rebuildForm.value
  if (!f.case_no.trim() || !f.reporter_name.trim() || f.brief.trim().length < 10) {
    return toast.error('请完整填写新会话案件信息（案情≥10字）')
  }
  rebuilding.value = true
  try {
    const detail = await rebuildSession({
      case_no: f.case_no.trim(),
      case_category: f.case_category,
      brief: f.brief.trim(),
      reporter_name: f.reporter_name.trim(),
      parsed_qa: parseResult.value?.parsed_qa ?? [],
    })
    toast.success('历史笔录已导入并重建为新会话')
    drawerOpen.value = false
    await router.push(`/workbench/${detail.id}`)
  } finally {
    rebuilding.value = false
  }
}
</script>

<template>
  <div class="page">
    <TopBar />
    <div class="page-body hist-body">
      <!-- 左侧筛选面板 -->
      <aside class="card filter-card">
        <div class="row filter-head">
          <b>筛选与搜索</b>
          <span class="spacer"></span>
          <button class="link-btn" @click="resetFilters">重置</button>
        </div>
        <div class="f-search">
          <AppIcon name="search" :size="14" class="muted" />
          <input v-model="keyword" placeholder="搜索案件编号、当事人..." @keyup.enter="reload" />
        </div>

        <div class="f-group">案件类型</div>
        <label :class="['f-item', { on: categoryFilter === '' }]">
          <input type="radio" name="cat" :checked="categoryFilter === ''" @change="categoryFilter = ''" /> 全部类型
        </label>
        <label v-for="cat in categories" :key="cat" :class="['f-item', { on: categoryFilter === cat }]">
          <input type="radio" name="cat" :checked="categoryFilter === cat" @change="categoryFilter = cat" /> {{ cat }}
        </label>

        <div class="f-group">时间范围</div>
        <label v-for="opt in [{ v: '7', l: '最近7天' }, { v: '30', l: '最近30天' }, { v: '90', l: '最近3个月' }, { v: 'custom', l: '全部时间' }]"
          :key="opt.v" :class="['f-item', { on: timeFilter === opt.v }]">
          <input type="radio" name="time" :checked="timeFilter === opt.v" @change="timeFilter = opt.v" /> {{ opt.l }}
        </label>

        <div class="f-group">笔录状态</div>
        <label :class="['f-item', { on: statusFilter === '' }]">
          <input type="radio" name="status" :checked="statusFilter === ''" @change="statusFilter = ''" /> 全部状态
        </label>
        <label v-for="opt in [{ v: 'completed', l: '已完成' }, { v: 'inquiry', l: '问询中' }, { v: 'draft', l: '草稿' }]"
          :key="opt.v" :class="['f-item', { on: statusFilter === opt.v }]">
          <input
            type="radio"
            name="status"
            :checked="statusFilter === opt.v"
            @change="statusFilter = opt.v as StatusKey"
          />
          {{ opt.l }}
        </label>
      </aside>

      <!-- 右侧笔录列表 -->
      <section class="list-col">
        <div class="row list-head">
          <span class="muted">找到 {{ filtered.length }} 条笔录</span>
          <span class="spacer"></span>
          <button class="btn btn-primary" @click="drawerOpen = true">
            <AppIcon name="upload" :size="15" /> 导入笔录
          </button>
        </div>

        <div v-if="loading" class="loading-mask"><span class="spinner"></span>加载中...</div>
        <div v-else-if="paged.length === 0" class="empty">暂无符合条件的笔录</div>
        <div v-else class="col rec-list">
          <div v-for="item in paged" :key="item.id" class="card rec-card">
            <div class="row" style="align-items: flex-start">
              <div style="flex: 1; min-width: 0">
                <div class="row wrap" style="gap: 10px">
                  <span class="mono rec-no">{{ item.case_no }}</span>
                  <span class="tag">{{ item.case_category }}</span>
                  <span :class="['tag', statusOf(item).tone]">
                    <span class="dot" style="background: currentColor"></span> {{ statusOf(item).label }}
                  </span>
                </div>
                <div class="row rec-meta">
                  <span class="muted"><AppIcon name="user" :size="13" /> {{ item.reporter_name || '-' }}</span>
                  <span class="muted"><AppIcon name="calendar" :size="13" /> {{ fmtDate(item.updated_at) }}</span>
                  <span class="muted"><AppIcon name="star" :size="13" /> {{ item.progress }} 分</span>
                </div>
                <div class="muted rec-brief" :title="item.brief">{{ item.brief }}</div>
              </div>
              <div class="row" style="gap: 8px; flex: none">
                <button class="btn btn-ghost btn-sm" @click="view(item)">
                  <AppIcon name="eye" :size="13" /> 查看
                </button>
                <button class="btn btn-ghost btn-sm" @click="download(item)">
                  <AppIcon name="download" :size="13" /> 下载
                </button>
                <button
                  v-if="item.stage === 'completed'"
                  class="btn btn-ghost btn-icon btn-sm"
                  title="归档"
                  @click="archive(item)"
                >
                  <AppIcon name="archive" :size="13" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="row pager">
          <button class="page-btn" :disabled="page === 1" @click="page--">
            <AppIcon name="chevron-left" :size="14" />
          </button>
          <button
            v-for="p in totalPages"
            :key="p"
            :class="['page-btn', { on: p === page }]"
            @click="page = p"
          >
            {{ p }}
          </button>
          <button class="page-btn" :disabled="page === totalPages" @click="page++">
            <AppIcon name="chevron-right" :size="14" />
          </button>
        </div>
      </section>
    </div>

    <!-- 导入抽屉 -->
    <div v-if="drawerOpen" class="drawer-overlay" @click="drawerOpen = false"></div>
    <aside v-if="drawerOpen" class="drawer wide">
      <div class="drawer-head">
        <AppIcon name="upload" :size="16" /> 历史笔录导入
        <span class="spacer"></span>
        <button class="btn btn-ghost btn-icon" @click="drawerOpen = false"><AppIcon name="x" :size="14" /></button>
      </div>
      <div class="drawer-body">
        <!-- 上传区：粘贴文本 / 上传文件 -->
        <div class="row tabs">
          <button :class="['btn', 'btn-sm', { active: importTab === 'text' }]" @click="importTab = 'text'">粘贴文本</button>
          <button :class="['btn', 'btn-sm', { active: importTab === 'file' }]" @click="importTab = 'file'">上传 Word</button>
        </div>
        <textarea
          v-if="importTab === 'text'"
          v-model="importText"
          class="textarea"
          placeholder="粘贴历史笔录文本（支持 问：/答： 结构自动解析）"
          style="min-height: 140px"
        ></textarea>
        <label v-else class="file-pick">
          <AppIcon name="file" :size="18" class="muted" />
          选择 .docx 笔录文件
          <input type="file" accept=".docx,.doc" hidden @change="($event.target as HTMLInputElement).files?.[0] && onParseFile(($event.target as HTMLInputElement).files![0])" />
        </label>
        <button v-if="importTab === 'text'" class="btn btn-primary" style="width: 100%; margin-top: 12px" :disabled="parsing || !importText.trim()" @click="doParse">
          <span v-if="parsing" class="spinner"></span> 解析笔录
        </button>

        <!-- 解析结果区 -->
        <template v-if="parseResult">
          <div v-if="!parseResult.parse_success" class="parse-warn">
            <AppIcon name="warning" :size="14" /> {{ parseResult.parse_message || '解析失败，请手工校对' }}
          </div>
          <div class="dr-section">解析问答（{{ parseResult.qa_count }} 组）</div>
          <div class="parse-qa-list">
            <div v-for="(qa, i) in parseResult.parsed_qa.slice(0, 12)" :key="i" class="parse-qa">
              <div class="parse-q">问：{{ qa.question }}</div>
              <div v-if="qa.answer" class="parse-a">答：{{ qa.answer }}</div>
              <span v-if="qa.chapter" class="tag ch-tag">{{ qa.chapter }}</span>
            </div>
            <div v-if="parseResult.parsed_qa.length === 0" class="empty">未解析出问答对</div>
          </div>

          <!-- 五流证据分析报告 -->
          <div v-if="parseResult.five_flow_analysis" class="dr-section">五流证据分析报告</div>
          <div v-if="parseResult.five_flow_analysis" class="row wrap" style="gap: 8px">
            <span v-for="flow in parseResult.five_flow_analysis.flows" :key="flow.flow_type" class="tag">
              {{ flow.flow_label }} {{ Math.round(flow.coverage) }}%
            </span>
          </div>
          <div v-if="parseResult.missing_flows.length" class="row wrap" style="gap: 8px; margin-top: 8px">
            <span class="muted small">缺失流：</span>
            <span v-for="f in parseResult.missing_flows" :key="f" class="tag error">{{ f }}</span>
          </div>
          <div v-if="parseResult.followup_draft.length" class="dr-section">缺口追问草稿</div>
          <ul v-if="parseResult.followup_draft.length" class="draft-list">
            <li v-for="(q, i) in parseResult.followup_draft" :key="i">{{ q }}</li>
          </ul>

          <!-- 转存为新问询会话 -->
          <div class="dr-section">转存为新问询会话</div>
          <input v-model="rebuildForm.case_no" class="input" placeholder="新案件编号 *" style="margin-bottom: 8px" />
          <input v-model="rebuildForm.reporter_name" class="input" placeholder="报案人姓名 *" style="margin-bottom: 8px" />
          <textarea v-model="rebuildForm.brief" class="textarea" placeholder="简要案情 *（≥10 字）" style="min-height: 70px"></textarea>
          <button class="btn btn-primary" style="width: 100%; margin-top: 12px" :disabled="rebuilding" @click="doRebuild">
            <span v-if="rebuilding" class="spinner"></span> 转存为新会话并继续问询
          </button>
        </template>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.hist-body {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 22px;
  align-items: start;
  padding-top: 24px;
}

.filter-card {
  position: sticky;
  top: 80px;
  max-height: calc(100vh - 110px);
  overflow-y: auto;
  padding: 18px;
}

.filter-head {
  margin-bottom: 14px;
}

.link-btn {
  background: none;
  border: none;
  color: var(--primary-hover);
  font-size: 12.5px;
  cursor: pointer;
}

.f-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 6px;
}

.f-search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-1);
  font-size: 13px;
  width: 100%;
}

.f-group {
  font-size: 12px;
  color: var(--text-3);
  margin: 16px 0 8px;
}

.f-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-2);
  margin-bottom: 4px;
}

.f-item input {
  accent-color: var(--primary);
}

.f-item.on {
  background: var(--primary);
  color: #fff;
}

.list-head {
  margin-bottom: 14px;
}

.rec-list {
  gap: 14px;
}

.rec-card {
  padding: 18px 20px;
  margin: 0;
}

.rec-no {
  font-size: 16px;
  font-weight: 700;
}

.rec-meta {
  gap: 16px;
  margin-top: 8px;
  font-size: 12.5px;
}

.rec-brief {
  margin-top: 6px;
  font-size: 12.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 640px;
}

.pager {
  justify-content: center;
  gap: 8px;
  margin-top: 22px;
}

.page-btn {
  min-width: 34px;
  height: 34px;
  border-radius: 8px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  color: var(--text-2);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}

.page-btn.on {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ---------- 导入抽屉 ---------- */
.drawer.wide {
  width: 560px;
}

.tabs {
  gap: 8px;
  margin-bottom: 12px;
}

.tabs .btn.active {
  background: var(--primary);
}

.file-pick {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  border: 1.5px dashed var(--border-3);
  border-radius: var(--radius-m);
  padding: 30px;
  cursor: pointer;
  color: var(--text-2);
  font-size: 13px;
}

.dr-section {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-2);
  margin: 18px 0 10px;
}

.parse-warn {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: var(--warning);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 14px;
  font-size: 12.5px;
}

.parse-qa-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 260px;
  overflow-y: auto;
}

.parse-qa {
  position: relative;
  background: var(--bg-3);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 12.5px;
  line-height: 1.7;
}

.parse-q {
  font-weight: 600;
}

.parse-a {
  color: var(--text-2);
}

.ch-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 10.5px;
  padding: 1px 8px;
}

.draft-list {
  margin: 0;
  padding-left: 18px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.9;
}

.small {
  font-size: 12px;
}
</style>
