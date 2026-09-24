"""
外部系统集成 Schema（BE-3）

对应需求文档：
- FR-3.2.2 外部系统案件一键同步与字段回填；
- OOS-1：智研判/智案管仅提供只读检索与映射回填，不回写外部系统。
"""

from pydantic import BaseModel, Field

from app.core.enums import ExternalSource


class ExternalSearchRequest(BaseModel):
    """外部系统检索请求（FR-3.2.2 输入项）。

    检索关键字（案件编号/报案人，必填其一）+ 外部系统来源选择。
    """

    keyword: str = Field(..., min_length=1, description="检索关键字（案件编号或报案人）")
    source: ExternalSource = Field(..., description="外部系统来源：zhiyanpan/zhianguan")


class ExternalCaseCandidate(BaseModel):
    """外部系统命中的候选案件（FR-3.2.2 处理逻辑步骤 2）。"""

    external_case_id: str = Field(description="外部系统案件ID")
    source: ExternalSource = Field(description="来源系统")
    case_no: str = Field(description="案件编号")
    case_category: str | None = Field(default=None, description="案件类别")
    brief: str | None = Field(default=None, description="简要案情")
    victim_name: str | None = Field(default=None, description="受害人姓名")
    victim_id_card: str | None = Field(default=None, description="受害人证件号")
    victim_phone: str | None = Field(default=None, description="受害人联系电话")
    handling_org: str | None = Field(default=None, description="办案单位")
    match_hint: str | None = Field(default=None, description="命中提示（供民警单选确认）")


class ExternalSearchResult(BaseModel):
    """外部系统检索结果（候选列表）。"""

    candidates: list[ExternalCaseCandidate] = Field(default_factory=list, description="候选案件列表")
    total: int = Field(default=0, description="命中数量")
    source: ExternalSource = Field(description="检索的外部系统")
    is_available: bool = Field(default=True, description="外部系统是否可用（超时/不可用则降级）")
    message: str = Field(default="", description="结果提示（无命中/多条命中/降级）")


class ExternalBackfillData(BaseModel):
    """字段映射回填数据（FR-3.2.2：外部字段 → 本地字段）。

    民警单选确认命中案件后，返回可直接回填至接报表单的字段集合。
    """

    case_no: str | None = Field(default=None, description="案件编号")
    case_category: str | None = Field(default=None, description="案件类别")
    brief: str | None = Field(default=None, description="简要案情")
    handling_org: str | None = Field(default=None, description="办案单位")
    reporter_name: str | None = Field(default=None, description="报案人姓名（受害人）")
    reporter_id_card: str | None = Field(default=None, description="报案人证件号")
    reporter_phone: str | None = Field(default=None, description="报案人联系电话")
    external_source: ExternalSource = Field(description="数据来源系统")
    external_case_id: str = Field(description="外部案件ID（审计追溯）")


class ExternalBackfillRequest(BaseModel):
    """确认回填请求（民警单选命中案件后触发字段映射）。"""

    source: ExternalSource = Field(..., description="外部系统来源")
    external_case_id: str = Field(..., description="选中的外部案件ID")
