"""
历史笔录解析导入路由（FR-3.5.3）

对应需求文档：
- FR-3.5.3 历史文本/文档笔录解析导入与会话重建；
- 6.6 历史笔录导入页（解析结果区 + 五流分析 + 缺口追问草稿）；
- 处理逻辑：解析问答 → 大纲章节归类 → 五流抽取 → 识别缺失流转继续问询草稿 → 重建新会话。

异常与边界：解析失败提示手工校对；非标准格式降级为纯文本导入；历史笔录不覆盖现有会话。

接口能力：
1) POST /imports/parse-text   解析粘贴的笔录文本（返回问答对 + 五流缺口 + 追问草稿）；
2) POST /imports/parse-docx   解析上传的 Word 笔录文档；
3) POST /imports/rebuild      将解析结果转存为新的问询会话（不覆盖现有会话）。

权限：导入历史笔录（Permission.RECORD_IMPORT，办案民警）。
"""

from fastapi import APIRouter, Depends, File, Request, UploadFile

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import AuditOpType, Permission
from app.core.exceptions import ValidationError
from app.schemas.common import ApiResponse
from app.schemas.fiveflow import ImportCreateSessionRequest, ParseResult, TextParseRequest
from app.schemas.session import SessionCreate, SessionDetail
from app.services.audit_service import AuditService
from app.services.import_service import ImportService
from app.services.session_service import SessionService

router = APIRouter(prefix="/imports", tags=["BE-6 历史笔录解析导入"])

_import_required = Depends(require_permission(Permission.RECORD_IMPORT))


def _enrich_parse_result(db, result: ParseResult) -> ParseResult:
    """补充五流缺口分析与继续问询草稿（FR-3.5.3 处理逻辑步骤 3~4）。"""
    analysis = ImportService(db).analyze_parsed_qa(result.parsed_qa)
    result.missing_flows = analysis["missing_flows"]
    result.followup_draft = analysis["followup_draft"]
    return result


# ============================================================
# 一、文本/文档解析（FR-3.5.3 处理逻辑步骤 1~4）
# ============================================================
@router.post("/parse-text", response_model=ApiResponse[ParseResult],
             summary="解析历史笔录文本", dependencies=[_import_required])
def parse_text(
    payload: TextParseRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[ParseResult]:
    """解析粘贴的笔录文本（FR-3.5.3）。

    识别"问：/答："结构提取问答对并章节归类；非标准格式降级为纯文本导入并提示手工校对。
    解析后补充五流缺口识别与继续问询草稿。
    """
    result = ImportService(db).parse_text(payload.text)
    result = _enrich_parse_result(db, result)
    return ApiResponse.ok(result, message=result.parse_message)


@router.post("/parse-docx", response_model=ApiResponse[ParseResult],
             summary="解析历史笔录 Word 文档", dependencies=[_import_required])
async def parse_docx(
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(..., description="历史笔录 Word 文档（.docx）"),
) -> ApiResponse[ParseResult]:
    """解析上传的 Word 笔录文档（FR-3.5.3：上传已有笔录文件）。

    使用 python-docx 提取段落文本后复用文本解析逻辑；解析失败提示手工校对。
    """
    if not (file.filename or "").lower().endswith((".docx", ".doc")):
        raise ValidationError("仅支持 Word 文档（.docx/.doc）")
    content = await file.read()
    result = ImportService(db).parse_docx(content)
    result = _enrich_parse_result(db, result)
    return ApiResponse.ok(result, message=result.parse_message)


# ============================================================
# 二、会话重建（FR-3.5.3 处理逻辑步骤 5）
# ============================================================
@router.post("/rebuild", response_model=ApiResponse[SessionDetail],
             summary="解析结果转存为新问询会话", dependencies=[_import_required])
def rebuild_session(
    payload: ImportCreateSessionRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[SessionDetail]:
    """将解析结果转存为新问询会话（FR-3.5.3：历史笔录不覆盖现有会话）。

    处理流程：
    1) 以导入的案件信息创建新会话（阶段=intake）；
    2) 重新识别缺口生成继续问询草稿；
    3) 写入解析问答 + 缺口追问草稿，并对已作答问答执行五流抽取；
    4) 写入历史笔录导入审计（2.4.2）。
    """
    session_service = SessionService(db)
    # 1) 创建新会话（复用接报录入逻辑，历史笔录独立成新会话，不覆盖现有）
    create_data = SessionCreate(
        case_no=payload.case_no,
        case_category=payload.case_category,
        brief=payload.brief,
        reporter_name=payload.reporter_name,
    )
    session = session_service.create_session(create_data, current_user, request)

    # 2) 重新识别缺口生成追问草稿
    analysis = ImportService(db).analyze_parsed_qa(payload.parsed_qa)
    followup_draft = analysis["followup_draft"]

    # 3) 重建会话（写入问答 + 缺口草稿 + 五流抽取）
    ImportService(db).rebuild_session(session, payload.parsed_qa, followup_draft)

    # 4) 历史笔录导入审计
    AuditService(db).log(
        op_type=AuditOpType.RECORD_IMPORT,
        officer_no=current_user.officer_no,
        case_no=payload.case_no,
        session_id=session.id,
        request=request,
        description=f"导入历史笔录：解析 {len(payload.parsed_qa)} 组问答，缺口追问 {len(followup_draft)} 条",
        detail={"qa_count": len(payload.parsed_qa), "missing_flows": analysis["missing_flows"]},
    )

    from app.api.v1.sessions import _build_detail

    return ApiResponse.ok(_build_detail(db, session.id), message="历史笔录已导入并重建为新会话")
