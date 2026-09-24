"""
辅助材料文件与存储路由（BE-7）

对应需求文档：
- FR-3.4.4 辅助材料拖拽上传与物理隔离；
- NFR-S6 文件安全（类型白名单、大小限制、病毒扫描、哈希校验）；
- IR-1 物理隔离（材料仅作研判输入，严禁拼接进正式问答正文）；
- 6.4 右栏材料抽屉、2.4.2 上传材料审计。

接口能力：
1) POST   /materials/sessions/{id}/upload  上传辅助材料（multipart/form-data）；
2) GET    /materials/sessions/{id}         列出会话辅助材料（材料抽屉）；
3) GET    /materials/{id}/download         授权下载材料文件；
4) DELETE /materials/{id}                  软删除材料（只增可追溯）。

权限：上传（MATERIAL_UPLOAD，办案民警）；查看/下载（MATERIAL_VIEW）。
"""

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, DbSession, require_permission
from app.core.enums import MaterialType, Permission
from app.schemas.common import ApiResponse
from app.schemas.material import MaterialListResult, MaterialOut
from app.services.material_service import MaterialService
from app.services.session_service import SessionService

router = APIRouter(prefix="/materials", tags=["BE-7 辅助材料存储"])


# ============================================================
# 一、上传（FR-3.4.4 处理逻辑）
# ============================================================
@router.post("/sessions/{session_id}/upload", response_model=ApiResponse[MaterialOut],
             summary="上传辅助材料",
             dependencies=[Depends(require_permission(Permission.MATERIAL_UPLOAD))])
async def upload_material(
    session_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(..., description="材料文件（拖拽上传）"),
    material_type: MaterialType = Form(..., description="材料类型（通话记录/转账流水/聊天截图等）"),
) -> ApiResponse[MaterialOut]:
    """上传辅助材料（FR-3.4.4）。

    处理流程：类型白名单校验 → 大小限制 → 哈希校验 → 病毒扫描 → 存储 → 元数据 + 审计。
    物理隔离（IR-1）：材料仅关联 session_id，绝不写入问答正文。
    """
    # 上传前校验会话写权限（办案民警本人，DR-4）
    session_service = SessionService(db)
    session = session_service._get_session(session_id)
    session_service._assert_write_access(session, current_user, request)

    material = MaterialService(db).upload(session_id, file, material_type, current_user, request)
    return ApiResponse.ok(MaterialOut.model_validate(material), message="材料上传成功")


# ============================================================
# 二、列表与下载（FR-3.4.4 访问授权控制）
# ============================================================
@router.get("/sessions/{session_id}", response_model=ApiResponse[MaterialListResult],
            summary="列出会话辅助材料",
            dependencies=[Depends(require_permission(Permission.MATERIAL_VIEW))])
def list_materials(
    session_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[MaterialListResult]:
    """列出会话辅助材料（材料抽屉），附带物理隔离声明（NFR-S1/IR-1）。"""
    # 读取权限校验（DR-4）
    session_service = SessionService(db)
    session = session_service._get_session(session_id)
    session_service._assert_read_access(session, current_user)

    materials = MaterialService(db).list_materials(session_id)
    items = [MaterialOut.model_validate(m) for m in materials]
    return ApiResponse.ok(MaterialListResult(items=items, total=len(items)))


@router.get("/{material_id}/download", summary="下载辅助材料")
def download_material(
    material_id: str,
    current_user: CurrentUser,
    db: DbSession,
) -> FileResponse:
    """授权下载材料文件（FR-3.4.4 访问授权控制）。

    校验会话读取权限后，以流式响应返回原始文件（保留原文件名）。
    """
    service = MaterialService(db)
    material = service.get_material(material_id)

    # 下载前校验所属会话的读取权限（DR-4）
    session_service = SessionService(db)
    session = session_service._get_session(material.session_id)
    session_service._assert_read_access(session, current_user)

    storage_path = service.get_storage_path(material)
    return FileResponse(
        path=str(storage_path),
        filename=material.file_name,
        media_type=material.content_type or "application/octet-stream",
    )


@router.delete("/{material_id}", response_model=ApiResponse, summary="删除辅助材料",
               dependencies=[Depends(require_permission(Permission.MATERIAL_UPLOAD))])
def delete_material(
    material_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """软删除材料（材料只增可追溯，采用软删除标记，写入审计）。"""
    MaterialService(db).delete_material(material_id, current_user, request)
    return ApiResponse.ok(message="材料已删除")
