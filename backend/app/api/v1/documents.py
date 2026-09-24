"""
文书预览与导出路由（BE-7）

对应需求文档：
- FR-3.5.1 红头笔录在线实时预览；
- FR-3.5.2 DOCX 标准文书排版生成与下载；
- 8.1 标准询问笔录文书排版规格、8.2 五流覆盖表、8.3 AI 研判报告；
- IR-2 空白过滤、IR-3 红头排版、IR-4 版本指纹。

接口能力：
1) GET  /documents/sessions/{id}/preview  红头笔录在线预览数据；
2) POST /documents/sessions/{id}/export   生成并下载标准排版 DOCX 文书。

权限：预览（DOCUMENT_PREVIEW）；导出（DOCUMENT_EXPORT）。
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import Permission
from app.schemas.common import ApiResponse
from app.schemas.document import DocumentExportRequest, DocumentPreview
from app.services.document_service import DocumentService
from app.services.session_service import SessionService

router = APIRouter(prefix="/documents", tags=["BE-7 文书预览与导出"])

# DOCX 标准 MIME 类型
_DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ============================================================
# 一、红头笔录在线预览（FR-3.5.1）
# ============================================================
@router.get("/sessions/{session_id}/preview", response_model=ApiResponse[DocumentPreview],
            summary="红头笔录在线预览",
            dependencies=[Depends(require_permission(Permission.DOCUMENT_PREVIEW))])
def preview_document(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[DocumentPreview]:
    """构建红头笔录预览数据（FR-3.5.1）。

    读取已作答问答 → 按公安询问笔录排版规范组织 → 过滤未作答空白项（IR-2）。
    """
    # 读取权限校验（DR-4）
    session_service = SessionService(db)
    session = session_service._get_session(session_id)
    session_service._assert_read_access(session, current_user)

    preview = DocumentService(db).build_preview(session_id)
    return ApiResponse.ok(preview)


# ============================================================
# 二、DOCX 文书生成与下载（FR-3.5.2 / 8.1）
# ============================================================
@router.post("/sessions/{session_id}/export", summary="导出 DOCX 笔录文书",
             dependencies=[Depends(require_permission(Permission.DOCUMENT_EXPORT))])
def export_document(
    session_id: str,
    options: DocumentExportRequest,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> Response:
    """生成标准排版 DOCX 文书并下载（FR-3.5.2）。

    排版规格（8.1）：红头标题（红色居中）、案件信息栏、问答正文（"问："加粗黑体、
    "答："正体宋体、1.5 倍行距）、落款签名区；可选附带五流覆盖表（8.2）与 AI 研判报告（8.3）。
    生成版本指纹写入审计（IR-4），并通过响应头 X-Document-Fingerprint 返回给前端。
    """
    # 读取权限校验（DR-4）
    session_service = SessionService(db)
    session = session_service._get_session(session_id)
    session_service._assert_read_access(session, current_user)

    content, file_name, fingerprint = DocumentService(db).generate_docx(
        session_id, options, current_user, request
    )

    # 文件名含中文，需 URL 编码并兼容 RFC 5987（filename*）
    encoded_name = quote(file_name)
    headers = {
        "Content-Disposition": f"attachment; filename=\"record.docx\"; filename*=UTF-8''{encoded_name}",
        # 文书版本指纹（IR-4：导出文书生成版本指纹）
        "X-Document-Fingerprint": fingerprint,
        "X-Document-Name": encoded_name,
    }
    return Response(content=content, media_type=_DOCX_MEDIA_TYPE, headers=headers)
