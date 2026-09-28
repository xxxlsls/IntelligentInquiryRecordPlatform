/**
 * UI-4 三栏沉浸式问询工作台（核心页面，FR-3.4.1~3.4.4）
 *
 * 布局（原型 GmdZP / 需求 6.4）：
 * - 顶部状态栏：案件编号、阶段徽章、计时统计、暂时保存/导出笔录/完成问询；
 * - 左栏 正式问答区：按大纲章节组织卡片流，问题行内编辑、答案录入实时保存、
 *   语音输入（Web Speech）、新增/删除问答、来源标记；
 * - 中栏 AI 侦查研判区：涉诈类型判定、判定依据、侦查指引、推荐补充问题（加入问询）；
 * - 右栏 五流证据区：五流覆盖进度、状态标签、证据摘要、重点缺口高亮 + 材料抽屉。
 *
 * 数据联动：问答录入实时保存 → 异步触发五流抽取与 AI 研判刷新（防抖）。
 */
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { adoptSuggestion, analyzeSession } from '@/api/ai'
import { getCoverage, extractElements } from '@/api/fiveflow'
import { listMaterials, uploadMaterial } from '@/api/materials'
import {
  createQA,
  deleteQA,
  getQAByChapter,
  getSession,
  saveSnapshot,
  transitStage,
  updateQA,
} from '@/api/sessions'
import AppIcon from '@/components/AppIcon.vue'
import type {
  AnalysisResult,
  Chapter,
  FiveFlowAnalysisResult,
  FlowCoverage,
  MaterialOut,
  MaterialType,
  QAChapterGroup,
  QAOut,
  SessionDetail,
} from '@/types'
import { FLOW_META, fmtDuration, fmtSize, SOURCE_LABEL, STATUS_META } from '@/utils/format'
import { toast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId as string

const session = ref<SessionDetail | null>(null)
const chapters = ref<QAChapterGroup[]>([])
const analysis = ref<AnalysisResult | null>(null)
const coverage = ref<FiveFlowAnalysisResult | null>(null)
const loading = ref(true)
const analyzing = ref(false)

// 顶部计时（断点快照恢复累计秒数）
const elapsed = ref(0)
let timerHandle: number | undefined

// 左栏检索关键字
const searchKey = ref('')
// 行内编辑状态：qaId → 编辑中问题文本
const editingQuestion = ref<Record<string, string>>({})
// 每章节新增问答输入框
const addingChapter = ref<Chapter | null>(null)
const addingText = ref('')

// 材料抽屉
const drawerOpen = ref(false)
const materials = ref<MaterialOut[]>([])
const uploadType = ref<MaterialType>('chat_screenshot')
const uploading = ref(false)

/** 材料类型候选（FR-3.4.4 白名单） */
const MATERIAL_TYPES: { value: MaterialType; label: string }[] = [
  { value: 'call_record', label: '通话记录' },
  { value: 'transfer_flow', label: '转账流水' },
  { value: 'chat_screenshot', label: '聊天截图' },
  { value: 'image', label: '图片' },
  { value: 'pdf', label: 'PDF 文档' },
  { value: 'document', label: '其他文档' },
]

onMounted(async () => {
  await reloadBase()
  // 计时器：每秒累计（暂存时写入快照）
  timerHandle = window.setInterval(() => (elapsed.value += 1), 1000)
  // 五流覆盖度为纯内存计算（毫秒级），随主体一并等待后立即解除遮罩，
  // 使左栏问答与右栏五流秒级呈现，不被耗时的 AI 研判拖慢
  await refreshCoverage()
  loading.value = false
  // AI 研判需调用本地大模型推理（单次约 20 秒），改为后台异步刷新，不阻塞工作台展示；
  // 期间中栏显示“研判中”占位，完成后自动填充（失败则保留上次结果）
  void refreshAnalysis()
})

onBeforeUnmount(() => {
  if (timerHandle) window.clearInterval(timerHandle)
  Object.values(saveTimers).forEach((t) => window.clearTimeout(t))
})

/** 加载会话详情与按章节问答（左栏卡片流） */
async function reloadBase() {
  const [detail, qa] = await Promise.all([getSession(sessionId), getQAByChapter(sessionId)])
  session.value = detail
  chapters.value = qa
  // 恢复断点计时（6.4 暂存快照）
  const snap = detail.stage_snapshot as { elapsed_seconds?: number } | null
  if (snap?.elapsed_seconds) elapsed.value = snap.elapsed_seconds
}

/** 左栏展示：按关键字过滤后的章节分组 */
const visibleChapters = computed(() => {
  if (!searchKey.value.trim()) return chapters.value
  const key = searchKey.value.trim()
  return chapters.value
    .map((g) => ({ ...g, items: g.items.filter((q) => q.question.includes(key) || (q.answer ?? '').includes(key)) }))
    .filter((g) => g.items.length > 0)
})

/** 中栏推荐补充问题（重点缺口追问置顶，GR-2） */
const suggestions = computed(() => analysis.value?.suggestions ?? [])

// ============================================================
// 问答实时保存（FR-3.4.1 双向绑定）+ 异步联动刷新
// ============================================================
const saveTimers: Record<string, number> = {}
let refreshTimer: number | undefined

/** 答案录入防抖保存 → 触发五流抽取与 AI 研判刷新 */
function onAnswerInput(qa: QAOut) {
  if (saveTimers[qa.id]) window.clearTimeout(saveTimers[qa.id])
  saveTimers[qa.id] = window.setTimeout(async () => {
    try {
      await updateQA(sessionId, qa.id, { answer: qa.answer ?? '' })
      scheduleLinkedRefresh(qa.id)
    } catch {
      // 拦截器已提示
    }
  }, 900)
}

/** 问题行内编辑提交 */
async function commitQuestion(qa: QAOut) {
  const text = (editingQuestion.value[qa.id] ?? '').trim()
  delete editingQuestion.value[qa.id]
  if (!text || text === qa.question) return
  await updateQA(sessionId, qa.id, { question: text })
  qa.question = text
  scheduleLinkedRefresh(qa.id)
  toast.success('问题已更新')
}

/** 联动刷新防抖：五流抽取 + 覆盖度 + AI 研判 + 进度 */
function scheduleLinkedRefresh(qaId?: string) {
  if (refreshTimer) window.clearTimeout(refreshTimer)
  refreshTimer = window.setTimeout(async () => {
    try {
      await extractElements(sessionId, qaId)
    } catch {
      // 抽取失败不阻断录入
    }
    await Promise.all([refreshCoverage(), refreshAnalysis(), refreshProgress()])
  }, 1600)
}

async function refreshCoverage() {
  try {
    coverage.value = await getCoverage(sessionId)
  } catch {
    // 忽略
  }
}

async function refreshAnalysis() {
  analyzing.value = true
  try {
    analysis.value = await analyzeSession(sessionId)
  } catch {
    // 忽略（中栏保留上次结果）
  } finally {
    analyzing.value = false
  }
}

async function refreshProgress() {
  const detail = await getSession(sessionId)
  if (session.value) session.value.progress = detail.progress
}

/** 新增问答（手动来源，插入章节末尾） */
async function addQA(chapter: Chapter) {
  const text = addingText.value.trim()
  if (!text) return toast.error('请输入问题内容')
  await createQA(sessionId, { chapter, question: text, source: 'manual' })
  addingChapter.value = null
  addingText.value = ''
  const qa = await getQAByChapter(sessionId)
  chapters.value = qa
  toast.success('问答已新增')
}

/** 删除问答（二次确认，FR-3.4.1） */
async function removeQA(qa: QAOut) {
  if (!window.confirm(`确认删除问答「${qa.question}」？删除后不可恢复。`)) return
  await deleteQA(sessionId, qa.id)
  chapters.value = await getQAByChapter(sessionId)
  scheduleLinkedRefresh()
  toast.success('问答已删除')
}

/** 采纳 AI 推荐问题 → 转左栏正式问答（GR-4） */
async function adopt(suggestionId: string) {
  const res = await adoptSuggestion(sessionId, suggestionId)
  if (res.is_duplicate) toast.info('该问题已存在，未重复新增')
  else toast.success('已加入问询大纲')
  chapters.value = await getQAByChapter(sessionId)
  await refreshAnalysis()
}

// ============================================================
// 语音输入（Web Speech API，浏览器不支持时提示降级手动录入）
// ============================================================
const recognizingId = ref('')
function dictate(qa: QAOut) {
  const SR = (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown })
    .SpeechRecognition || (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition
  if (!SR) return toast.error('当前浏览器不支持语音识别，请手动录入')
  const rec = new (SR as new () => {
    lang: string
    interimResults: boolean
    onresult: (e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void
    onend: () => void
    start: () => void
  })()
  rec.lang = 'zh-CN'
  rec.interimResults = true
  recognizingId.value = qa.id
  const base = qa.answer ?? ''
  rec.onresult = (e) => {
    const text = Array.from({ length: e.results.length }, (_, i) => e.results[i][0].transcript).join('')
    qa.answer = base + text
  }
  rec.onend = () => {
    recognizingId.value = ''
    onAnswerInput(qa)
  }
  rec.start()
}

// ============================================================
// 顶部操作：暂时保存 / 完成问询 / 导出笔录
// ============================================================
async function saveNow() {
  await saveSnapshot(sessionId, { elapsed_seconds: elapsed.value, saved_at: new Date().toISOString() })
  toast.success('现场已暂存，可稍后断点续问')
}

async function completeInquiry() {
  if (!window.confirm('确认完成问询？笔录将封存并进入预览导出阶段。')) return
  await transitStage(sessionId, 'completed')
  toast.success('问询已完成')
  await router.push(`/document/${sessionId}`)
}

// ============================================================
// 材料抽屉（FR-3.4.4 拖拽上传，物理隔离于问答正文）
// ============================================================
async function openDrawer() {
  drawerOpen.value = true
  await reloadMaterials()
}

async function reloadMaterials() {
  const res = await listMaterials(sessionId)
  materials.value = res.items
}

async function onUpload(file: File) {
  uploading.value = true
  try {
    await uploadMaterial(sessionId, file, uploadType.value)
    toast.success('材料上传成功')
    await reloadMaterials()
  } finally {
    uploading.value = false
  }
}

function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (file) void onUpload(file)
}

/** 右栏流卡片状态色调 */
function flowTone(flow: FlowCoverage) {
  return STATUS_META[flow.status].tone
}
</script>

<template>
  <div class="wb">
    <!-- 顶部状态栏 -->
    <header class="wb-top no-print">
      <button class="btn btn-ghost btn-icon" title="返回工作台" @click="router.push('/')">
        <AppIcon name="arrow-left" :size="15" />
      </button>
      <div class="topbar-title">案件编号：{{ session?.case_info?.case_no }}</div>
      <span class="tag">{{ session?.case_info?.case_category }}</span>
      <span class="tag primary stage-badge"><span class="dot" style="background: var(--success)"></span> 进行中</span>
      <span class="row timer"><AppIcon name="clock" :size="15" /> {{ fmtDuration(elapsed) }}</span>
      <span class="row muted progress-wrap">
        进度 {{ session?.progress ?? 0 }}%
        <span class="progress" style="width: 110px"><i :style="{ width: (session?.progress ?? 0) + '%' }"></i></span>
      </span>
      <span class="spacer"></span>
      <button class="btn btn-ghost" @click="saveNow"><AppIcon name="save" :size="14" /> 暂时保存</button>
      <button class="btn btn-ghost" @click="router.push(`/document/${sessionId}`)">
        <AppIcon name="download" :size="14" /> 导出笔录
      </button>
      <button class="btn btn-danger" @click="completeInquiry">完成问询</button>
    </header>

    <div v-if="loading" class="loading-mask"><span class="spinner"></span>正在恢复问询现场...</div>

    <div v-else class="wb-cols">
      <!-- 左栏：正式问答区 -->
      <section class="wb-col col-qa">
        <div class="col-head">
          <AppIcon name="list" :size="16" class="head-icon" />
          问题引导
          <span class="spacer"></span>
          <div class="qa-search">
            <AppIcon name="search" :size="13" class="muted" />
            <input v-model="searchKey" placeholder="搜索问题" />
          </div>
        </div>
        <div class="col-body">
          <div v-for="group in visibleChapters" :key="group.chapter" class="chapter">
            <div class="chapter-head">
              {{ group.chapter_label }}
              <span class="muted chapter-count">{{ group.items.filter((q) => q.is_answered).length }}/{{ group.items.length }}</span>
              <span class="spacer"></span>
              <button class="btn btn-ghost btn-sm" @click="addingChapter = group.chapter; addingText = ''">
                <AppIcon name="plus" :size="12" /> 新增问答
              </button>
            </div>
            <!-- 新增问答输入行 -->
            <div v-if="addingChapter === group.chapter" class="qa-add row">
              <input v-model="addingText" class="input" placeholder="输入新问题，回车确认" @keyup.enter="addQA(group.chapter)" />
              <button class="btn btn-primary btn-sm" @click="addQA(group.chapter)">确认</button>
              <button class="btn btn-ghost btn-sm" @click="addingChapter = null">取消</button>
            </div>
            <div v-for="qa in group.items" :key="qa.id" :class="['qa-card', { answered: qa.is_answered }]">
              <div class="qa-q row">
                <AppIcon :name="qa.is_answered ? 'check-circle' : 'circle'" :size="15" :class="qa.is_answered ? 'ok' : 'muted'" />
                <input
                  v-if="editingQuestion[qa.id] !== undefined"
                  v-model="editingQuestion[qa.id]"
                  class="qa-q-edit"
                  autofocus
                  @blur="commitQuestion(qa)"
                  @keyup.enter="($event.target as HTMLInputElement).blur()"
                />
                <span v-else class="qa-q-text" title="点击编辑问题" @click="editingQuestion[qa.id] = qa.question">
                  {{ qa.question }}
                </span>
                <span class="spacer"></span>
                <span class="tag src-tag">{{ SOURCE_LABEL[qa.source] }}</span>
                <button class="icon-mini" title="删除问答" @click="removeQA(qa)">
                  <AppIcon name="trash" :size="13" />
                </button>
              </div>
              <div class="qa-a">
                <textarea
                  v-model="qa.answer"
                  :class="['qa-a-input', { recording: recognizingId === qa.id }]"
                  :placeholder="recognizingId === qa.id ? '正在语音识别...' : '录入回答内容（失焦自动保存）'"
                  rows="2"
                  @input="onAnswerInput(qa)"
                ></textarea>
                <button
                  :class="['icon-mini mic', { on: recognizingId === qa.id }]"
                  title="语音输入"
                  @click="dictate(qa)"
                >
                  <AppIcon name="mic" :size="13" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 中栏：AI 侦查研判区 -->
      <section class="wb-col col-ai">
        <div class="col-head">
          <AppIcon name="zap" :size="16" class="head-icon ai" />
          AI 侦查研判
          <span class="spacer"></span>
          <span v-if="analyzing" class="muted small"><span class="spinner"></span> 研判中</span>
          <span v-if="analysis?.is_timeout" class="tag warning">模型超时·展示上次结果</span>
        </div>
        <div class="col-body">
          <!-- AI 研判后台加载占位（大模型推理约 20 秒，不阻塞左/右两栏） -->
          <div v-if="analyzing && !analysis" class="gap-banner info">
            <span class="spinner"></span> AI 正在研判案情，生成涉诈类型判定与追问建议…（约 20 秒，可先继续录入）
          </div>
          <div v-if="analysis?.is_insufficient_context" class="gap-banner info">
            <AppIcon name="chat" :size="14" /> 问答上下文不足，继续录入后自动刷新研判结论
          </div>
          <!-- 涉诈类型判定 -->
          <div v-if="analysis?.case_type_judgement" class="card ai-card">
            <div class="row">
              <AppIcon name="shield" :size="15" class="head-icon" />
              <b>涉诈类型判定</b>
              <span class="spacer"></span>
              <span class="tag primary">置信度 {{ Math.round((analysis.case_type_judgement.confidence ?? 0) * 100) }}%</span>
            </div>
            <div class="judge-type">{{ analysis.case_type_judgement.case_type }}</div>
            <div class="muted small-label">判定依据支撑链</div>
            <ul class="basis-list">
              <li v-for="(b, i) in analysis.case_type_judgement.basis" :key="i">{{ b }}</li>
            </ul>
            <div class="row wrap" style="gap: 6px">
              <span v-for="w in analysis.case_type_judgement.hit_signal_words" :key="w" class="tag primary">{{ w }}</span>
            </div>
          </div>
          <!-- 侦查指引建议 -->
          <div v-if="analysis?.investigation_guide" class="card ai-card">
            <div class="row"><AppIcon name="search" :size="15" class="head-icon" /><b>侦查指引建议</b></div>
            <p v-if="analysis.investigation_guide.suspect_profile" class="guide-item">
              <span class="guide-key">嫌疑人画像</span>{{ analysis.investigation_guide.suspect_profile }}
            </p>
            <p v-if="analysis.investigation_guide.fund_interception" class="guide-item">
              <span class="guide-key">资金链拦截</span>{{ analysis.investigation_guide.fund_interception }}
            </p>
            <p v-if="analysis.investigation_guide.followup_investigation" class="guide-item">
              <span class="guide-key">补充侦查</span>{{ analysis.investigation_guide.followup_investigation }}
            </p>
          </div>
          <!-- 推荐补充问题 -->
          <div class="ai-sub-title">推荐补充问题</div>
          <div v-if="suggestions.length === 0" class="empty">暂无推荐问题</div>
          <div v-for="sug in suggestions" :key="sug.id" :class="['card sug-card', { pinned: sug.is_pinned, adopted: sug.is_adopted }]">
            <div class="row" style="align-items: flex-start">
              <AppIcon :name="sug.is_pinned ? 'warning' : 'zap'" :size="14" :class="sug.is_pinned ? 'gap-icon' : 'head-icon ai'" />
              <div style="flex: 1">
                <div class="sug-content">{{ sug.content }}</div>
                <div class="row wrap" style="gap: 6px; margin-top: 6px">
                  <span v-if="sug.is_pinned" class="tag error">重点缺口追问</span>
                  <span v-if="sug.target_chapter" class="tag">{{ sug.target_chapter }}</span>
                </div>
              </div>
            </div>
            <div class="row" style="justify-content: flex-end; margin-top: 10px">
              <button class="btn btn-primary btn-sm" :disabled="sug.is_adopted" @click="adopt(sug.id)">
                {{ sug.is_adopted ? '已加入问询' : '加入问询' }}
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- 右栏：五流证据区 -->
      <section class="wb-col col-flow">
        <div class="col-head">
          <AppIcon name="folder" :size="16" class="head-icon flow" />
          五流证据
          <span class="spacer"></span>
          <button class="btn btn-ghost btn-sm" @click="openDrawer">
            <AppIcon name="upload" :size="12" /> 材料
          </button>
        </div>
        <div class="col-body">
          <div class="row overall">
            <span class="muted">总体覆盖度</span>
            <span class="spacer"></span>
            <b>{{ Math.round(coverage?.overall_coverage ?? 0) }}%</b>
          </div>
          <div class="progress overall-bar"><i :style="{ width: (coverage?.overall_coverage ?? 0) + '%' }"></i></div>
          <div v-if="coverage?.has_key_gap" class="gap-banner">
            <AppIcon name="warning" :size="14" /> 存在重点缺口，请关注中栏追问建议
          </div>
          <div v-for="flow in coverage?.flows ?? []" :key="flow.flow_type" :class="['flow-card', flow.status]">
            <div class="row flow-head">
              <span :class="['flow-icon', FLOW_META[flow.flow_type].tone]">
                <AppIcon :name="FLOW_META[flow.flow_type].icon" :size="15" />
              </span>
              <b>{{ flow.flow_label }}</b>
              <span class="spacer"></span>
              <span class="badge-count flow-count">{{ flow.collected_count }}</span>
            </div>
            <div class="row" style="gap: 8px; margin: 8px 0 6px">
              <span :class="['tag', flowTone(flow)]">{{ STATUS_META[flow.status].label }}</span>
              <span class="muted small">{{ flow.collected_count }}/{{ flow.required_count }} 要素</span>
              <span class="spacer"></span>
              <span class="muted small">{{ Math.round(flow.coverage) }}%</span>
            </div>
            <div class="progress"><i :style="{ width: flow.coverage + '%' }"></i></div>
            <!-- 重点缺口高亮 -->
            <div v-if="flow.key_gaps.length" class="gap-list">
              <div v-for="gap in flow.key_gaps" :key="gap" class="gap-item">
                <AppIcon name="warning" :size="12" /> 缺口：{{ gap }}
              </div>
            </div>
            <!-- 证据摘要 -->
            <div v-if="flow.evidence_summary.length" class="evi-list">
              <div v-for="(evi, i) in flow.evidence_summary" :key="i" class="evi-item">
                <AppIcon name="file" :size="12" /> {{ evi }}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 材料抽屉（物理隔离于问答正文，IR-1） -->
    <div v-if="drawerOpen" class="drawer-overlay" @click="drawerOpen = false"></div>
    <aside v-if="drawerOpen" class="drawer no-print">
      <div class="drawer-head">
        <AppIcon name="folder" :size="16" /> 辅助材料
        <span class="spacer"></span>
        <button class="btn btn-ghost btn-icon" @click="drawerOpen = false"><AppIcon name="x" :size="14" /></button>
      </div>
      <div class="drawer-body">
        <div class="muted isolation">辅助材料仅作研判输入，物理隔离于正式问答正文</div>
        <!-- 拖拽上传区 -->
        <div class="drop-zone" @drop.prevent="onDrop" @dragover.prevent>
          <AppIcon name="upload" :size="22" class="muted" />
          <div class="muted small">拖拽文件到此处上传</div>
          <div class="row" style="gap: 8px; margin-top: 10px">
            <select v-model="uploadType" class="select" style="width: 130px; flex: none; padding: 7px 10px">
              <option v-for="t in MATERIAL_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
            <label class="btn btn-ghost btn-sm">
              选择文件
              <input type="file" hidden @change="($event.target as HTMLInputElement).files?.[0] && onUpload(($event.target as HTMLInputElement).files![0])" />
            </label>
          </div>
          <div v-if="uploading" class="small muted"><span class="spinner"></span> 上传中...</div>
        </div>
        <!-- 材料列表 -->
        <div v-if="materials.length === 0" class="empty">暂无辅助材料</div>
        <div v-for="m in materials" :key="m.id" class="mat-item">
          <AppIcon name="file" :size="16" class="muted" />
          <div style="flex: 1; min-width: 0">
            <div class="mat-name">{{ m.file_name }}</div>
            <div class="muted small">
              {{ MATERIAL_TYPES.find((t) => t.value === m.material_type)?.label }} · {{ fmtSize(m.file_size) }} ·
              {{ m.uploader_no }}
            </div>
          </div>
          <span :class="['tag', m.virus_scan_passed ? 'success' : 'error']">{{ m.virus_scan_passed ? '扫描通过' : '扫描异常' }}</span>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.wb {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-0);
}

.wb-top {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 58px;
  padding: 0 18px;
  background: var(--bg-1);
  border-bottom: 1px solid var(--border-1);
  flex-shrink: 0;
}

.stage-badge {
  border: 1px solid rgba(59, 109, 255, 0.5);
}

.timer {
  font-family: Consolas, monospace;
  font-size: 15px;
  font-weight: 600;
}

.progress-wrap {
  gap: 8px;
  font-size: 12.5px;
}

.wb-cols {
  flex: 1;
  display: grid;
  grid-template-columns: 1.25fr 1fr 0.95fr;
  gap: 1px;
  background: var(--border-1);
  min-height: 0;
}

.wb-col {
  background: var(--bg-0);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.col-qa {
  background: var(--bg-1);
}

.col-head {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-1);
  font-weight: 700;
  font-size: 14.5px;
  flex-shrink: 0;
}

.head-icon {
  color: var(--primary-hover);
}
.head-icon.ai {
  color: var(--warning);
}
.head-icon.flow {
  color: var(--accent);
}

.col-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px 30px;
}

.qa-search {
  display: flex;
  align-items: center;
  gap: 7px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  padding: 5px 10px;
  width: 170px;
}

.qa-search input {
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-1);
  font-size: 12.5px;
  width: 100%;
}

/* ---------- 左栏问答卡片 ---------- */
.chapter {
  margin-bottom: 18px;
}

.chapter-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: var(--text-2);
  margin-bottom: 10px;
  padding-left: 2px;
}

.chapter-count {
  font-size: 11.5px;
  font-weight: 400;
}

.qa-add {
  margin-bottom: 10px;
  gap: 8px;
}

.qa-card {
  background: var(--bg-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-m);
  padding: 12px 14px;
  margin-bottom: 10px;
  transition: border-color 0.15s;
}

.qa-card.answered {
  border-color: rgba(34, 197, 94, 0.35);
}

.qa-q {
  gap: 8px;
  align-items: flex-start;
}

.qa-q .ok {
  color: var(--success);
  margin-top: 2px;
  flex-shrink: 0;
}

.qa-q .muted {
  margin-top: 2px;
  flex-shrink: 0;
}

.qa-q-text {
  cursor: text;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.5;
}

.qa-q-edit {
  flex: 1;
  background: var(--bg-3);
  border: 1px solid var(--primary);
  border-radius: 6px;
  color: var(--text-1);
  font-size: 13.5px;
  padding: 4px 8px;
  outline: none;
}

.src-tag {
  font-size: 11px;
  padding: 1px 8px;
  flex-shrink: 0;
}

.icon-mini {
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 3px;
  border-radius: 5px;
  display: inline-flex;
}

.icon-mini:hover {
  color: var(--error);
  background: var(--bg-3);
}

.icon-mini.mic:hover,
.icon-mini.mic.on {
  color: var(--error);
}

.icon-mini.mic.on {
  animation: pulse 1s infinite;
}

@keyframes pulse {
  50% {
    opacity: 0.4;
  }
}

.qa-a {
  position: relative;
  margin-top: 9px;
}

.qa-a-input {
  width: 100%;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  color: var(--text-1);
  font-size: 13px;
  font-family: inherit;
  padding: 8px 34px 8px 10px;
  outline: none;
  resize: vertical;
  min-height: 52px;
}

.qa-a-input:focus {
  border-color: var(--primary);
}

.qa-a-input.recording {
  border-color: var(--error);
}

.qa-a .mic {
  position: absolute;
  right: 8px;
  bottom: 8px;
}

/* ---------- 中栏 AI ---------- */
.ai-card {
  padding: 14px 16px;
  margin: 0 0 12px;
}

.judge-type {
  font-size: 16px;
  font-weight: 700;
  color: var(--primary-hover);
  margin: 8px 0 4px;
}

.small-label {
  font-size: 11.5px;
  margin: 6px 0 4px;
}

.basis-list {
  margin: 0 0 8px;
  padding-left: 18px;
  color: var(--text-2);
  font-size: 12.5px;
  line-height: 1.8;
}

.guide-item {
  margin: 8px 0;
  font-size: 12.5px;
  color: var(--text-2);
  line-height: 1.7;
}

.guide-key {
  display: inline-block;
  background: var(--bg-4);
  border-radius: 5px;
  color: var(--text-1);
  font-size: 11.5px;
  padding: 1px 7px;
  margin-right: 8px;
}

.ai-sub-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-2);
  margin: 16px 0 10px;
}

.sug-card {
  padding: 12px 14px;
  margin: 0 0 10px;
}

.sug-card.pinned {
  border-color: rgba(239, 68, 68, 0.5);
}

.sug-card.adopted {
  opacity: 0.6;
}

.gap-icon {
  color: var(--error);
  margin-top: 2px;
}

.sug-content {
  font-size: 13px;
  line-height: 1.6;
}

/* ---------- 右栏五流 ---------- */
.overall {
  font-size: 12.5px;
  margin-bottom: 6px;
}

.overall-bar {
  margin-bottom: 12px;
}

.gap-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: var(--error);
  border-radius: 8px;
  font-size: 12.5px;
  padding: 8px 12px;
  margin-bottom: 12px;
}

.gap-banner.info {
  background: var(--primary-dim);
  border-color: rgba(59, 109, 255, 0.4);
  color: var(--primary-hover);
}

.flow-card {
  background: var(--bg-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-m);
  padding: 13px 14px;
  margin-bottom: 12px;
}

.flow-card.key_gap {
  border-color: rgba(239, 68, 68, 0.55);
}

.flow-head b {
  font-size: 13.5px;
}

.flow-icon {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.flow-icon.primary {
  background: var(--primary-dim);
  color: var(--primary-hover);
}
.flow-icon.success {
  background: rgba(34, 197, 94, 0.14);
  color: var(--success);
}
.flow-icon.warning {
  background: rgba(245, 158, 11, 0.14);
  color: var(--warning);
}
.flow-icon.error {
  background: rgba(239, 68, 68, 0.14);
  color: var(--error);
}
.flow-icon.purple {
  background: rgba(167, 139, 250, 0.16);
  color: var(--purple);
}

.flow-count {
  background: var(--bg-4);
  color: var(--text-2);
}

.small {
  font-size: 12px;
}

.gap-list {
  margin-top: 9px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.gap-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--error);
  font-size: 12px;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 6px;
  padding: 4px 8px;
}

.evi-list {
  margin-top: 9px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.evi-item {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-2);
  font-size: 12px;
  background: var(--bg-3);
  border-radius: 6px;
  padding: 5px 8px;
}

/* ---------- 材料抽屉 ---------- */
.isolation {
  font-size: 11.5px;
  background: var(--bg-3);
  border-radius: 7px;
  padding: 7px 10px;
  margin-bottom: 12px;
}

.drop-zone {
  border: 1.5px dashed var(--border-3);
  border-radius: var(--radius-m);
  padding: 22px 14px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin-bottom: 14px;
}

.mat-item {
  display: flex;
  align-items: center;
  gap: 10px;
  background: var(--bg-2);
  border: 1px solid var(--border-1);
  border-radius: var(--radius-m);
  padding: 10px 12px;
  margin-bottom: 10px;
}

.mat-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
