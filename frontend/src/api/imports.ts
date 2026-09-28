/**
 * BE-6 扩展 历史笔录解析导入接口（/imports）
 */
import { httpPost } from '@/api/request'
import type { ParseResult, ParsedQA, SessionDetail } from '@/types'

/** 解析粘贴的笔录文本 */
export function parseText(text: string) {
  return httpPost<ParseResult>('/imports/parse-text', { text })
}

/** 解析上传的 Word 笔录文档 */
export async function parseDocx(file: File) {
  const form = new FormData()
  form.append('file', file)
  return httpPost<ParseResult>('/imports/parse-docx', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

/** 解析结果转存为新问询会话 */
export function rebuildSession(data: {
  case_no: string
  case_category: string
  brief: string
  reporter_name: string
  parsed_qa: ParsedQA[]
}) {
  return httpPost<SessionDetail>('/imports/rebuild', data)
}
