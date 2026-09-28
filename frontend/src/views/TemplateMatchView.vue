/**
 * UI-3 问询模板智能匹配页（FR-3.3.2 / FR-3.3.3）
 *
 * 布局（原型 gE9Ah）：
 * - 左侧：原案基础信息摘要卡片；
 * - 右上：AI 智能推荐模板卡片（匹配度评分、命中信号词、推荐理由、预览/使用）；
 * - 右下：全量模板库检索与多选（类别筛选 + 匹配度排序，选中状态与推荐区联动）；
 * - 底部：确认模板并开始问询（未选时禁用），确认后装配大纲进入三栏工作台。
 */
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { recommendTemplates } from '@/api/ai'
import { selectTemplates, getSession } from '@/api/sessions'
import { getTemplate, listTemplates } from '@/api/templates'
import AppIcon from '@/components/AppIcon.vue'
import type { SessionDetail, TemplateDetail, TemplateOut, TemplateRecommendItem, Chapter } from '@/types'
import { CHAPTER_LABEL, CHAPTER_ORDER } from '@/utils/format'
import { toast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId as string

const session = ref<SessionDetail | null>(null)
const recommendations = ref<TemplateRecommendItem[]>([])
const degraded = ref(false)
const templates = ref<TemplateOut[]>([])
/** 模板问题数缓存（模板详情懒加载） */
const questionCount = ref<Record<string, number>>({})
/** 已选模板ID集合（推荐区与全量库联动高亮） */
const selected = ref<Set<string>>(new Set())
const loading = ref(true)
const confirming = ref(false)

// 全量库筛选与排序
const keyword = ref('')
const categoryFilter = ref('')
const sortBy = ref<'score' | 'name'>('score')

// 预览弹窗
const preview = ref<TemplateDetail | null>(null)

/** 匹配度映射（全量库行展示匹配度百分比） */
const scoreMap = computed(() => {
  const map: Record<string, number> = {}
  recommendations.value.forEach((r) => (map[r.template.id] = r.match_percent))
  return map
})

const categories = computed(() => [...new Set(templates.value.map((t) => t.category))])

/** 全量库列表：关键字 + 类别过滤，匹配度/名称排序 */
const filteredTemplates = computed(() => {
  let list = templates.value.filter(
    (t) =>
      (!categoryFilter.value || t.category === categoryFilter.value) &&
      (!keyword.value || t.name.includes(keyword.value) || t.category.includes(keyword.value)),
  )
  if (sortBy.value === 'score') {
    list = [...list].sort((a, b) => (scoreMap.value[b.id] ?? -1) - (scoreMap.value[a.id] ?? -1))
  } else {
    list = [...list].sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  }
  return list
})

onMounted(async () => {
  try {
    const [detail, tplList] = await Promise.all([getSession(sessionId), listTemplates({ only_enabled: true })])
    session.value = detail
    templates.value = tplList
    selected.value = new Set(detail.selected_template_ids)
    // AI 智能推荐（降级时展示全量库兜底）
    const rec = await recommendTemplates(detail.case_info?.brief ?? '', detail.case_info?.case_category, 3)
    recommendations.value = rec.recommendations
    degraded.value = rec.is_degraded
    // 推荐模板问题数（卡片展示问题数/预计时长）
    await Promise.all(rec.recommendations.map((r) => loadQuestionCount(r.template.id)))
  } finally {
    loading.value = false
  }
})

/** 懒加载模板问题数（详情接口含标准问题集） */
async function loadQuestionCount(templateId: string) {
  if (questionCount.value[templateId] !== undefined) return
  const detail = await getTemplate(templateId)
  questionCount.value[templateId] = detail.questions.length
}

/** 预计时长估算（问题数 × 1.5~2 分钟，取 5 分钟整） */
function durationRange(count: number): string {
  const low = Math.max(10, Math.round((count * 1.5) / 5) * 5)
  const high = Math.max(15, Math.round((count * 2) / 5) * 5)
  return `${low}-${high}分钟`
}

/** 切换模板选中状态（多选，FR-3.3.3 组合选定） */
function toggleSelect(templateId: string) {
  const next = new Set(selected.value)
  if (next.has(templateId)) next.delete(templateId)
  else next.add(templateId)
  selected.value = next
}

/** 预览模板：弹窗展示按章节归类的标准问题集 */
async function openPreview(templateId: string) {
  preview.value = await getTemplate(templateId)
}

/** 预览弹窗内按章节分组 */
const previewGroups = computed(() => {
  if (!preview.value) return []
  return CHAPTER_ORDER.map((ch) => ({
    chapter: ch,
    items: preview.value!.questions.filter((q) => q.chapter === ch),
  })).filter((g) => g.items.length > 0)
})

/** 确认模板并开始问询：装配大纲 + 流转 templates → inquiry */
async function confirmAndStart() {
  if (selected.value.size === 0) return
  confirming.value = true
  try {
    await selectTemplates(sessionId, [...selected.value])
    toast.success('模板已选定，大纲装配完成')
    await router.push(`/workbench/${sessionId}`)
  } catch {
    // 拦截器已提示
  } finally {
    confirming.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="page-body">
      <div class="page-head row">
        <div>
          <h1 class="page-title">问询模板智能匹配</h1>
          <p class="page-sub">基于案件信息，AI 为您推荐最适合的问询模板</p>
        </div>
        <span class="spacer"></span>
        <button class="btn btn-ghost btn-sm" @click="router.push('/')">
          <AppIcon name="arrow-left" :size="14" /> 返回工作台
        </button>
      </div>

      <div v-if="loading" class="loading-mask"><span class="spinner"></span>正在加载案件与推荐结果...</div>

      <div v-else class="match-grid">
        <!-- 左侧：原案基础信息摘要 -->
        <aside class="card summary">
          <h3 class="card-title"><AppIcon name="file" :size="16" class="sum-icon" /> 原案基础信息</h3>
          <div class="sum-block">
            <div class="muted sum-label">案件编号</div>
            <div class="mono sum-value">{{ session?.case_info?.case_no }}</div>
          </div>
          <div class="sum-block">
            <div class="muted sum-label">案件类别</div>
            <div class="sum-value">{{ session?.case_info?.case_category }}</div>
          </div>
          <div class="sum-block">
            <div class="muted sum-label">报案人</div>
            <div class="sum-value">{{ session?.case_info?.reporter?.name || '-' }}</div>
          </div>
          <div class="sum-block">
            <div class="muted sum-label">简要案情</div>
            <div class="sum-value brief">{{ session?.case_info?.brief }}</div>
          </div>
        </aside>

        <!-- 右侧：推荐区 + 全量库 -->
        <div class="col">
          <div class="row rec-head">
            <AppIcon name="star" :size="18" class="rec-star" />
            <h2 class="rec-title">AI 智能推荐</h2>
            <span class="spacer"></span>
            <span v-if="degraded" class="tag warning">推荐降级：展示全量库兜底</span>
            <span class="badge-count">{{ recommendations.length }} 项匹配</span>
          </div>

          <div class="rec-grid">
            <div
              v-for="rec in recommendations"
              :key="rec.template.id"
              :class="['card rec-card', { picked: selected.has(rec.template.id) }]"
            >
              <div class="row" style="align-items: flex-start">
                <div style="flex: 1">
                  <div class="rec-name">{{ rec.template.name }}</div>
                  <div class="row wrap" style="gap: 6px; margin-top: 8px">
                    <span class="tag">{{ rec.template.category }}</span>
                    <span v-if="rec.is_high_confidence" class="tag primary">高置信</span>
                  </div>
                </div>
                <div class="score-box">
                  <div class="score-num">{{ rec.match_percent }}%</div>
                  <div class="score-label">匹配度</div>
                </div>
              </div>
              <div class="row rec-meta">
                <span class="muted"><AppIcon name="list" :size="14" /> 问题数 {{ questionCount[rec.template.id] ?? '-' }} 题</span>
                <span class="muted"><AppIcon name="clock" :size="14" /> {{ durationRange(questionCount[rec.template.id] ?? 0) }}</span>
              </div>
              <!-- 推荐理由与命中信号词（展开查看） -->
              <details class="rec-reason">
                <summary>推荐理由与命中信号词</summary>
                <p class="muted reason-text">{{ rec.reason }}</p>
                <div class="row wrap" style="gap: 6px">
                  <span v-for="w in rec.hit_signal_words" :key="w" class="tag primary">{{ w }}</span>
                  <span v-if="rec.hit_signal_words.length === 0" class="muted small">无命中信号词（语义/类别因子匹配）</span>
                </div>
              </details>
              <div class="row" style="gap: 10px; margin-top: 14px">
                <button class="btn btn-ghost" style="flex: 1" @click="openPreview(rec.template.id)">预览模板</button>
                <button
                  :class="['btn', selected.has(rec.template.id) ? 'btn-ghost' : 'btn-primary']"
                  style="flex: 1"
                  @click="toggleSelect(rec.template.id)"
                >
                  {{ selected.has(rec.template.id) ? '取消使用' : '使用此模板' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 全量模板库 -->
          <div class="row lib-head">
            <h2 class="rec-title">全量模板库</h2>
            <span class="spacer"></span>
            <div class="lib-search">
              <AppIcon name="search" :size="14" class="muted" />
              <input v-model="keyword" placeholder="搜索模板名称/案由" />
            </div>
            <select v-model="categoryFilter" class="select lib-select">
              <option value="">全部类型</option>
              <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
            </select>
            <select v-model="sortBy" class="select lib-select">
              <option value="score">按匹配度</option>
              <option value="name">按名称</option>
            </select>
          </div>

          <div class="col lib-list">
            <div v-for="tpl in filteredTemplates" :key="tpl.id" :class="['lib-row', { picked: selected.has(tpl.id) }]">
              <label class="row chk" @click.prevent="toggleSelect(tpl.id)">
                <input type="checkbox" :checked="selected.has(tpl.id)" />
                <div>
                  <div class="lib-name">{{ tpl.name }}</div>
                  <div class="row" style="gap: 10px; margin-top: 4px">
                    <span class="tag">{{ tpl.category }}</span>
                    <span class="muted small">{{ questionCount[tpl.id] ?? '-' }} 题</span>
                    <span v-if="scoreMap[tpl.id] !== undefined" class="muted small">匹配度 {{ scoreMap[tpl.id] }}%</span>
                  </div>
                </div>
              </label>
              <div class="row" style="gap: 8px">
                <button class="btn btn-ghost btn-sm" @click="openPreview(tpl.id)">查看</button>
                <button
                  :class="['btn', 'btn-sm', selected.has(tpl.id) ? 'btn-ghost' : 'btn-primary']"
                  @click="toggleSelect(tpl.id)"
                >
                  {{ selected.has(tpl.id) ? '已选' : '使用' }}
                </button>
              </div>
            </div>
            <div v-if="filteredTemplates.length === 0" class="empty">无匹配模板</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部操作区 -->
    <div class="footer-bar">
      <span class="muted footer-tip">已选 {{ selected.size }} 个模板（可组合装配大纲）</span>
      <button class="btn btn-primary" :disabled="selected.size === 0 || confirming" @click="confirmAndStart">
        <span v-if="confirming" class="spinner"></span>
        确认模板并开始问询
      </button>
    </div>

    <!-- 模板预览弹窗 -->
    <div v-if="preview" class="modal-overlay" @click.self="preview = null">
      <div class="modal">
        <h3 class="modal-title">{{ preview.name }} · 标准问题集</h3>
        <div class="row wrap" style="gap: 6px; margin-bottom: 14px">
          <span class="tag">{{ preview.category }}</span>
          <span class="tag">{{ preview.questions.length }} 题</span>
          <span v-for="w in preview.signal_words.slice(0, 6)" :key="w.id" class="tag primary">{{ w.word }}</span>
        </div>
        <div v-for="group in previewGroups" :key="group.chapter" class="preview-group">
          <div class="preview-chapter">{{ CHAPTER_LABEL[group.chapter as Chapter] }}</div>
          <ol class="preview-qs">
            <li v-for="q in group.items" :key="q.id">{{ q.question }}</li>
          </ol>
        </div>
        <div class="row" style="justify-content: flex-end; margin-top: 18px">
          <button class="btn btn-ghost" @click="preview = null">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.match-grid {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 24px;
  align-items: start;
}

.summary {
  position: sticky;
  top: 24px;
}

.sum-icon {
  color: var(--primary-hover);
}

.sum-block {
  background: var(--bg-3);
  border-radius: var(--radius-m);
  padding: 12px 14px;
  margin-bottom: 12px;
}

.sum-label {
  font-size: 12px;
  margin-bottom: 4px;
}

.sum-value {
  font-size: 14px;
  font-weight: 600;
}

.sum-value.brief {
  font-weight: 400;
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.7;
}

.rec-head {
  margin-bottom: 16px;
}

.rec-star {
  color: var(--warning);
}

.rec-title {
  margin: 0;
  font-size: 18px;
}

.rec-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 30px;
}

.rec-card {
  border-color: rgba(59, 109, 255, 0.55);
  padding: 18px;
  margin: 0;
}

.rec-card.picked {
  box-shadow: 0 0 0 2px var(--primary-dim);
}

.rec-name {
  font-size: 15px;
  font-weight: 700;
  line-height: 1.4;
}

.score-box {
  background: var(--primary-dim);
  border-radius: var(--radius-m);
  padding: 8px 12px;
  text-align: center;
  flex-shrink: 0;
}

.score-num {
  color: var(--primary-hover);
  font-size: 18px;
  font-weight: 700;
}

.score-label {
  color: var(--text-3);
  font-size: 11px;
}

.rec-meta {
  gap: 16px;
  margin-top: 14px;
  font-size: 12.5px;
}

.rec-reason {
  margin-top: 10px;
  font-size: 12.5px;
}

.rec-reason summary {
  color: var(--text-3);
  cursor: pointer;
}

.reason-text {
  margin: 8px 0;
  font-size: 12.5px;
  line-height: 1.7;
}

.lib-head {
  margin-bottom: 14px;
  gap: 10px;
}

.lib-search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: var(--radius-m);
  padding: 7px 12px;
  width: 220px;
}

.lib-search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-1);
  font-size: 13px;
  width: 100%;
}

.lib-select {
  width: 120px;
  flex: none;
  padding: 8px 12px;
}

.lib-list {
  gap: 12px;
}

.lib-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: var(--bg-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-l);
  padding: 16px 20px;
  transition: border-color 0.15s;
}

.lib-row.picked {
  border-color: var(--primary);
  background: linear-gradient(90deg, var(--primary-dim), var(--bg-2) 40%);
}

.chk {
  cursor: pointer;
  align-items: flex-start;
}

.chk input {
  margin-top: 4px;
  accent-color: var(--primary);
  width: 15px;
  height: 15px;
}

.lib-name {
  font-size: 15px;
  font-weight: 600;
}

.small {
  font-size: 12px;
}

.footer-tip {
  margin-right: auto;
  font-size: 13px;
}

.preview-group {
  margin-bottom: 14px;
}

.preview-chapter {
  font-weight: 700;
  font-size: 13px;
  color: var(--primary-hover);
  margin-bottom: 6px;
}

.preview-qs {
  margin: 0;
  padding-left: 20px;
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.9;
}
</style>
