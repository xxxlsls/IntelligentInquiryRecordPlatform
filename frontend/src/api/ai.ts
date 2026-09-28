/**
 * BE-5 AI 研判推荐接口（/ai）
 */
import { httpGet, httpPost } from '@/api/request'
import type { AnalysisResult, LLMStatusOut, SuggestionOut, TemplateRecommendResult } from '@/types'

/** AI 智能推荐模板（FR-3.3.2） */
export function recommendTemplates(brief: string, caseCategory?: string, topN = 5) {
  return httpPost<TemplateRecommendResult>('/ai/recommend', {
    brief,
    case_category: caseCategory,
    top_n: topN,
  })
}

/** 触发 AI 侦查研判分析（问答变更后异步刷新中栏） */
export function analyzeSession(sessionId: string) {
  return httpPost<AnalysisResult>(`/ai/sessions/${sessionId}/analyze`)
}

/** 获取会话 AI 建议列表（中栏卡片） */
export function getSuggestions(sessionId: string) {
  return httpGet<SuggestionOut[]>(`/ai/sessions/${sessionId}/suggestions`)
}

/** 一键采纳推荐问题（GR-4：转左栏正式问答） */
export function adoptSuggestion(sessionId: string, suggestionId: string) {
  return httpPost<{ success: boolean; qa_id?: string | null; is_duplicate: boolean; message: string }>(
    `/ai/sessions/${sessionId}/adopt`,
    { suggestion_id: suggestionId },
  )
}

/** LLM 接入状态（工作台系统通知） */
export function getLLMStatus() {
  return httpGet<LLMStatusOut>('/ai/llm/status')
}
