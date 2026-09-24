"""
AI 侦查研判建议 Schema（BE-5 / DE-10）

对应需求文档：
- FR-3.4.2 AI 特征提取与侦查研判建议；
- 5.4 重点缺口追问建议生成规则；
- 8.3 AI 侦查研判指引报告格式；
- 6.4 中栏 AI 侦查研判区。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import SuggestionType


class FactFeature(BaseModel):
    """AI 提取的事实特征（FR-3.4.2 处理逻辑步骤 2）。"""

    feature: str = Field(description="特征描述")
    hit_signal_words: list[str] = Field(default_factory=list, description="命中的特征信号词")
    related_flow: str | None = Field(default=None, description="关联的五流类型")


class CaseTypeJudgement(BaseModel):
    """涉诈类型判定 + 判定依据支撑链（8.3 案由判定结论/判定依据支撑链）。"""

    case_type: str = Field(description="涉诈类型判定结论（如虚假投资理财类）")
    confidence: float = Field(description="判定置信度 0~1")
    basis: list[str] = Field(default_factory=list, description="判定依据支撑链（事实特征）")
    hit_signal_words: list[str] = Field(default_factory=list, description="命中信号词")


class InvestigationGuide(BaseModel):
    """侦查指引建议（8.3 嫌疑人画像/资金链拦截/后续补充侦查指引）。"""

    suspect_profile: str | None = Field(default=None, description="嫌疑人画像推断")
    fund_interception: str | None = Field(default=None, description="下游资金链拦截建议")
    followup_investigation: str | None = Field(default=None, description="后续补充侦查指引")


class SuggestionOut(BaseModel):
    """AI 建议输出模型（中栏卡片）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    suggestion_type: SuggestionType
    title: str | None = None
    content: str
    basis: dict | None = Field(default=None, description="判定依据支撑链")
    confidence: float | None = None
    target_chapter: str | None = Field(default=None, description="推荐问题追加的目标章节")
    target_element_code: str | None = Field(default=None, description="针对的缺失要素编号")
    is_pinned: bool = Field(description="是否置顶（重点缺口追问 GR-2）")
    is_adopted: bool = Field(description="是否已采纳")
    sort_order: int
    created_at: datetime


class AnalysisResult(BaseModel):
    """AI 研判聚合结果（问答变更后触发，FR-3.4.2）。"""

    session_id: str
    fact_features: list[FactFeature] = Field(default_factory=list, description="提取的事实特征")
    case_type_judgement: CaseTypeJudgement | None = Field(default=None, description="涉诈类型判定")
    investigation_guide: InvestigationGuide | None = Field(default=None, description="侦查指引建议")
    suggestions: list[SuggestionOut] = Field(default_factory=list, description="推荐补充问题（重点缺口置顶）")
    is_insufficient_context: bool = Field(default=False, description="上下文是否不足（提示继续录入）")
    is_timeout: bool = Field(default=False, description="模型是否超时（展示上次结果并标注）")


class AdoptSuggestionRequest(BaseModel):
    """一键采纳推荐问题请求（GR-4）。"""

    suggestion_id: str = Field(..., description="被采纳的建议ID")


class AdoptSuggestionResult(BaseModel):
    """采纳结果：推荐问题转为左栏问答项（来源=AI 推荐），去重处理。"""

    success: bool = Field(description="是否采纳成功")
    qa_id: str | None = Field(default=None, description="生成的问答项ID")
    is_duplicate: bool = Field(default=False, description="是否因重复而未新增（去重处理）")
    message: str = Field(default="", description="结果描述")


# ============================================================
# 大模型私有化接入运维（/ai/llm/*）
# ============================================================
class LLMCapabilitiesOut(BaseModel):
    """四项分能力开关状态（可单独降级）。"""

    semantic_match: bool = Field(description="能力一：语义匹配推荐")
    analysis: bool = Field(description="能力二：侦查研判建议生成")
    extraction: bool = Field(description="能力三：五流要素抽取")
    import_parse: bool = Field(description="能力四：历史笔录解析导入")


class LLMStatusOut(BaseModel):
    """LLM 可达性与配置状态（供内网排障）。"""

    enabled: bool = Field(description="总开关是否开启")
    reachable: bool = Field(description="模型端点是否可达（不可达时接口仍 200）")
    base_url: str = Field(description="OpenAI 兼容服务基础地址")
    chat_model: str = Field(description="对话模型名")
    embedding_model: str = Field(description="向量模型名")
    capabilities: LLMCapabilitiesOut = Field(description="分能力开关状态")


class LLMReindexResult(BaseModel):
    """模板语义向量重建结果（能力一支撑）。"""

    indexed: int = Field(description="成功重建向量的模板数")
    failed: int = Field(description="失败数")
    model: str = Field(description="使用的向量模型名")
