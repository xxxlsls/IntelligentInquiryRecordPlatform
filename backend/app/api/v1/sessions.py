"""
笔录生命周期路由（BE-2）

对应需求文档：
- FR-3.2.1 案件接报录入与草稿保存；
- FR-3.3.3 多模板组合选定与大纲装配；
- FR-3.4.1 结构化大纲章节问答编排；
- 4.5 四阶段断点续问；
- 6.1 笔录台账检索与统计。

权限：办案民警可写，反诈研判员只读，越权由服务层校验（DR-4）。
"""

from fastapi import APIRouter, Depends, Query, Request

from app.core.dependencies import CurrentScope, CurrentUser, DbSession, require_permission
from app.core.enums import Permission, Stage
from app.schemas.common import ApiResponse, PageResult
from app.schemas.session import (
    QACreate,
    QAOut,
    QAUpdate,
    SessionCreate,
    SessionDetail,
    SessionListItem,
    SessionRestore,
    SessionUpdate,
    StageTransitRequest,
    TemplateSelectRequest,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["BE-2 笔录生命周期"])


# ============================================================
# 笔录台账（6.1）
# ============================================================
@router.get("", response_model=ApiResponse[PageResult[SessionListItem]], summary="笔录台账检索")
def list_sessions(
    scope: CurrentScope,
    db: DbSession,
    keyword: str | None = Query(default=None, description="关键字（案件编号/案情/报案人）"),
    stage: Stage | None = Query(default=None, description="状态筛选（阶段）"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> ApiResponse[PageResult[SessionListItem]]:
    """笔录台账复合多条件检索（6.1）。按数据权限范围过滤（DR-2/DR-3）。"""
    items, total = SessionService(db).list_sessions(
        scope, keyword=keyword, stage=stage, page=page, page_size=page_size
    )
    return ApiResponse.ok(PageResult.of(items, total, page, page_size))


@router.get("/statistics", response_model=ApiResponse[dict], summary="笔录统计计数")
def get_statistics(scope: CurrentScope, db: DbSession) -> ApiResponse[dict]:
    """笔录统计（6.1 顶部统计区：总数/各状态数）。"""
    return ApiResponse.ok(SessionService(db).get_statistics(scope))


# ============================================================
# 接报录入与草稿（FR-3.2.1）
# ============================================================
@router.post("", response_model=ApiResponse[SessionDetail], summary="新增笔录（接报录入）",
             dependencies=[Depends(require_permission(Permission.RECORD_CREATE))])
def create_session(
    data: SessionCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """新增笔录会话：创建案件+报案人+会话，阶段=intake（FR-3.2.1）。"""
    session = SessionService(db).create_session(data, current_user, request)
    detail = _build_detail(db, session.id)
    return ApiResponse.ok(detail, message="笔录创建成功，已保存草稿")


@router.get("/{session_id}", response_model=ApiResponse[SessionDetail], summary="笔录会话详情")
def get_session(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """获取笔录会话详情（含案件、模板、阶段快照）。"""
    # 触发访问校验与审计
    SessionService(db).restore(session_id, current_user, None)
    return ApiResponse.ok(_build_detail(db, session_id))


@router.put("/{session_id}", response_model=ApiResponse[SessionDetail], summary="更新草稿",
            dependencies=[Depends(require_permission(Permission.RECORD_CREATE))])
def update_draft(
    session_id: str,
    data: SessionUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """更新接报草稿（intake/templates 阶段可修改案件与报案人信息）。"""
    SessionService(db).update_draft(session_id, data, current_user, request)
    return ApiResponse.ok(_build_detail(db, session_id), message="草稿已保存")


# ============================================================
# 阶段流转与断点续问（4.5 / BP-5）
# ============================================================
@router.post("/{session_id}/stage", response_model=ApiResponse[SessionDetail], summary="阶段流转")
def transit_stage(
    session_id: str,
    data: StageTransitRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """阶段流转（4.5 状态机）。仅允许向前推进或停留当前阶段。"""
    SessionService(db).transit_stage(session_id, data.target_stage, current_user, request)
    return ApiResponse.ok(_build_detail(db, session_id), message=f"已流转至 {data.target_stage.value}")


@router.post("/{session_id}/select-templates", response_model=ApiResponse[SessionDetail],
             summary="选定模板并开始问询",
             dependencies=[Depends(require_permission(Permission.TEMPLATE_SELECT))])
def select_templates(
    session_id: str,
    data: TemplateSelectRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """多模板组合选定与大纲装配，流转 templates→inquiry（FR-3.3.3）。"""
    SessionService(db).select_templates_and_start(session_id, data.template_ids, current_user, request)
    return ApiResponse.ok(_build_detail(db, session_id), message="模板已选定，大纲装配完成，进入问询")


@router.get("/{session_id}/restore", response_model=ApiResponse[SessionRestore], summary="断点续问恢复")
def restore_session(
    session_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionRestore]:
    """断点续问现场恢复（4.5/BP-5）：识别阶段并返回恢复目标界面与内容。"""
    result = SessionService(db).restore(session_id, current_user, request)
    return ApiResponse.ok(SessionRestore(
        session_id=result["session_id"],
        stage=Stage(result["stage"]),
        target_view=result["target_view"],
        restore_data=result["restore_data"],
    ))


@router.post("/{session_id}/snapshot", response_model=ApiResponse, summary="暂存现场快照")
def save_snapshot(
    session_id: str,
    snapshot: dict,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """暂时保存断点现场快照（6.4 顶部"暂时保存"）。"""
    SessionService(db).save_snapshot(session_id, snapshot, current_user)
    return ApiResponse.ok(message="现场已暂存")


@router.post("/{session_id}/archive", response_model=ApiResponse, summary="归档笔录")
def archive_session(
    session_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """归档已完成会话（completed → 归档）。"""
    SessionService(db).archive_session(session_id, current_user, request)
    return ApiResponse.ok(message="笔录已归档")


# ============================================================
# 问答编排（FR-3.4.1）
# ============================================================
@router.get("/{session_id}/qa", response_model=ApiResponse[list[dict]], summary="按章节获取问答")
def get_qa_by_chapter(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[list[dict]]:
    """按大纲章节归类返回问答项（6.4 左栏卡片流）。"""
    return ApiResponse.ok(SessionService(db).get_qa_by_chapter(session_id))


@router.post("/{session_id}/qa", response_model=ApiResponse[QAOut], summary="新增问答",
             dependencies=[Depends(require_permission(Permission.INQUIRY_EDIT))])
def create_qa(
    session_id: str,
    data: QACreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[QAOut]:
    """新增问答项（FR-3.4.1：插入指定章节）。"""
    qa = SessionService(db).create_qa(session_id, data, current_user, request)
    return ApiResponse.ok(QAOut.model_validate(qa), message="问答已新增")


@router.put("/{session_id}/qa/{qa_id}", response_model=ApiResponse[QAOut], summary="编辑问答",
            dependencies=[Depends(require_permission(Permission.INQUIRY_EDIT))])
def update_qa(
    session_id: str,
    qa_id: str,
    data: QAUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[QAOut]:
    """行内编辑问答项（FR-3.4.1：双向绑定实时保存，联动五流抽取）。"""
    qa = SessionService(db).update_qa(session_id, qa_id, data, current_user, request)
    return ApiResponse.ok(QAOut.model_validate(qa), message="问答已保存")


@router.delete("/{session_id}/qa/{qa_id}", response_model=ApiResponse, summary="删除问答",
               dependencies=[Depends(require_permission(Permission.INQUIRY_EDIT))])
def delete_qa(
    session_id: str,
    qa_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """删除问答项（FR-3.4.1：删除需二次确认，前端保障）。"""
    SessionService(db).delete_qa(session_id, qa_id, current_user, request)
    return ApiResponse.ok(message="问答已删除")


# ============================================================
# 内部工具
# ============================================================
def _build_detail(db, session_id: str) -> SessionDetail:
    """构建笔录会话详情响应对象。"""
    from app.schemas.case import CaseOut

    service = SessionService(db)
    session = service._get_session_with_case(session_id)
    case_out = CaseOut.model_validate(session.case) if session.case else None
    snapshot = None
    if session.stage_snapshot:
        import json
        try:
            snapshot = json.loads(session.stage_snapshot)
        except (json.JSONDecodeError, TypeError):
            snapshot = None
    return SessionDetail(
        id=session.id,
        stage=Stage(session.stage),
        progress=session.progress,
        creator_no=session.creator_no,
        creator_org_id=session.creator_org_id,
        is_archived=session.is_archived,
        stage_snapshot=snapshot,
        selected_template_ids=[t.id for t in session.selected_templates],
        case_info=case_out,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )
