/**
 * UI-2 案件基础信息采集页（FR-3.2.1 / FR-3.2.2）
 *
 * 布局（原型 n9cOe2）：
 * - 左侧主表单：基本信息（案件编号/类别/报案人等，必填校验）+ 案情描述；
 * - 右侧"历史案件同步"折叠面板：关键字检索外部系统（智研判/智案管），
 *   命中候选单选确认后自动回填表单字段（回填后仍可手动修改）；
 * - 底部操作区：取消 / 保存草稿 / 进入模板选择（校验不通过阻止流转）。
 */
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { searchExternal, getBackfill } from '@/api/external'
import { createSession, getSession, updateDraft, transitStage } from '@/api/sessions'
import { listTemplates } from '@/api/templates'
import AppIcon from '@/components/AppIcon.vue'
import TopBar from '@/components/TopBar.vue'
import type { ExternalCaseCandidate, ExternalSource } from '@/types'
import { toast } from '@/utils/toast'

const route = useRoute()
const router = useRouter()
const sessionId = route.params.sessionId as string | undefined

/** 接报表单（字段对齐后端 SessionCreate） */
const form = reactive({
  case_no: '',
  case_category: '',
  reporter_name: '',
  reporter_id_card: '',
  reporter_phone: '',
  handling_org: '',
  brief: '',
})
const errors = reactive<Record<string, string>>({})
const saving = ref(false)
/** 案件类别候选（取自模板库案由类别，19 类案由 + 其他） */
const categories = ref<string[]>([])

// ---------- 外部系统同步面板 ----------
const syncOpen = ref(true)
const syncKeyword = ref('')
const syncSource = ref<ExternalSource>('zhiyanpan')
const candidates = ref<ExternalCaseCandidate[]>([])
const searching = ref(false)
const selectedCandidate = ref('')

onMounted(async () => {
  // 类别候选来自模板库案由（去重）
  listTemplates({ only_enabled: true })
    .then((list) => {
      categories.value = [...new Set(list.map((t) => t.category))]
      if (!categories.value.includes('其他')) categories.value.push('其他')
    })
    .catch(() => undefined)
  // 草稿编辑：恢复已录表单（4.5 intake 断点恢复）
  if (sessionId) {
    const detail = await getSession(sessionId)
    const c = detail.case_info
    if (c) {
      form.case_no = c.case_no
      form.case_category = c.case_category
      form.brief = c.brief
      form.handling_org = c.handling_org
      form.reporter_name = c.reporter?.name ?? ''
      form.reporter_id_card = c.reporter?.id_card ?? ''
      form.reporter_phone = c.reporter?.phone ?? ''
    }
  }
})

/** 前端必填校验（FR-3.2.1 输入校验规则，与后端一致） */
function validate(): boolean {
  Object.keys(errors).forEach((k) => delete errors[k])
  if (!form.case_no.trim()) errors.case_no = '案件编号为必填项'
  else if (!/^[A-Za-z0-9\-_]{4,50}$/.test(form.case_no.trim()))
    errors.case_no = '编号格式：4-50 位字母、数字、连字符或下划线'
  if (!form.case_category) errors.case_category = '请选择案件类别'
  if (!form.reporter_name.trim()) errors.reporter_name = '报案人姓名为必填项'
  if (form.reporter_id_card && !/^\d{17}[\dXx]|\d{15}$/.test(form.reporter_id_card.trim()))
    errors.reporter_id_card = '证件号应为 15 或 18 位'
  if (form.reporter_phone && !/^1[3-9]\d{9}$/.test(form.reporter_phone.trim()))
    errors.reporter_phone = '手机号应为 11 位有效号码'
  if (!form.brief.trim() || form.brief.trim().length < 10) errors.brief = '简要案情为必填项（≥10 字）'
  return Object.keys(errors).length === 0
}

/** 保存草稿：新建（POST /sessions）或更新（PUT /sessions/{id}） */
async function saveDraft(): Promise<string | null> {
  if (!validate()) {
    toast.error('请完善必填项后再保存')
    return null
  }
  saving.value = true
  try {
    if (sessionId) {
      await updateDraft(sessionId, { ...form })
      toast.success('草稿已保存')
      return sessionId
    }
    const detail = await createSession({ ...form })
    toast.success('笔录创建成功，已保存草稿')
    return detail.id
  } catch {
    return null
  } finally {
    saving.value = false
  }
}

/** 进入模板选择：保存草稿后流转 intake → templates */
async function toTemplates() {
  const id = await saveDraft()
  if (!id) return
  try {
    await transitStage(id, 'templates')
    await router.push(`/templates/${id}`)
  } catch {
    // 拦截器已提示
  }
}

/** 外部系统关键字检索（FR-3.2.2 步骤 1~2） */
async function doSearch() {
  if (!syncKeyword.value.trim()) return toast.error('请输入检索关键字')
  searching.value = true
  selectedCandidate.value = ''
  try {
    const res = await searchExternal(syncKeyword.value.trim(), syncSource.value)
    candidates.value = res.candidates
    if (res.total === 0) toast.info(res.message || '未命中外部案件')
  } finally {
    searching.value = false
  }
}

/** 单选候选案件 → 获取映射回填数据并写入表单（FR-3.2.2 步骤 3~4） */
async function onPickCandidate(cand: ExternalCaseCandidate) {
  selectedCandidate.value = cand.external_case_id
  const data = await getBackfill(cand.external_case_id, cand.source)
  // 回填后字段仍可手动修改核对
  if (data.case_no) form.case_no = data.case_no
  if (data.case_category) form.case_category = data.case_category
  if (data.brief) form.brief = data.brief
  if (data.handling_org) form.handling_org = data.handling_org
  if (data.reporter_name) form.reporter_name = data.reporter_name
  if (data.reporter_id_card) form.reporter_id_card = data.reporter_id_card
  if (data.reporter_phone) form.reporter_phone = data.reporter_phone
  toast.success('外部案件数据已回填，请核对后保存')
}
</script>

<template>
  <div class="page">
    <TopBar />
    <div class="page-body">
      <div class="page-head">
        <h1 class="page-title">案件基础信息采集</h1>
        <p class="page-sub">请完整填写案件基本信息，系统将自动匹配适用的问询模板</p>
      </div>

      <div class="intake-grid">
        <!-- 左侧主表单 -->
        <div class="col">
          <div class="card">
            <h3 class="card-title bar">基本信息</h3>
            <div class="field">
              <label class="field-label">案件编号<span class="req">*</span></label>
              <input v-model="form.case_no" :class="['input', { invalid: errors.case_no }]" placeholder="自动生成或手动输入" />
              <div v-if="errors.case_no" class="field-error">{{ errors.case_no }}</div>
            </div>
            <div class="two-col">
              <div class="field">
                <label class="field-label">案件类别<span class="req">*</span></label>
                <select v-model="form.case_category" :class="['select', { invalid: errors.case_category }]">
                  <option value="" disabled>选择案件类别</option>
                  <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
                </select>
                <div v-if="errors.case_category" class="field-error">{{ errors.case_category }}</div>
              </div>
              <div class="field">
                <label class="field-label">办案单位</label>
                <input v-model="form.handling_org" class="input" placeholder="默认当前机构" />
              </div>
            </div>
            <div class="two-col">
              <div class="field">
                <label class="field-label">报案人姓名<span class="req">*</span></label>
                <input v-model="form.reporter_name" :class="['input', { invalid: errors.reporter_name }]" placeholder="请输入报案人姓名" />
                <div v-if="errors.reporter_name" class="field-error">{{ errors.reporter_name }}</div>
              </div>
              <div class="field">
                <label class="field-label">报案人证件号</label>
                <input v-model="form.reporter_id_card" :class="['input', { invalid: errors.reporter_id_card }]" placeholder="选填，15/18 位" />
                <div v-if="errors.reporter_id_card" class="field-error">{{ errors.reporter_id_card }}</div>
              </div>
            </div>
            <div class="field" style="margin-bottom: 4px">
              <label class="field-label">报案人联系电话</label>
              <input v-model="form.reporter_phone" :class="['input', { invalid: errors.reporter_phone }]" placeholder="选填，11 位手机号" />
              <div v-if="errors.reporter_phone" class="field-error">{{ errors.reporter_phone }}</div>
            </div>
          </div>

          <div class="card">
            <h3 class="card-title bar">案情描述</h3>
            <div class="field">
              <label class="field-label">简要案情<span class="req">*</span></label>
              <textarea
                v-model="form.brief"
                :class="['textarea', { invalid: errors.brief }]"
                placeholder="请简要描述案件经过（200字以内，≥10 字）"
                maxlength="200"
              ></textarea>
              <div v-if="errors.brief" class="field-error">{{ errors.brief }}</div>
            </div>
          </div>
        </div>

        <!-- 右侧历史案件同步面板 -->
        <div class="col">
          <div class="card sync-card">
            <h3 class="card-title" style="cursor: pointer" @click="syncOpen = !syncOpen">
              <AppIcon name="sync" :size="16" class="sync-icon" />
              历史案件同步
              <span class="spacer"></span>
              <AppIcon :name="syncOpen ? 'chevron-down' : 'chevron-right'" :size="16" class="muted" />
            </h3>
            <template v-if="syncOpen">
              <p class="muted sync-desc">根据报案人信息快速检索历史案件</p>
              <div class="row" style="gap: 8px">
                <select v-model="syncSource" class="select" style="width: 110px; flex: none">
                  <option value="zhiyanpan">智研判</option>
                  <option value="zhianguan">智案管</option>
                </select>
                <input v-model="syncKeyword" class="input" placeholder="输入姓名或身份证号" @keyup.enter="doSearch" />
              </div>
              <button class="btn btn-primary sync-btn" :disabled="searching" @click="doSearch">
                <span v-if="searching" class="spinner"></span>
                快速检索
              </button>
              <!-- 检索结果区：候选案件单选确认回填 -->
              <div v-if="candidates.length" class="col cand-list">
                <label
                  v-for="cand in candidates"
                  :key="cand.external_case_id"
                  :class="['cand', { on: selectedCandidate === cand.external_case_id }]"
                >
                  <input
                    type="radio"
                    name="candidate"
                    :checked="selectedCandidate === cand.external_case_id"
                    @change="onPickCandidate(cand)"
                  />
                  <div>
                    <div class="row" style="gap: 8px">
                      <span class="mono case-no">{{ cand.case_no }}</span>
                      <span v-if="cand.case_category" class="tag">{{ cand.case_category }}</span>
                    </div>
                    <div class="muted small">{{ cand.victim_name || '-' }} · {{ cand.match_hint || cand.handling_org || '' }}</div>
                  </div>
                </label>
              </div>
              <div v-else class="result-placeholder">检索结果将在此显示</div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部操作区 -->
    <div class="footer-bar">
      <button class="btn btn-ghost" @click="router.back()">取消</button>
      <button class="btn btn-ghost" :disabled="saving" @click="saveDraft">保存草稿</button>
      <button class="btn btn-primary" :disabled="saving" @click="toTemplates">进入模板选择</button>
    </div>
  </div>
</template>

<style scoped>
.intake-grid {
  display: grid;
  grid-template-columns: 1.9fr 1fr;
  gap: 22px;
  align-items: start;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}

.sync-card {
  position: sticky;
  top: 80px;
}

.sync-icon {
  color: var(--primary-hover);
}

.sync-desc {
  margin: 0 0 14px;
  font-size: 13px;
}

.sync-btn {
  width: 100%;
  margin-top: 12px;
}

.result-placeholder {
  margin-top: 14px;
  background: var(--bg-3);
  border: 1px dashed var(--border-2);
  border-radius: var(--radius-m);
  color: var(--text-3);
  text-align: center;
  padding: 22px 0;
  font-size: 13px;
}

.cand-list {
  gap: 10px;
  margin-top: 14px;
}

.cand {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: var(--radius-m);
  padding: 12px;
  cursor: pointer;
  transition: border-color 0.15s;
}

.cand.on {
  border-color: var(--primary);
  background: var(--primary-dim);
}

.cand input {
  margin-top: 4px;
  accent-color: var(--primary);
}

.case-no {
  font-weight: 700;
}

.small {
  font-size: 12px;
  margin-top: 3px;
}
</style>
