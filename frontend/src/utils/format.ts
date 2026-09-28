/**
 * 通用格式化工具与领域常量映射（中文展示名对齐后端 enums.py）
 */
import type { Chapter, ElementStatus, FlowType, QASource, Stage } from '@/types'

/** 日期时间格式化：2024-09-12 15:30 */
export function fmtDateTime(value?: string | null): string {
  if (!value) return '-'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 日期格式化：2024-09-12 */
export function fmtDate(value?: string | null): string {
  return fmtDateTime(value).slice(0, 10)
}

/** 秒数格式化为 hh:mm:ss 计时展示（UI-4 顶部计时统计） */
export function fmtDuration(seconds: number): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(Math.floor(seconds / 3600))}:${p(Math.floor((seconds % 3600) / 60))}:${p(seconds % 60)}`
}

/** 字节数人类可读化（材料列表文件大小） */
export function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 笔录阶段（Stage）中文与展示色调 */
export const STAGE_META: Record<Stage, { label: string; tone: string }> = {
  intake: { label: '接报录入', tone: 'warning' },
  templates: { label: '模板选择', tone: 'warning' },
  inquiry: { label: '问询进行中', tone: 'primary' },
  completed: { label: '已完成', tone: 'success' },
}

/** 大纲章节标准顺序与中文名（对齐后端 CHAPTER_ORDER） */
export const CHAPTER_ORDER: Chapter[] = [
  'fixed_opening',
  'contact_lure',
  'fraud_process',
  'fund_loss',
  'evidence_supplement',
]

export const CHAPTER_LABEL: Record<Chapter, string> = {
  fixed_opening: '固定开头',
  contact_lure: '接触引流',
  fraud_process: '被骗经过',
  fund_loss: '资金损失',
  evidence_supplement: '证据补充',
}

/** 问答来源标记（UI-4 左栏来源标识） */
export const SOURCE_LABEL: Record<QASource, string> = {
  template: '模板',
  ai_recommend: 'AI 推荐',
  manual: '手动',
}

/** 五流类型图标与色调（UI-4 右栏流卡片） */
export const FLOW_META: Record<FlowType, { icon: string; tone: string }> = {
  person: { icon: 'users', tone: 'warning' },
  communication: { icon: 'phone', tone: 'success' },
  network: { icon: 'globe', tone: 'purple' },
  fund: { icon: 'banknote', tone: 'primary' },
  delivery: { icon: 'truck', tone: 'error' },
}

/** 五流要素/流状态中文与色调（5.3 状态判定） */
export const STATUS_META: Record<ElementStatus, { label: string; tone: string }> = {
  collected: { label: '已收集', tone: 'success' },
  need_supplement: { label: '需补充', tone: 'warning' },
  key_gap: { label: '重点缺口', tone: 'error' },
  not_involved: { label: '不涉及', tone: '' },
}

/** 角色中文名（UI-1 顶部用户信息） */
export const ROLE_LABEL: Record<string, string> = {
  case_officer: '办案民警',
  analyst: '反诈研判员',
  admin: '系统管理员',
}

/** 断点续问 target_view → 前端路由（4.5 恢复目标界面） */
export function restoreRoute(targetView: string, sessionId: string): string {
  switch (targetView) {
    case 'intake_modal':
      return `/intake/${sessionId}`
    case 'template_page':
      return `/templates/${sessionId}`
    case 'workbench':
      return `/workbench/${sessionId}`
    case 'preview_page':
      return `/document/${sessionId}`
    default:
      return `/workbench/${sessionId}`
  }
}
