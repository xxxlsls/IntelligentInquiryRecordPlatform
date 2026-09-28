/**
 * UI-5 笔录生成与编辑页（FR-3.5.1 预览 / FR-3.5.2 导出）
 *
 * 布局（原型 xQNHn / 需求 6.5）：
 * - 顶部操作区：编辑视图/预览视图切换、导出（DOCX 选项）、打印、保存笔录、返回工作台；
 * - 左侧编辑工具栏：AI 辅助（智能纠错/法律术语插入）、格式工具（加粗/斜体/下划线）、
 *   段落（对齐/列表/缩进），编辑视图下作用于文书内容；
 * - 中间预览区：标准红头格式询问笔录全文（红头标题/案件信息/问答正文/落款）；
 * - 右侧信息面板：笔录信息（生成时间/问题总数/回答完成度/字数/质量评分）、
 *   版本历史、快速导出（Word/PDF）。
 *
 * 说明：文书正文数据源为后端问答（IR-2 已过滤空白项）；编辑视图的排版调整
 * 仅本地暂存（本浏览器），正式内容以工作台问答为准。
 */
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getCoverage } from '@/api/fiveflow'
import { exportDocument, previewDocument } from '@/api/documents'
import { getSession } from '@/api/sessions'
import AppIcon from '@/components/AppIcon.vue'
import type { DocumentPreview, SessionDetail } from '@/types'
import { fmtDateTime } from '@/utils/format'
import { toast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId as string

const preview = ref<DocumentPreview | null>(null)
const session = ref<SessionDetail | null>(null)
const overallCoverage = ref(0)
const mode = ref<'edit' | 'preview'>('preview')
const exporting = ref(false)

/** 导出选项（FR-3.5.2：附五流覆盖表/AI 研判报告） */
const exportOpts = ref({ fiveFlow: false, analysis: false })
const exportDialog = ref(false)

// 编辑视图：本地排版暂存（localStorage，仅本浏览器）
const LOCAL_KEY = `ip_doc_html_${sessionId}`
const editorRef = ref<HTMLDivElement | null>(null)
const editorHtml = ref('')
const charCount = ref(0)

/** 常用法律术语（点击插入光标处） */
const LEGAL_TERMS = ['犯罪嫌疑人', '被害人', '涉案资金', '电信网络诈骗', '强制措施', '证据链']
const termPanel = ref(false)

onMounted(async () => {
  const [doc, detail] = await Promise.all([previewDocument(sessionId), getSession(sessionId)])
  preview.value = doc
  session.value = detail
  getCoverage(sessionId)
    .then((res) => (overallCoverage.value = res.overall_coverage))
    .catch(() => undefined)
  editorHtml.value = localStorage.getItem(LOCAL_KEY) || ''
  updateCharCount()
})

/** 问答正文纯文本（字数统计） */
const plainText = computed(() =>
  (preview.value?.qa_paragraphs ?? []).map((p) => `${p.question}\n${p.answer}`).join('\n'),
)

/** 质量评分：问询进度 60% + 五流覆盖度 40%（前端综合评估展示） */
const qualityScore = computed(() =>
  Math.round(0.6 * (session.value?.progress ?? 0) + 0.4 * overallCoverage.value),
)

function updateCharCount() {
  if (mode.value === 'edit' && editorRef.value) {
    charCount.value = editorRef.value.innerText.replace(/\s/g, '').length
  } else {
    charCount.value = plainText.value.replace(/\s/g, '').length
  }
}

/** 视图切换：进入编辑视图时将预览渲染结果注入可编辑容器 */
async function switchMode(next: 'edit' | 'preview') {
  if (next === mode.value) return
  if (next === 'edit') {
    mode.value = 'edit'
    await nextTick()
    if (editorRef.value) {
      editorRef.value.innerHTML = editorHtml.value || buildSheetHtml()
      editorRef.value.focus()
    }
  } else {
    // 离开编辑视图时捕获当前排版
    if (editorRef.value) editorHtml.value = editorRef.value.innerHTML
    mode.value = 'preview'
  }
  updateCharCount()
}

/** 由预览数据构建文书 HTML（编辑视图初始内容） */
function buildSheetHtml(): string {
  const p = preview.value
  if (!p) return ''
  const paras = p.qa_paragraphs
    .map((item) => `<p class="doc-q">问：${item.question}</p><p class="doc-a">答：${item.answer}</p>`)
    .join('')
  return `
    <div class="doc-red">${p.red_header_title}</div>
    <div class="doc-meta">
      <p>案件编号：${p.case_no}</p>
      <p>案件类型：${p.case_category ?? '-'}</p>
      <p>问询时间：${p.inquiry_time ?? '-'}</p>
      <p>询问人：${p.inquirer ?? '-'}　被询问人：${p.interviewee ?? '-'}</p>
    </div>
    ${paras}
    <div class="doc-sign">被询问人签名：＿＿＿＿＿＿＿＿　　日期：＿＿＿＿年＿＿月＿＿日</div>`
}

/** 格式工具（编辑视图，execCommand 富文本操作） */
function exec(command: string) {
  if (mode.value !== 'edit') return toast.info('请先切换到编辑视图')
  document.execCommand(command)
  editorRef.value?.focus()
}

/** 智能纠错：本地规则检查并修正常见排版问题 */
function autoCorrect() {
  if (mode.value !== 'edit' || !editorRef.value) return toast.info('请先切换到编辑视图')
  const before = editorRef.value.innerHTML
  const after = before
    .replace(/([，。；：！？])\1+/g, '$1') // 重复标点
    .replace(/ {2,}/g, ' ') // 连续空格
    .replace(/　{2,}/g, '　') // 连续全角空格
  editorRef.value.innerHTML = after
  toast.success(after === before ? '未发现排版问题' : '智能纠错完成')
}

/** 法律术语插入光标处 */
function insertTerm(term: string) {
  exec('insertText')
  if (mode.value === 'edit' && editorRef.value) {
    document.execCommand('insertText', false, term)
  }
  termPanel.value = false
}

/** 保存笔录：编辑排版本地暂存 */
function saveLocal() {
  if (mode.value === 'edit' && editorRef.value) {
    editorHtml.value = editorRef.value.innerHTML
    localStorage.setItem(LOCAL_KEY, editorHtml.value)
    toast.success('笔录排版已本地暂存')
  } else {
    toast.info('预览视图无需保存，内容以工作台问答为准')
  }
  updateCharCount()
}

/** 导出 DOCX（后端生成标准红头文书） */
async function doExport() {
  exporting.value = true
  try {
    await exportDocument(sessionId, {
      include_five_flow_table: exportOpts.value.fiveFlow,
      include_analysis_report: exportOpts.value.analysis,
    })
    toast.success('DOCX 文书已导出')
    exportDialog.value = false
  } finally {
    exporting.value = false
  }
}

/** 打印 / 导出 PDF（浏览器打印对话框，打印样式仅输出文书纸张） */
function printDoc() {
  window.print()
}

/** 版本历史（后端会话时间线：初始版本 + 当前版本） */
const versions = computed(() => {
  const s = session.value
  if (!s) return []
  const list = [
    { name: 'V 当前', time: fmtDateTime(s.updated_at), note: '系统自动保存', current: true },
  ]
  if (s.created_at !== s.updated_at) {
    list.push({ name: 'V1', time: fmtDateTime(s.created_at), note: '初始版本', current: false })
  }
  return list
})
</script>

<template>
  <div class="doc-page">
    <!-- 顶部操作区 -->
    <header class="topbar no-print">
      <button class="btn btn-ghost btn-icon" title="返回工作台" @click="router.push(`/workbench/${sessionId}`)">
        <AppIcon name="arrow-left" :size="15" />
      </button>
      <div class="topbar-title">笔录生成与编辑</div>
      <div class="topbar-divider"></div>
      <span class="topbar-muted">案件 {{ preview?.case_no }}</span>
      <span class="spacer"></span>
      <div class="mode-switch">
        <button :class="['btn', 'btn-sm', { active: mode === 'edit' }]" @click="switchMode('edit')">编辑视图</button>
        <button :class="['btn', 'btn-sm', { active: mode === 'preview' }]" @click="switchMode('preview')">预览视图</button>
      </div>
      <button class="btn btn-ghost btn-sm" @click="exportDialog = true">
        <AppIcon name="download" :size="14" /> 导出
      </button>
      <button class="btn btn-ghost btn-sm" @click="printDoc">
        <AppIcon name="printer" :size="14" /> 打印
      </button>
      <button class="btn btn-primary btn-sm" @click="saveLocal">
        <AppIcon name="save" :size="14" /> 保存笔录
      </button>
    </header>

    <div class="doc-body">
      <!-- 左侧编辑工具栏 -->
      <aside class="tool-col no-print">
        <div class="tool-title">编辑工具</div>
        <div class="muted tool-sub">快速编辑和格式化</div>

        <div class="tool-group">AI 辅助</div>
        <button class="tool-btn" @click="autoCorrect"><AppIcon name="zap" :size="14" /> 智能纠错</button>
        <div class="tool-btn-wrap">
          <button class="tool-btn" @click="termPanel = !termPanel">
            <AppIcon name="edit" :size="14" /> 法律术语 <span class="tag primary new-tag">NEW</span>
          </button>
          <div v-if="termPanel" class="term-panel">
            <button v-for="t in LEGAL_TERMS" :key="t" class="term-item" @click="insertTerm(t)">{{ t }}</button>
          </div>
        </div>

        <div class="tool-group">格式工具</div>
        <button class="tool-btn" @click="exec('bold')"><b>B</b> 加粗</button>
        <button class="tool-btn" @click="exec('italic')"><i>I</i> 斜体</button>
        <button class="tool-btn" @click="exec('underline')"><u>U</u> 下划线</button>

        <div class="tool-group">段落</div>
        <button class="tool-btn" @click="exec('justifyFull')"><AppIcon name="list" :size="14" /> 对齐</button>
        <button class="tool-btn" @click="exec('insertUnorderedList')"><AppIcon name="list" :size="14" /> 列表</button>
        <button class="tool-btn" @click="exec('indent')"><AppIcon name="chevron-right" :size="14" /> 缩进</button>
      </aside>

      <!-- 中间文书区 -->
      <main class="sheet-col">
        <!-- 编辑视图：可编辑容器（本地排版暂存） -->
        <div
          v-if="mode === 'edit'"
          ref="editorRef"
          class="doc-sheet print-area"
          contenteditable="true"
          @input="updateCharCount"
        ></div>
        <!-- 预览视图：红头文书结构化渲染 -->
        <div v-else-if="preview" class="doc-sheet print-area">
          <div class="doc-red">{{ preview.red_header_title }}</div>
          <div class="doc-meta">
            <p>案件编号：{{ preview.case_no }}</p>
            <p>案件类型：{{ preview.case_category ?? '-' }}</p>
            <p>问询时间：{{ preview.inquiry_time ?? '-' }}</p>
            <p>询问人：{{ preview.inquirer ?? '-' }}　被询问人：{{ preview.interviewee ?? '-' }}</p>
          </div>
          <template v-for="(item, i) in preview.qa_paragraphs" :key="i">
            <p class="doc-q">问：{{ item.question }}</p>
            <p class="doc-a">答：{{ item.answer }}</p>
          </template>
          <div v-if="preview.qa_paragraphs.length === 0" class="doc-empty">暂无已作答问答，返回工作台继续录入</div>
          <div class="doc-sign">被询问人签名：＿＿＿＿＿＿＿＿　　日期：＿＿＿＿年＿＿月＿＿日</div>
        </div>
        <div v-else class="loading-mask"><span class="spinner"></span>正在渲染文书...</div>
      </main>

      <!-- 右侧信息面板 -->
      <aside class="info-col no-print">
        <div class="tool-title row"><AppIcon name="file" :size="15" /> 笔录信息</div>
        <div class="info-card">
          <div class="muted">生成时间</div>
          <b>{{ fmtDateTime(session?.updated_at) }}</b>
        </div>
        <div class="info-card">
          <div class="muted">问题总数</div>
          <b>{{ preview?.answered_count ?? 0 }} 题已作答</b>
        </div>
        <div class="info-card">
          <div class="muted">回答完成度</div>
          <b>{{ session?.progress ?? 0 }}%</b>
        </div>
        <div class="info-card">
          <div class="muted">笔录字数</div>
          <b>{{ charCount.toLocaleString() }} 字</b>
        </div>
        <div class="info-card">
          <div class="muted">质量评分</div>
          <b class="score">{{ qualityScore }} 分</b>
        </div>

        <div class="tool-title" style="margin-top: 18px">版本历史</div>
        <div v-for="v in versions" :key="v.name" :class="['ver-item', { current: v.current }]">
          <div class="row" style="gap: 8px">
            <b>{{ v.name }}</b>
            <span v-if="v.current" class="tag primary">当前</span>
          </div>
          <div class="muted ver-time">{{ v.time }} · {{ v.note }}</div>
        </div>

        <div class="tool-title" style="margin-top: 18px">快速导出</div>
        <button class="tool-btn" @click="exportDialog = true">
          <AppIcon name="file" :size="14" /> 导出 Word <AppIcon name="chevron-right" :size="13" class="spacer" />
        </button>
        <button class="tool-btn" @click="printDoc">
          <AppIcon name="printer" :size="14" /> 导出 PDF <AppIcon name="chevron-right" :size="13" class="spacer" />
        </button>
      </aside>
    </div>

    <!-- 导出选项弹窗 -->
    <div v-if="exportDialog" class="modal-overlay" @click.self="exportDialog = false">
      <div class="modal" style="width: 420px">
        <h3 class="modal-title">导出 DOCX 笔录文书</h3>
        <label class="opt-row">
          <input v-model="exportOpts.fiveFlow" type="checkbox" />
          附带五流证据覆盖表（8.2）
        </label>
        <label class="opt-row">
          <input v-model="exportOpts.analysis" type="checkbox" />
          附带 AI 侦查研判报告（8.3）
        </label>
        <div class="row" style="justify-content: flex-end; gap: 10px; margin-top: 18px">
          <button class="btn btn-ghost" @click="exportDialog = false">取消</button>
          <button class="btn btn-primary" :disabled="exporting" @click="doExport">
            <span v-if="exporting" class="spinner"></span> 导出
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.doc-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-0);
}

.mode-switch {
  display: flex;
  background: var(--bg-3);
  border-radius: 9px;
  padding: 3px;
  gap: 3px;
}

.mode-switch .btn {
  background: transparent;
  padding: 5px 14px;
}

.mode-switch .btn.active {
  background: var(--primary);
}

.doc-body {
  flex: 1;
  display: grid;
  grid-template-columns: 220px 1fr 280px;
  gap: 1px;
  background: var(--border-1);
  min-height: 0;
}

.tool-col,
.info-col {
  background: var(--bg-1);
  padding: 18px 16px;
  overflow-y: auto;
}

.tool-title {
  font-size: 14.5px;
  font-weight: 700;
  margin-bottom: 4px;
}

.tool-sub {
  font-size: 12px;
  margin-bottom: 14px;
}

.tool-group {
  font-size: 12px;
  color: var(--text-3);
  margin: 16px 0 8px;
}

.tool-btn {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  background: var(--bg-3);
  border: 1px solid var(--border-1);
  border-radius: 8px;
  color: var(--text-1);
  font-size: 13px;
  font-family: inherit;
  padding: 9px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.tool-btn:hover {
  border-color: var(--primary);
}

.tool-btn .spacer {
  margin-left: auto;
}

.tool-btn-wrap {
  position: relative;
}

.new-tag {
  font-size: 10px;
  padding: 0 6px;
  margin-left: auto;
}

.term-panel {
  position: absolute;
  left: 100%;
  top: 0;
  margin-left: 8px;
  width: 150px;
  background: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 10px;
  padding: 8px;
  z-index: 30;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
}

.term-item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--text-2);
  font-size: 12.5px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.term-item:hover {
  background: var(--bg-4);
  color: var(--text-1);
}

/* ---------- 文书纸张 ---------- */
.sheet-col {
  background: var(--bg-0);
  overflow-y: auto;
  padding: 26px 34px;
  display: flex;
  justify-content: center;
}

.doc-sheet {
  width: 100%;
  max-width: 860px;
  min-height: 100%;
  background: #fdfdfb;
  color: #1a1a1a;
  border-radius: 4px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
  padding: 56px 64px;
  font-size: 15px;
  line-height: 2;
  outline: none;
}
</style>

<!-- 文书正文排版样式（非 scoped：编辑视图注入的 HTML 同样生效） -->
<style>
.doc-red {
  text-align: center;
  color: #d0342c;
  font-size: 30px;
  font-weight: 800;
  letter-spacing: 6px;
  font-family: 'SimSun', '宋体', serif;
  padding-bottom: 14px;
  border-bottom: 3px solid #d0342c;
  margin-bottom: 26px;
}

.doc-meta p {
  margin: 2px 0;
  font-size: 14px;
}

.doc-q {
  margin: 16px 0 4px;
  font-weight: 700;
  text-indent: 0;
}

.doc-a {
  margin: 0 0 4px;
  text-indent: 2em;
}

.doc-empty {
  text-align: center;
  color: #999;
  padding: 40px 0;
}

.doc-sign {
  margin-top: 44px;
  font-size: 14px;
}

/* ---------- 右侧信息面板 ---------- */
.info-card {
  background: var(--bg-3);
  border-radius: var(--radius-m);
  padding: 10px 14px;
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.info-card .muted {
  font-size: 11.5px;
}

.info-card b {
  font-size: 14px;
}

.score {
  color: var(--primary-hover);
  font-size: 17px;
}

.ver-item {
  background: var(--bg-3);
  border: 1px solid transparent;
  border-radius: var(--radius-m);
  padding: 10px 14px;
  margin-bottom: 8px;
}

.ver-item.current {
  border-color: var(--primary);
  background: var(--primary-dim);
}

.ver-time {
  font-size: 11.5px;
  margin-top: 2px;
}

.opt-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 4px;
  cursor: pointer;
  font-size: 13.5px;
}

.opt-row input {
  accent-color: var(--primary);
  width: 15px;
  height: 15px;
}
</style>
