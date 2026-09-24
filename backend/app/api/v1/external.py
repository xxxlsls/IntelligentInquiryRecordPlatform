"""
外部系统集成路由（BE-3）

对应需求文档：
- FR-3.2.2 外部系统案件一键同步与字段回填（智研判/智案管只读检索）；
- OOS-1：仅只读检索与映射回填，严禁回写外部系统；
- 2.4.2 外部系统同步审计（检索关键字、命中案件、回填动作）。

接口能力：
1) POST /external/search   按关键字只读检索外部案件，返回候选列表（含降级提示）；
2) GET  /external/backfill 民警单选确认命中案件后，返回字段映射回填数据；
3) POST /sessions/{id}/external-backfill 将回填数据应用到指定笔录草稿。

权限：办案民警可执行外部同步（Permission.EXTERNAL_SYNC）。
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import ExternalSource, Permission
from app.schemas.common import ApiResponse
from app.schemas.external import (
    ExternalBackfillData,
    ExternalSearchRequest,
    ExternalSearchResult,
)
from app.schemas.session import SessionDetail
from app.services.external_service import ExternalSystemService
from app.services.session_service import SessionService

router = APIRouter(prefix="/external", tags=["BE-3 外部系统集成"])

# 外部同步权限依赖（FR-3.2.2：办案民警）
_external_sync_required = Depends(require_permission(Permission.EXTERNAL_SYNC))


@router.post("/search", response_model=ApiResponse[ExternalSearchResult],
             summary="检索外部系统案件", dependencies=[_external_sync_required])
def search_external_cases(
    payload: ExternalSearchRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[ExternalSearchResult]:
    """外部系统案件只读检索（FR-3.2.2 处理逻辑步骤 1~2）。

    输入检索关键字（案件编号/报案人）与来源系统，返回候选案件列表。
    外部系统超时/不可用时降级为空结果并提示手工录入（异常与边界）。
    """
    result = ExternalSystemService().search(payload.keyword, payload.source)
    return ApiResponse.ok(result, message=result.message)


@router.get("/backfill", response_model=ApiResponse[ExternalBackfillData],
            summary="获取字段映射回填数据", dependencies=[_external_sync_required])
def get_backfill_data(
    request: Request,
    current_user: CurrentUser,
    external_case_id: str = Query(..., description="选中的外部案件ID"),
    source: ExternalSource = Query(..., description="外部系统来源"),
) -> ApiResponse[ExternalBackfillData]:
    """民警单选确认命中案件后，执行外部字段 → 本地字段映射（FR-3.2.2 步骤 3~4）。

    返回可直接回填至接报表单的字段集合；映射缺失项留空待补。
    """
    data = ExternalSystemService().get_backfill_data(external_case_id, source)
    return ApiResponse.ok(data, message="已获取回填数据，请确认后写入接报表单")


@router.post("/sessions/{session_id}/apply", response_model=ApiResponse[SessionDetail],
             summary="应用外部回填数据到笔录草稿", dependencies=[_external_sync_required])
def apply_backfill(
    session_id: str,
    payload: ExternalBackfillData,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """将外部映射数据回填到指定笔录草稿（FR-3.2.2 一键同步）。

    回填动作写入外部系统同步审计（2.4.2），越权由服务层校验（DR-4）。
    """
    SessionService(db).apply_external_backfill(
        session_id, payload.model_dump(mode="json"), current_user, request
    )
    # 复用笔录详情构建逻辑，返回最新草稿
    from app.api.v1.sessions import _build_detail

    return ApiResponse.ok(_build_detail(db, session_id), message="外部案件数据已回填")
