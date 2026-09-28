/**
 * BE-7 文书预览与导出接口（/documents）
 */
import { httpDownload, httpGet } from '@/api/request'
import type { DocumentPreview } from '@/types'

/** 红头笔录在线预览（FR-3.5.1） */
export function previewDocument(sessionId: string) {
  return httpGet<DocumentPreview>(`/documents/sessions/${sessionId}/preview`)
}

/** 导出 DOCX 笔录文书（FR-3.5.2，可选附五流覆盖表/AI 研判报告） */
export function exportDocument(
  sessionId: string,
  options: { include_five_flow_table?: boolean; include_analysis_report?: boolean } = {},
) {
  return httpDownload(
    `/documents/sessions/${sessionId}/export`,
    {
      include_five_flow_table: options.include_five_flow_table ?? false,
      include_analysis_report: options.include_analysis_report ?? false,
    },
    '询问笔录.docx',
  )
}
