"""
API 路由汇总（v1）

聚合八大后端模块的全部子路由，统一挂载到 /api/v1 前缀下。
子路由与需求文档 3.7 后端模块划分对应关系：
- auth       BE-1 认证与权限（登录/JWT/会话）
- org        BE-1 组织机构与警员维护
- sessions   BE-2 笔录生命周期（接报/阶段流转/断点续问/问答编排/台账）
- external   BE-3 外部系统集成（智研判/智案管只读检索回填）
- templates  BE-4 模板配置（19 类案由模板库/大纲装配）
- ai         BE-5 AI 研判推荐（模板匹配/侦查研判/采纳）
- fiveflow   BE-6 五流要素分析（定义目录/覆盖度/抽取）
- imports    BE-6 扩展 历史笔录解析导入
- materials  BE-7 辅助材料存储（上传/下载/物理隔离）
- documents  BE-7 文书预览与 DOCX 导出
- audit      BE-8 操作审计检索
"""

from fastapi import APIRouter

from app.api.v1 import (
    ai,
    audit,
    auth,
    documents,
    external,
    fiveflow,
    imports,
    materials,
    org,
    sessions,
    templates,
)

# v1 总路由
api_router = APIRouter()

# 按模块顺序注册子路由（各子路由自带 prefix 与 tags）
api_router.include_router(auth.router)
api_router.include_router(org.router)
api_router.include_router(sessions.router)
api_router.include_router(external.router)
api_router.include_router(templates.router)
api_router.include_router(ai.router)
api_router.include_router(fiveflow.router)
api_router.include_router(imports.router)
api_router.include_router(materials.router)
api_router.include_router(documents.router)
api_router.include_router(audit.router)
