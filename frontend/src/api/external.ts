/**
 * BE-3 外部系统集成接口（/external，智研判/智案管只读检索回填）
 */
import { httpGet, httpPost } from '@/api/request'
import type { ExternalBackfillData, ExternalSearchResult, ExternalSource } from '@/types'

/** 检索外部系统案件（FR-3.2.2） */
export function searchExternal(keyword: string, source: ExternalSource) {
  return httpPost<ExternalSearchResult>('/external/search', { keyword, source })
}

/** 获取字段映射回填数据（单选确认命中案件后） */
export function getBackfill(externalCaseId: string, source: ExternalSource) {
  return httpGet<ExternalBackfillData>('/external/backfill', {
    external_case_id: externalCaseId,
    source,
  })
}
