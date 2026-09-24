"""
案件与报案人 Schema（DE-2 / DE-3）

对应需求文档：FR-3.2.1 案件接报录入与草稿保存的输入校验规则。
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReporterBase(BaseModel):
    """报案人基础字段（FR-3.2.1 输入项）。"""

    name: str = Field(..., min_length=1, max_length=50, description="报案人姓名（必填）")
    id_card: str | None = Field(default=None, max_length=30, description="报案人证件号（选填，格式校验）")
    phone: str | None = Field(default=None, max_length=20, description="报案人联系电话（选填，手机号校验）")
    gender: str | None = Field(default=None, max_length=10, description="性别")
    address: str | None = Field(default=None, max_length=200, description="住址")

    @field_validator("id_card")
    @classmethod
    def validate_id_card(cls, v: str | None) -> str | None:
        """证件号格式校验：15 或 18 位（末位可为 X），选填但填写则校验。"""
        if v is None or v == "":
            return v
        if not re.fullmatch(r"\d{17}[\dXx]|\d{15}", v.strip()):
            raise ValueError("证件号格式不正确（应为 15 位或 18 位）")
        return v.strip().upper()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        """手机号格式校验：11 位、以 1 开头，选填但填写则校验。"""
        if v is None or v == "":
            return v
        if not re.fullmatch(r"1[3-9]\d{9}", v.strip()):
            raise ValueError("手机号格式不正确（应为 11 位有效手机号）")
        return v.strip()


class ReporterOut(ReporterBase):
    """报案人输出模型（敏感字段脱敏由服务层处理，NFR-S2）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str


class CaseCreate(BaseModel):
    """案件接报录入请求（FR-3.2.1）。

    校验规则：
    - 案件编号（必填，唯一，格式校验）；
    - 案件类别（必填，19 类案由 + 其他）；
    - 简要案情（必填，长文本，≥10 字）；
    - 办案单位（必填，默认当前机构）；
    - 接报时间（默认当前，可调整）。
    """

    case_no: str = Field(..., min_length=1, max_length=50, description="案件编号（必填，唯一）")
    case_category: str = Field(..., min_length=1, max_length=50, description="案件类别")
    brief: str = Field(..., min_length=10, description="简要案情（≥10 字）")
    handling_org: str | None = Field(default=None, max_length=100, description="办案单位（默认当前机构）")
    report_time: datetime | None = Field(default=None, description="接报时间（默认当前）")
    reporter: ReporterBase = Field(..., description="报案人信息")

    @field_validator("case_no")
    @classmethod
    def validate_case_no(cls, v: str) -> str:
        """案件编号格式校验：字母数字与连字符组合，去除首尾空白。"""
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9\-_]{4,50}", v):
            raise ValueError("案件编号格式不正确（4-50 位字母、数字、连字符或下划线）")
        return v

    @field_validator("brief")
    @classmethod
    def strip_brief(cls, v: str) -> str:
        """简要案情去除首尾空白后再校验长度。"""
        return v.strip()


class CaseUpdate(BaseModel):
    """案件信息更新请求（草稿阶段可修改，案件编号不可改）。"""

    case_category: str | None = Field(default=None, max_length=50, description="案件类别")
    brief: str | None = Field(default=None, min_length=10, description="简要案情")
    handling_org: str | None = Field(default=None, max_length=100, description="办案单位")
    report_time: datetime | None = Field(default=None, description="接报时间")
    reporter: ReporterBase | None = Field(default=None, description="报案人信息")


class CaseOut(BaseModel):
    """案件输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    case_no: str
    case_category: str
    brief: str
    handling_org: str
    report_time: datetime
    external_source: str | None = None
    external_case_id: str | None = None
    creator_no: str
    created_at: datetime
    reporter: ReporterOut | None = None
