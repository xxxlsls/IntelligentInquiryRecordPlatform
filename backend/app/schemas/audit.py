"""
审计日志 Schema（BE-8 / DE-8）

对应需求文档：FR-3.1.4 操作审计日志、8.4 操作审计流水记录字段。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AuditOpType


class AuditLogOut(BaseModel):
    """审计日志输出模型（8.4 字段）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_no: str | None = Field(default=None, description="案件编号")
    session_id: str | None = Field(default=None, description="关联会话ID")
    officer_no: str = Field(description="警员警号")
    op_type: AuditOpType = Field(description="操作类型")
    op_time: datetime = Field(description="操作时间戳")
    op_result: str = Field(description="操作结果：success/failure/denied")
    change_fingerprint: str | None = Field(default=None, description="变更指纹")
    ip: str | None = Field(default=None, description="操作来源 IP")
    description: str | None = Field(default=None, description="操作描述")
    detail: dict | None = Field(default=None, description="操作明细")


class AuditQueryParams(BaseModel):
    """审计检索条件（FR-3.1.4：案件编号/警号/操作类型/时间范围）。"""

    case_no: str | None = Field(default=None, description="案件编号")
    officer_no: str | None = Field(default=None, description="警员警号")
    op_type: AuditOpType | None = Field(default=None, description="操作类型")
    start_time: datetime | None = Field(default=None, description="起始时间")
    end_time: datetime | None = Field(default=None, description="结束时间")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")
