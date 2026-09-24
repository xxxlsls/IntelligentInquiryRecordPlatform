"""
五流要素分析路由（BE-6）

对应需求文档：
- FR-3.4.3 五流覆盖度实时计算与缺口定位；
- 5.1 五流各要素明细表（要素定义目录）；
- 5.2 要素抽取规则（ER-1~ER-5）；
- 5.3 覆盖度计算与状态判定规则（四状态）；
- 6.4 右栏五流证据图谱区。

接口能力：
1) GET  /fiveflow/definitions              五流要素定义目录（可按流类型过滤）；
2) GET  /fiveflow/sessions/{id}/coverage   计算会话五流覆盖度与缺口（右栏聚合）；
3) POST /fiveflow/sessions/{id}/extract    手动触发问答要素抽取（增量，ER-3）。

权限：查看五流覆盖度（Permission.FIVEFLOW_VIEW）。
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import FlowType, Permission
from app.models.record import QAItem
from app.schemas.common import ApiResponse
from app.schemas.fiveflow import (
    ElementDefinitionOut,
    ExtractRequest,
    FiveFlowAnalysisResult,
)
from app.services.fiveflow_service import FiveFlowService
from app.services.session_service import SessionService

router = APIRouter(prefix="/fiveflow", tags=["BE-6 五流要素分析"])

# 五流查看权限依赖（FR-3.4.3）
_fiveflow_view_required = Depends(require_permission(Permission.FIVEFLOW_VIEW))


# ============================================================
# 一、要素定义目录（5.1）
# ============================================================
@router.get("/definitions", response_model=ApiResponse[list[ElementDefinitionOut]],
            summary="五流要素定义目录", dependencies=[_fiveflow_view_required])
def list_definitions(
    current_user: CurrentUser,
    db: DbSession,
    flow_type: FlowType | None = Query(default=None, description="按流类型过滤（人员/通信/网络/资金/寄递）"),
) -> ApiResponse[list[ElementDefinitionOut]]:
    """列出五流要素定义目录（5.1 明细表），供前端展示要素清单与核心要素标识。"""
    definitions = FiveFlowService(db).list_definitions(flow_type)
    return ApiResponse.ok([ElementDefinitionOut.model_validate(d) for d in definitions])


# ============================================================
# 二、覆盖度计算与缺口定位（FR-3.4.3 / 5.3）
# ============================================================
@router.get("/sessions/{session_id}/coverage", response_model=ApiResponse[FiveFlowAnalysisResult],
            summary="五流覆盖度实时计算", dependencies=[_fiveflow_view_required])
def compute_coverage(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[FiveFlowAnalysisResult]:
    """计算会话五流覆盖度与状态（5.3 覆盖度公式 + 四状态判定）。

    Cov(Flow)=N_collected/N_required×100%；核心要素缺失标记重点缺口（联动中栏追问）。
    """
    service = SessionService(db)
    session = service._get_session_with_case(session_id)
    service._assert_read_access(session, current_user)

    analysis = FiveFlowService(db).compute_coverage(session)
    return ApiResponse.ok(analysis)


# ============================================================
# 三、要素抽取（ER-1~ER-3，问答变更后触发）
# ============================================================
@router.post("/sessions/{session_id}/extract", response_model=ApiResponse[FiveFlowAnalysisResult],
             summary="触发五流要素抽取", dependencies=[_fiveflow_view_required])
def extract_elements(
    session_id: str,
    payload: ExtractRequest | None,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[FiveFlowAnalysisResult]:
    """手动触发问答五流要素抽取（ER-3 增量更新）。

    - 传入 qa_id 时仅抽取该变更问答（增量）；
    - 未传 qa_id 时全量重抽取该会话问答。
    抽取完成后返回最新覆盖度分析结果。
    """
    service = SessionService(db)
    session = service._get_session_with_case(session_id)
    # 抽取会写入要素数据，需写权限（办案民警本人）
    service._assert_write_access(session, current_user)

    fiveflow = FiveFlowService(db)
    qa_id = payload.qa_id if payload else None

    if qa_id:
        # 增量抽取：仅处理变更的问答项（ER-3）
        qa = db.get(QAItem, qa_id)
        qa_items = [qa] if qa else []
    else:
        # 全量抽取：加载会话全部问答
        qa_items = list(db.execute(
            select(QAItem).where(QAItem.session_id == session_id)
        ).scalars().all())

    fiveflow.extract_from_qa(session_id, qa_items)
    # 同步要素状态字段并返回最新覆盖度
    fiveflow.sync_element_status(session_id)
    analysis = fiveflow.compute_coverage(session)
    return ApiResponse.ok(analysis, message="五流要素抽取完成")
