/**
 * BE-4 模板配置接口（/templates）
 */
import { httpGet } from '@/api/request'
import type { TemplateDetail, TemplateOut } from '@/types'

/** 模板列表检索（6.3 全量模板库） */
export function listTemplates(params?: { keyword?: string; only_enabled?: boolean }) {
  return httpGet<TemplateOut[]>('/templates', params)
}

/** 模板详情（含标准问题集，供预览） */
export function getTemplate(templateId: string) {
  return httpGet<TemplateDetail>(`/templates/${templateId}`)
}

/** 多模板大纲装配预览 */
export function previewOutline(templateIds: string[]) {
  return httpGet<Record<string, unknown>[]>('/templates/outline-preview', { template_ids: templateIds })
}
