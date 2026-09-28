/**
 * 前端类型定义（与后端 backend/app/schemas 一一对应）
 *
 * 字段命名保持与后端 Pydantic 模型一致（snake_case），避免映射成本。
 */

// ---------- 通用响应 ----------
export interface ApiResponse<T> {
  success: boolean
  code: string
  message: string
  data: T | null
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ---------- 枚举（对应 backend/app/core/enums.py） ----------
export type Stage = 'intake' | 'templates' | 'inquiry' | 'completed'
export type Role = 'case_officer' | 'analyst' | 'admin'
export type Chapter =
  | 'fixed_opening'
  | 'contact_lure'
  | 'fraud_process'
  | 'fund_loss'
  | 'evidence_supplement'
export type QASource = 'template' | 'ai_recommend' | 'manual'
export type FlowType = 'person' | 'communication' | 'network' | 'fund' | 'delivery'
export type ElementStatus = 'collected' | 'need_supplement' | 'key_gap' | 'not_involved'
export type SuggestionType =
  | 'case_type_judge'
  | 'investigation_guide'
  | 'followup_question'
  | 'key_gap_question'
export type MaterialType =
  | 'call_record'
  | 'transfer_flow'
  | 'chat_screenshot'
  | 'image'
  | 'pdf'
  | 'document'
export type ExternalSource = 'zhiyanpan' | 'zhianguan'

// ---------- BE-1 认证 ----------
export interface UserInfo {
  id: string
  officer_no: string
  name: string
  role: Role
  org_id: string
  org_name?: string | null
  org_path?: string | null
  permissions: string[]
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

// ---------- BE-2 笔录会话 ----------
export interface ReporterOut {
  id: string
  case_id: string
  name: string
  id_card?: string | null
  phone?: string | null
  gender?: string | null
  address?: string | null
}

export interface CaseOut {
  id: string
  case_no: string
  case_category: string
  brief: string
  handling_org: string
  report_time: string
  external_source?: string | null
  external_case_id?: string | null
  creator_no: string
  created_at: string
  reporter?: ReporterOut | null
}

export interface SessionCreate {
  case_no: string
  case_category: string
  brief: string
  handling_org?: string | null
  report_time?: string | null
  reporter_name: string
  reporter_id_card?: string | null
  reporter_phone?: string | null
}

export interface SessionListItem {
  id: string
  case_no: string
  case_category: string
  brief: string
  reporter_name?: string | null
  creator_no: string
  creator_name?: string | null
  stage: Stage
  progress: number
  updated_at: string
}

export interface SessionDetail {
  id: string
  stage: Stage
  progress: number
  creator_no: string
  creator_org_id: string
  is_archived: boolean
  stage_snapshot?: Record<string, unknown> | null
  selected_template_ids: string[]
  case_info?: CaseOut | null
  created_at: string
  updated_at: string
}

export interface SessionRestore {
  session_id: string
  stage: Stage
  target_view: 'intake_modal' | 'template_page' | 'workbench' | 'preview_page' | string
  restore_data: Record<string, unknown>
}

export interface QAOut {
  id: string
  session_id: string
  chapter: Chapter
  question: string
  answer?: string | null
  source: QASource
  sort_order: number
  is_answered: boolean
  updated_at: string
}

export interface QAChapterGroup {
  chapter: Chapter
  chapter_label: string
  items: QAOut[]
}

// ---------- BE-4 模板 ----------
export interface TemplateOut {
  id: string
  name: string
  code: string
  category: string
  description?: string | null
  is_general: boolean
  is_enabled: boolean
  sort_order: number
  created_at: string
}

export interface TemplateQuestionOut {
  id: string
  template_id: string
  chapter: Chapter
  question: string
  sort_order: number
  target_elements?: string | null
}

export interface TemplateDetail extends TemplateOut {
  questions: TemplateQuestionOut[]
  signal_words: { id: string; template_id: string; word: string; weight: number }[]
}

export interface TemplateRecommendItem {
  template: TemplateOut
  match_score: number
  match_percent: number
  is_high_confidence: boolean
  hit_signal_words: string[]
  signal_factor: number
  category_factor: number
  semantic_factor: number
  reason: string
}

export interface TemplateRecommendResult {
  recommendations: TemplateRecommendItem[]
  is_degraded: boolean
  degrade_reason?: string | null
  total_templates: number
}

// ---------- BE-5 AI 研判 ----------
export interface SuggestionOut {
  id: string
  session_id: string
  suggestion_type: SuggestionType
  title?: string | null
  content: string
  basis?: Record<string, unknown> | null
  confidence?: number | null
  target_chapter?: string | null
  target_element_code?: string | null
  is_pinned: boolean
  is_adopted: boolean
  sort_order: number
  created_at: string
}

export interface CaseTypeJudgement {
  case_type: string
  confidence: number
  basis: string[]
  hit_signal_words: string[]
}

export interface InvestigationGuide {
  suspect_profile?: string | null
  fund_interception?: string | null
  followup_investigation?: string | null
}

export interface AnalysisResult {
  session_id: string
  fact_features: { feature: string; hit_signal_words: string[]; related_flow?: string | null }[]
  case_type_judgement?: CaseTypeJudgement | null
  investigation_guide?: InvestigationGuide | null
  suggestions: SuggestionOut[]
  is_insufficient_context: boolean
  is_timeout: boolean
}

export interface LLMStatusOut {
  enabled: boolean
  reachable: boolean
  base_url: string
  chat_model: string
  embedding_model: string
  capabilities: {
    semantic_match: boolean
    analysis: boolean
    extraction: boolean
    import_parse: boolean
  }
}

// ---------- BE-6 五流 ----------
export interface FiveFlowElementOut {
  id: string
  session_id: string
  flow_type: FlowType
  element_code: string
  element_name?: string | null
  value?: string | null
  status: ElementStatus
  evidence_snippet?: string | null
  is_core: boolean
  need_manual_confirm: boolean
}

export interface FlowCoverage {
  flow_type: FlowType
  flow_label: string
  coverage: number
  status: ElementStatus
  collected_count: number
  required_count: number
  elements: FiveFlowElementOut[]
  evidence_summary: string[]
  key_gaps: string[]
}

export interface FiveFlowAnalysisResult {
  session_id: string
  flows: FlowCoverage[]
  overall_coverage: number
  has_key_gap: boolean
}

// ---------- BE-6 历史笔录导入 ----------
export interface ParsedQA {
  chapter?: string | null
  question: string
  answer?: string | null
}

export interface ParseResult {
  parsed_qa: ParsedQA[]
  qa_count: number
  five_flow_analysis?: FiveFlowAnalysisResult | null
  missing_flows: string[]
  followup_draft: string[]
  parse_success: boolean
  parse_message: string
}

// ---------- BE-7 材料与文书 ----------
export interface MaterialOut {
  id: string
  session_id: string
  file_name: string
  material_type: MaterialType
  content_type?: string | null
  file_size: number
  file_hash: string
  uploader_no: string
  virus_scan_status: string
  virus_scan_passed: boolean
  created_at: string
}

export interface MaterialListResult {
  items: MaterialOut[]
  total: number
  isolation_notice: string
}

export interface DocumentPreviewItem {
  chapter_label?: string | null
  question: string
  answer: string
}

export interface DocumentPreview {
  session_id: string
  red_header_title: string
  case_no: string
  case_category?: string | null
  inquiry_time?: string | null
  inquiry_place?: string | null
  inquirer?: string | null
  interviewee?: string | null
  qa_paragraphs: DocumentPreviewItem[]
  answered_count: number
  signature_area: Record<string, unknown>
}

// ---------- BE-3 外部系统 ----------
export interface ExternalCaseCandidate {
  external_case_id: string
  source: ExternalSource
  case_no: string
  case_category?: string | null
  brief?: string | null
  victim_name?: string | null
  victim_id_card?: string | null
  victim_phone?: string | null
  handling_org?: string | null
  match_hint?: string | null
}

export interface ExternalSearchResult {
  candidates: ExternalCaseCandidate[]
  total: number
  source: ExternalSource
  is_available: boolean
  message: string
}

export interface ExternalBackfillData {
  case_no?: string | null
  case_category?: string | null
  brief?: string | null
  handling_org?: string | null
  reporter_name?: string | null
  reporter_id_card?: string | null
  reporter_phone?: string | null
  external_source: ExternalSource
  external_case_id: string
}
