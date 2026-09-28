/**
 * BE-6 五流要素分析接口（/fiveflow）
 */
import { httpGet, httpPost } from '@/api/request'
import type { FiveFlowAnalysisResult } from '@/types'

/** 五流要素定义目录 */
export function getDefinitions() {
  return httpGet<unknown[]>('/fiveflow/definitions')
}

/** 会话五流覆盖度实时计算（UI-4 右栏） */
export function getCoverage(sessionId: string) {
  return httpGet<FiveFlowAnalysisResult>(`/fiveflow/sessions/${sessionId}/coverage`)
}

/** 触发要素抽取（问答变更后增量抽取） */
export function extractElements(sessionId: string, qaId?: string) {
  return httpPost<FiveFlowAnalysisResult>(`/fiveflow/sessions/${sessionId}/extract`, {
    session_id: sessionId,
    qa_id: qaId,
  })
}
