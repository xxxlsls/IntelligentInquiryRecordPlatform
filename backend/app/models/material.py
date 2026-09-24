"""
辅助材料模型（DE-7：Material）

实现需求文档：
- FR-3.4.4 辅助材料拖拽上传与物理隔离（材料仅作研判输入，严禁拼接进正式问答）；
- 8.4 审计（文件名、类型、大小、哈希）；
- IR-1 物理隔离、IR-5 材料引用（可在五流覆盖表/研判报告中引用，不混入问答正文）；
- NFR-S6 文件安全（病毒扫描与校验）。
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Material(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """辅助材料（DE-7）。

    物理隔离设计（IR-1）：材料独立存储于本表与文件系统，仅通过 session_id 关联会话，
    绝不写入 QAItem 问答正文，保障执法程序合法性（NFR-S1）。
    """

    __tablename__ = "material"

    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_session.id"), nullable=False, index=True, comment="所属会话ID"
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    stored_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="存储文件名（UUID 重命名，避免冲突与路径穿越）"
    )
    material_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="材料类型：call_record/transfer_flow/chat_screenshot/..."
    )
    content_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="MIME 类型"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="文件大小（字节）"
    )
    file_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="文件内容 SHA-256 哈希（校验与审计）"
    )
    storage_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="文件存储相对路径"
    )
    uploader_no: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="上传人警号"
    )
    virus_scan_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", comment="病毒扫描状态：pending/passed/infected"
    )
    virus_scan_passed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="病毒扫描是否通过"
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="软删除标记（材料只增可追溯）"
    )

    session: Mapped["RecordSession"] = relationship("RecordSession")  # noqa: F821
