"""
模板配置路由（BE-4）

对应需求文档：
- FR-3.3.1 19 类电诈模板库与通用模板管理（元数据、问题集、信号词、启用状态）；
- FR-3.3.3 多模板组合选定与大纲装配（预览装配结果）；
- 6.3 全量模板库检索（降级兜底）。

权限说明（2.2 权限矩阵）：
- 查看模板库：办案民警/反诈研判员/管理员（TEMPLATE_VIEW 或 TEMPLATE_SELECT 场景）；
- 维护模板库（增删改）：仅系统管理员（TEMPLATE_MANAGE）。
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import Chapter, Permission
from app.schemas.common import ApiResponse
from app.schemas.template import (
    TemplateCreate,
    TemplateDetail,
    TemplateOut,
    TemplateUpdate,
)
from app.services.template_service import TemplateService

router = APIRouter(prefix="/templates", tags=["BE-4 模板配置"])

# 模板管理权限依赖（仅系统管理员，FR-3.3.1）
_template_manage_required = Depends(require_permission(Permission.TEMPLATE_MANAGE))


def _to_detail(template) -> TemplateDetail:
    """将模板 ORM 对象转换为详情输出模型（含问题集与信号词）。"""
    detail = TemplateDetail.model_validate(template)
    return detail


# ============================================================
# 查询（供推荐兜底与管理员维护）
# ============================================================
@router.get("", response_model=ApiResponse[list[TemplateOut]], summary="模板列表检索")
def list_templates(
    current_user: CurrentUser,
    db: DbSession,
    keyword: str | None = Query(default=None, description="名称/案由模糊检索（6.3 全量库检索）"),
    only_enabled: bool = Query(default=False, description="仅返回启用模板"),
) -> ApiResponse[list[TemplateOut]]:
    """检索模板库（6.3 全量模板库检索，降级兜底时使用）。"""
    templates = TemplateService(db).list_templates(only_enabled=only_enabled, keyword=keyword)
    return ApiResponse.ok([TemplateOut.model_validate(t) for t in templates])


@router.get("/outline-preview", response_model=ApiResponse[list[dict]], summary="多模板大纲装配预览")
def preview_outline(
    current_user: CurrentUser,
    db: DbSession,
    template_ids: list[str] = Query(..., description="待装配的模板ID集合（≥1）"),
) -> ApiResponse[list[dict]]:
    """多模板组合大纲装配预览（FR-3.3.3）：合并问题集、章节归类去重。

    供前端在正式选定前预览装配结果；正式装配见 POST /sessions/{id}/select-templates。
    """
    outline = TemplateService(db).assemble_outline(template_ids)
    return ApiResponse.ok(outline)


@router.get("/{template_id}", response_model=ApiResponse[TemplateDetail], summary="模板详情")
def get_template(
    template_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[TemplateDetail]:
    """获取模板详情（含标准问题集与特征信号词，供管理员维护）。"""
    template = TemplateService(db).get_template(template_id)
    return ApiResponse.ok(_to_detail(template))


# ============================================================
# 增删改（仅系统管理员，FR-3.3.1）
# ============================================================
@router.post("", response_model=ApiResponse[TemplateDetail], summary="新增模板",
             dependencies=[_template_manage_required])
def create_template(
    data: TemplateCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[TemplateDetail]:
    """新增模板（含问题集与信号词，模板编码唯一性校验）。"""
    template = TemplateService(db).create_template(data, current_user, request)
    return ApiResponse.ok(_to_detail(TemplateService(db).get_template(template.id)), message="模板创建成功")


@router.put("/{template_id}", response_model=ApiResponse[TemplateDetail], summary="更新模板",
            dependencies=[_template_manage_required])
def update_template(
    template_id: str,
    data: TemplateUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[TemplateDetail]:
    """更新模板元数据（编码/案由不可改，启用状态变更实时生效）。"""
    TemplateService(db).update_template(template_id, data, current_user, request)
    return ApiResponse.ok(_to_detail(TemplateService(db).get_template(template_id)), message="模板更新成功")


@router.delete("/{template_id}", response_model=ApiResponse, summary="删除模板",
               dependencies=[_template_manage_required])
def delete_template(
    template_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """删除模板（被进行中会话引用时拒绝，仅可停用，FR-3.3.1 异常与边界）。"""
    TemplateService(db).delete_template(template_id, current_user, request)
    return ApiResponse.ok(message="模板删除成功")


# ============================================================
# 问题集维护（仅系统管理员，FR-3.3.1 标准问题库）
# ============================================================
@router.post("/{template_id}/questions", response_model=ApiResponse[TemplateDetail], summary="新增模板问题",
             dependencies=[_template_manage_required])
def add_question(
    template_id: str,
    chapter: Chapter,
    question: str,
    current_user: CurrentUser,
    db: DbSession,
    sort_order: int = Query(default=0, description="章节内排序号"),
    target_elements: str | None = Query(default=None, description="目标五流要素编号（逗号分隔）"),
) -> ApiResponse[TemplateDetail]:
    """为模板新增标准问题（维护标准问题库）。"""
    service = TemplateService(db)
    service.add_question(template_id, chapter, question, sort_order, target_elements)
    return ApiResponse.ok(_to_detail(service.get_template(template_id)), message="问题已新增")


@router.delete("/{template_id}/questions/{question_id}", response_model=ApiResponse, summary="删除模板问题",
               dependencies=[_template_manage_required])
def delete_question(
    template_id: str,
    question_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """删除模板标准问题。"""
    TemplateService(db).delete_question(question_id)
    return ApiResponse.ok(message="问题已删除")
