"""
审计日志模型（DE-8：AuditLog）

实现需求文档：
- FR-3.1.4 操作审计日志（案件编号、警员警号、操作类型、时间戳、变更指纹、IP）；
- 2.4.2 敏感操作审计（登录/登出、案件访问、外部同步、问答修改、采纳建议、上传材料、
  文书导出、越权拦截、配置变更）；
- 8.4 操作审计流水记录字段；
- NFR-S5/NFR-C3 审计日志只增不删不改。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """操作审计流水（DE-8）。

    设计原则：只增不删不改（无 updated_at，不提供更新/删除接口）。
    支持按案件编号、警员警号、操作类型、时间范围检索（FR-3.1.4）。
    """

    __tablename__ = "audit_log"

    case_no: Mapped[str | None] = mapped_column(
        String(50), nullable=True, index=True, comment="案件编号（8.4 case_no）"
    )
    session_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True, comment="关联笔录会话ID（便于按会话追溯）"
    )
    officer_no: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True, comment="警员警号（8.4 officer_no）"
    )
    op_type: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True, comment="操作类型（8.4 op_type，见 AuditOpType 枚举）"
    )
    op_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True, comment="操作时间戳（8.4 op_time）"
    )
    op_result: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", comment="操作结果：success/failure/denied"
    )
    change_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="变更指纹（前后值哈希，8.4 change_fingerprint）"
    )
    ip: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="操作来源 IP（8.4 ip）"
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(300), nullable=True, comment="客户端标识"
    )
    # 操作明细（JSON 字符串）：记录检索关键字、命中案件、变更内容、导出指纹等
    detail: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="操作明细（JSON，如变更前后值、检索关键字、文书指纹）"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="操作描述（人类可读摘要）"
    )
