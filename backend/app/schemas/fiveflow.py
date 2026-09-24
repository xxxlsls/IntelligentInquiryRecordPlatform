"""
五流要素分析 Schema（BE-6 / DE-6）

对应需求文档：
- 5.1 五流各要素明细表；
- 5.3 覆盖度计算与状态判定规则；
- FR-3.4.3 五流覆盖度实时计算与缺口定位；
- FR-3.5.3 历史笔录解析导入；
- 8.2 五流证据要素覆盖表格式。
"""

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ElementStatus, FlowType


class ElementDefinitionOut(BaseModel):
    """五流要素定义（5.1 目录项）。"""

    model_config = ConfigDict(from_attributes=True)

    flow_type: FlowType
    element_code: str
    element_name: str
    field_type: str
    description: str | None = None
    is_core: bool = Field(description="是否核心要素（核心缺失→重点缺口）")
    sort_order: int


class FiveFlowElementOut(BaseModel):
    """会话级五流要素抽取结果（DE-6）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    flow_type: FlowType
    element_code: str
    element_name: str | None = Field(default=None, description="要素名称（关联定义目录）")
    value: str | None = Field(default=None, description="抽取值")
    status: ElementStatus = Field(description="要素状态")
    evidence_snippet: str | None = Field(default=None, description="证据摘要片段（ER-5）")
    is_core: bool = Field(default=False, description="是否核心要素")
    need_manual_confirm: bool = Field(default=False, description="是否需手动确认（ER-4）")


class FlowCoverage(BaseModel):
    """单个流的覆盖度统计（6.4 右栏流卡片）。

    对应 5.3 覆盖度公式：Cov(Flow) = N_collected / N_required × 100%。
    """

    flow_type: FlowType = Field(description="流类型")
    flow_label: str = Field(description="流中文名（如资金流）")
    coverage: float = Field(description="覆盖度百分比 0~100")
    status: ElementStatus = Field(description="流状态：已收集/需补充/重点缺口/不涉及")
    collected_count: int = Field(description="已采集要素数 N_collected")
    required_count: int = Field(description="应收集要素总数 N_required（不涉及项不计入）")
    elements: list[FiveFlowElementOut] = Field(default_factory=list, description="该流全部要素明细")
    evidence_summary: list[str] = Field(default_factory=list, description="已提取证据摘要")
    key_gaps: list[str] = Field(default_factory=list, description="重点缺口清单（缺失的核心要素名称）")


class FiveFlowAnalysisResult(BaseModel):
    """五流覆盖度实时计算结果（FR-3.4.3 右栏聚合）。"""

    session_id: str
    flows: list[FlowCoverage] = Field(default_factory=list, description="五个流的覆盖度卡片")
    overall_coverage: float = Field(default=0.0, description="总体覆盖度（各涉及流的加权平均）")
    has_key_gap: bool = Field(default=False, description="是否存在重点缺口（联动中栏追问）")


class ExtractRequest(BaseModel):
    """要素抽取请求（问答变更后触发，ER-1 异步抽取）。

    注：session_id 以路径参数为准，请求体中的 session_id 仅作兼容保留，可为空。
    """

    session_id: str | None = Field(default=None, description="会话ID（以路径参数为准，可省略）")
    qa_id: str | None = Field(default=None, description="变更的问答项ID（增量抽取，ER-3）")


# ============================================================
# 历史笔录解析导入（FR-3.5.3）
# ============================================================
class ParsedQA(BaseModel):
    """解析出的问答对（FR-3.5.3 处理逻辑步骤 1）。"""

    chapter: str | None = Field(default=None, description="归类的大纲章节")
    question: str = Field(description="问题内容")
    answer: str | None = Field(default=None, description="答案内容")


class TextParseRequest(BaseModel):
    """文本笔录解析请求（粘贴文本导入）。"""

    text: str = Field(..., min_length=1, description="笔录文本内容")


class ParseResult(BaseModel):
    """历史笔录解析结果（6.6 解析结果区）。

    对应 FR-3.5.3 输出：解析问答、五流证据分析报告、缺口追问草稿。
    """

    parsed_qa: list[ParsedQA] = Field(default_factory=list, description="提取的问答对（已章节归类）")
    qa_count: int = Field(default=0, description="解析出的问答对数量")
    five_flow_analysis: FiveFlowAnalysisResult | None = Field(default=None, description="五流证据分析报告")
    missing_flows: list[str] = Field(default_factory=list, description="识别出的缺失流（转继续问询草稿）")
    followup_draft: list[str] = Field(default_factory=list, description="缺口追问草稿问题")
    parse_success: bool = Field(default=True, description="解析是否成功")
    parse_message: str = Field(default="", description="解析提示（失败时提示手工校对）")


class ImportCreateSessionRequest(BaseModel):
    """解析结果转存为新问询会话请求（FR-3.5.3：历史笔录不覆盖现有会话）。"""

    case_no: str = Field(..., min_length=1, max_length=50, description="新案件编号")
    case_category: str = Field(..., min_length=1, max_length=50, description="案件类别")
    brief: str = Field(..., min_length=10, description="简要案情")
    reporter_name: str = Field(..., min_length=1, max_length=50, description="报案人姓名")
    parsed_qa: list[ParsedQA] = Field(default_factory=list, description="解析出的问答对")
