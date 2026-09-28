/**
 * BE-2 笔录生命周期接口（/sessions）
 */
import { httpDelete, httpGet, httpPost, httpPut } from '@/api/request'
import type {
  Chapter,
  PageResult,
  QAChapterGroup,
  QASource,
  SessionCreate,
  SessionDetail,
  SessionListItem,
  SessionRestore,
  Stage,
} from '@/types'

/** 笔录台账检索（6.1） */
export function listSessions(params: { keyword?: string; stage?: Stage; page?: number; page_size?: number }) {
  return httpGet<PageResult<SessionListItem>>('/sessions', params)
}

/** 笔录统计计数（工作台统计区） */
export function getStatistics() {
  return httpGet<Record<string, number>>('/sessions/statistics')
}

/** 新增笔录（接报录入） */
export function createSession(data: SessionCreate) {
  return httpPost<SessionDetail>('/sessions', data)
}

/** 笔录会话详情 */
export function getSession(sessionId: string) {
  return httpGet<SessionDetail>(`/sessions/${sessionId}`)
}

/** 更新接报草稿 */
export function updateDraft(sessionId: string, data: Partial<SessionCreate>) {
  return httpPut<SessionDetail>(`/sessions/${sessionId}`, data)
}

/** 阶段流转（4.5 状态机） */
export function transitStage(sessionId: string, targetStage: Stage) {
  return httpPost<SessionDetail>(`/sessions/${sessionId}/stage`, { target_stage: targetStage })
}

/** 选定模板并开始问询（templates → inquiry） */
export function selectTemplates(sessionId: string, templateIds: string[]) {
  return httpPost<SessionDetail>(`/sessions/${sessionId}/select-templates`, { template_ids: templateIds })
}

/** 断点续问恢复 */
export function restoreSession(sessionId: string) {
  return httpGet<SessionRestore>(`/sessions/${sessionId}/restore`)
}

/** 暂存现场快照（UI-4 顶部"暂时保存"） */
export function saveSnapshot(sessionId: string, snapshot: Record<string, unknown>) {
  return httpPost<null>(`/sessions/${sessionId}/snapshot`, snapshot)
}

/** 归档笔录 */
export function archiveSession(sessionId: string) {
  return httpPost<null>(`/sessions/${sessionId}/archive`)
}

/** 按章节获取问答（UI-4 左栏卡片流） */
export function getQAByChapter(sessionId: string) {
  return httpGet<QAChapterGroup[]>(`/sessions/${sessionId}/qa`)
}

/** 新增问答 */
export function createQA(sessionId: string, data: { chapter: Chapter; question: string; answer?: string; source?: QASource }) {
  return httpPost<unknown>(`/sessions/${sessionId}/qa`, data)
}

/** 编辑问答（行内双向绑定实时保存） */
export function updateQA(sessionId: string, qaId: string, data: { question?: string; answer?: string }) {
  return httpPut<unknown>(`/sessions/${sessionId}/qa/${qaId}`, data)
}

/** 删除问答 */
export function deleteQA(sessionId: string, qaId: string) {
  return httpDelete<null>(`/sessions/${sessionId}/qa/${qaId}`)
}
