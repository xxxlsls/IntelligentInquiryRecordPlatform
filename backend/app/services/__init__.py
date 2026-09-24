"""
services 包 · 业务逻辑层

按 8 大后端模块组织核心业务实现：
- auth_service        BE-1 认证与权限
- org_service         BE-1 组织机构维护
- audit_service       BE-8 审计监控
- session_service     BE-2 笔录生命周期
- external_service    BE-3 外部系统集成
- template_service    BE-4 模板配置服务
- ai_service          BE-5 AI 研判推荐
- fiveflow_service    BE-6 五流要素分析引擎
- material_service    BE-7 文件与存储
- document_service    文书导出（DOCX）
- import_service      BE-6 历史笔录解析导入
"""
