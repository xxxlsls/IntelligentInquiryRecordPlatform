"""
文件与存储服务（BE-7）

实现需求文档：
- FR-3.4.4 辅助材料拖拽上传与物理隔离；
- NFR-S6 文件安全（病毒扫描与校验）；
- IR-1 物理隔离（材料仅作研判输入，严禁拼接进正式问答）；
- 8.4 审计（文件名、类型、大小、哈希）。

处理逻辑：上传文件 → 病毒扫描 → 文件校验（哈希）→ 存储 → 生成材料列表元数据。
物理隔离保障：材料独立存储于 Material 表与文件系统，绝不写入 QAItem 问答正文。
"""

import os
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ALLOWED_FILE_EXTENSIONS, AuditOpType, MaterialType
from app.core.exceptions import ValidationError
from app.core.security import compute_file_hash
from app.models.material import Material
from app.models.record import RecordSession
from app.models.user import User
from app.services.audit_service import AuditService


class MaterialService:
    """辅助材料文件与存储服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)
        # 确保上传目录存在
        self.upload_root = Path(settings.UPLOAD_DIR)
        self.upload_root.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 上传（FR-3.4.4 处理逻辑）
    # ============================================================
    def upload(
        self,
        session_id: str,
        file: UploadFile,
        material_type: MaterialType,
        user: User,
        request=None,
    ) -> Material:
        """上传辅助材料。

        步骤：
        1) 校验文件类型白名单与大小限制；
        2) 读取内容并计算哈希（文件校验）；
        3) 病毒扫描（演示为模拟扫描）；
        4) 存储文件（UUID 重命名，防路径穿越）；
        5) 生成材料元数据 + 写入审计。

        物理隔离（IR-1）：材料仅关联 session_id，不写入问答正文。

        :raises ValidationError: 类型非法/超限/病毒扫描未通过
        """
        # 校验会话存在
        session = self.db.get(RecordSession, session_id)
        if session is None:
            raise ValidationError("笔录会话不存在")

        file_name = file.filename or "unnamed"
        ext = os.path.splitext(file_name)[1].lower()

        # 1) 类型白名单校验（FR-3.4.4：类型白名单，可配）
        if ext not in ALLOWED_FILE_EXTENSIONS:
            raise ValidationError(f"不支持的文件类型 {ext}，允许类型：{', '.join(sorted(ALLOWED_FILE_EXTENSIONS))}")

        # 读取内容
        content = file.file.read()
        size = len(content)

        # 大小限制校验（默认 ≤50MB/个，可配）
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if size > max_bytes:
            raise ValidationError(f"文件大小 {size // (1024 * 1024)}MB 超过上限 {settings.MAX_FILE_SIZE_MB}MB")
        if size == 0:
            raise ValidationError("文件内容为空")

        # 2) 文件校验（哈希）
        file_hash = compute_file_hash(content)

        # 3) 病毒扫描（NFR-S6，演示为模拟扫描）
        scan_passed, scan_status = self._virus_scan(content, file_name)
        if not scan_passed:
            # 病毒/非法文件拒绝（FR-3.4.4 异常与边界）
            self.audit.log(
                op_type=AuditOpType.MATERIAL_UPLOAD,
                officer_no=user.officer_no,
                session_id=session_id,
                case_no=session.case.case_no if session.case else None,
                request=request,
                op_result="failure",
                description=f"材料病毒扫描未通过，已拒绝：{file_name}",
                detail={"file_name": file_name, "file_hash": file_hash},
            )
            raise ValidationError("文件未通过安全扫描，已拒绝上传")

        # 4) 存储文件（UUID 重命名，避免冲突与路径穿越）
        stored_name = f"{uuid.uuid4().hex}{ext}"
        # 按会话分目录存储，便于管理与清理
        session_dir = self.upload_root / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        storage_path = session_dir / stored_name
        with open(storage_path, "wb") as f:
            f.write(content)

        # 5) 生成材料元数据
        material = Material(
            session_id=session_id,
            file_name=file_name,
            stored_name=stored_name,
            material_type=material_type.value,
            content_type=file.content_type,
            file_size=size,
            file_hash=file_hash,
            storage_path=str(storage_path),
            uploader_no=user.officer_no,
            virus_scan_status=scan_status,
            virus_scan_passed=True,
        )
        self.db.add(material)
        self.db.commit()
        self.db.refresh(material)

        # 上传材料审计（2.4.2：文件名、类型、大小、哈希）
        self.audit.log(
            op_type=AuditOpType.MATERIAL_UPLOAD,
            officer_no=user.officer_no,
            session_id=session_id,
            case_no=session.case.case_no if session.case else None,
            request=request,
            description=f"上传辅助材料：{file_name}",
            detail={
                "file_name": file_name, "material_type": material_type.value,
                "file_size": size, "file_hash": file_hash,
            },
            change_fingerprint=file_hash,
        )
        return material

    def _virus_scan(self, content: bytes, file_name: str) -> tuple[bool, str]:
        """病毒扫描（NFR-S6）。

        演示实现：模拟扫描逻辑（检测 EICAR 测试病毒特征串）。
        生产环境应替换为真实杀毒引擎（如 ClamAV）调用。

        :return: (是否通过, 扫描状态)
        """
        if not settings.ENABLE_VIRUS_SCAN:
            return True, "skipped"
        # EICAR 标准测试病毒特征串（用于验证扫描拦截能力）
        eicar_signature = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR"
        if eicar_signature in content:
            return False, "infected"
        return True, "passed"

    # ============================================================
    # 查询与下载授权（FR-3.4.4 访问授权控制）
    # ============================================================
    def list_materials(self, session_id: str) -> list[Material]:
        """列出会话的辅助材料（材料抽屉列表）。"""
        return list(self.db.execute(
            select(Material)
            .where(Material.session_id == session_id, Material.is_deleted.is_(False))
            .order_by(Material.created_at.desc())
        ).scalars().all())

    def get_material(self, material_id: str) -> Material:
        """获取单个材料（用于授权下载）。"""
        material = self.db.get(Material, material_id)
        if material is None or material.is_deleted:
            raise ValidationError("材料不存在")
        return material

    def get_storage_path(self, material: Material) -> Path:
        """获取材料文件存储路径。"""
        return Path(material.storage_path)

    def delete_material(self, material_id: str, user: User, request=None) -> None:
        """软删除材料（材料只增可追溯，采用软删除标记）。"""
        material = self.get_material(material_id)
        material.is_deleted = True
        self.db.commit()
        self.audit.log(
            op_type=AuditOpType.MATERIAL_UPLOAD,
            officer_no=user.officer_no,
            session_id=material.session_id,
            request=request,
            description=f"删除辅助材料：{material.file_name}",
            detail={"action": "delete", "material_id": material_id},
        )
