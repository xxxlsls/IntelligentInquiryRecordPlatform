"""
模板配置与 AI 推荐 Schema（BE-4 / BE-5）

对应需求文档：
- FR-3.3.1 模板库管理（元数据、问题集、信号词、启用状态）；
- FR-3.3.2 AI 智能推荐匹配（推荐卡片、匹配度、命中信号词、推荐理由）；
- 6.3 问询模板智能匹配页。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Chapter


# ============================================================
# 模板管理（FR-3.3.1）
# ============================================================
class TemplateQuestionBase(BaseModel):
    """模板标准问题基础字段。"""

    chapter: Chapter = Field(..., description="所属大纲章节")
    question: str = Field(..., min_length=1, description="问题内容")
    sort_order: int = Field(default=0, description="章节内排序号")
    target_elements: str | None = Field(default=None, description="目标五流要素编号（逗号分隔）")


class TemplateQuestionCreate(TemplateQuestionBase):
    """新增模板问题请求。"""


class TemplateQuestionOut(TemplateQuestionBase):
    """模板问题输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str


class SignalWordBase(BaseModel):
    """特征信号词基础字段。"""

    word: str = Field(..., min_length=1, max_length=50, description="特征信号词")
    weight: float = Field(default=1.0, ge=0, le=10, description="信号词权重 w_i")


class SignalWordCreate(SignalWordBase):
    """新增信号词请求。"""


class SignalWordOut(SignalWordBase):
    """信号词输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    template_id: str


class TemplateCreate(BaseModel):
    """新增模板请求（FR-3.3.1）。"""

    name: str = Field(..., min_length=1, max_length=100, description="模板名称")
    code: str = Field(..., min_length=1, max_length=50, description="模板编码（唯一）")
    category: str = Field(..., min_length=1, max_length=50, description="案由类别")
    description: str | None = Field(default=None, description="模板描述（用于语义相似计算）")
    is_general: bool = Field(default=False, description="是否通用兜底模板")
    is_enabled: bool = Field(default=True, description="启用状态")
    sort_order: int = Field(default=0, description="排序号")
    questions: list[TemplateQuestionCreate] = Field(default_factory=list, description="标准问题集")
    signal_words: list[SignalWordCreate] = Field(default_factory=list, description="特征信号词列表")


class TemplateUpdate(BaseModel):
    """更新模板请求（编码/案由不可改）。"""

    name: str | None = Field(default=None, max_length=100, description="模板名称")
    description: str | None = Field(default=None, description="模板描述")
    is_general: bool | None = Field(default=None, description="是否通用模板")
    is_enabled: bool | None = Field(default=None, description="启用状态")
    sort_order: int | None = Field(default=None, description="排序号")


class TemplateOut(BaseModel):
    """模板输出模型（简要，不含问题集）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    code: str
    category: str
    description: str | None = None
    is_general: bool
    is_enabled: bool
    sort_order: int
    created_at: datetime


class TemplateDetail(TemplateOut):
    """模板详情（含问题集与信号词，供管理员维护与大纲装配）。"""

    questions: list[TemplateQuestionOut] = Field(default_factory=list, description="标准问题集")
    signal_words: list[SignalWordOut] = Field(default_factory=list, description="特征信号词")


# ============================================================
# AI 智能推荐（FR-3.3.2）
# ============================================================
class TemplateRecommendRequest(BaseModel):
    """AI 推荐请求。

    输入项（FR-3.3.2）：案情文本（简要案情 + 案件类别）、推荐数量（默认 TOP 3~5）。
    """

    brief: str = Field(..., min_length=1, description="简要案情文本")
    case_category: str | None = Field(default=None, description="案件类别（用于 F_cat 类别因子）")
    top_n: int = Field(default=5, ge=1, le=20, description="推荐数量（默认 TOP 5）")


class TemplateRecommendItem(BaseModel):
    """推荐模板卡片（6.3 右上：匹配度评分、命中信号词、推荐理由）。"""

    template: TemplateOut = Field(description="模板信息")
    match_score: float = Field(description="综合匹配度评分 S(D,T)，0~1")
    match_percent: int = Field(description="匹配度百分比（前端展示）")
    is_high_confidence: bool = Field(description="是否高置信度推荐（S≥阈值）")
    hit_signal_words: list[str] = Field(default_factory=list, description="命中的特征信号词")
    # 三因子明细，便于展开查看推荐理由
    signal_factor: float = Field(default=0.0, description="F_sig 信号词命中因子")
    category_factor: float = Field(default=0.0, description="F_cat 案由类别因子")
    semantic_factor: float = Field(default=0.0, description="F_sem 语义相似因子")
    reason: str = Field(default="", description="推荐理由（人类可读）")


class TemplateRecommendResult(BaseModel):
    """AI 推荐结果（含降级标识）。"""

    recommendations: list[TemplateRecommendItem] = Field(default_factory=list, description="TOP 推荐模板")
    is_degraded: bool = Field(default=False, description="是否降级（无高置信匹配/模型超时→展示全量库）")
    degrade_reason: str | None = Field(default=None, description="降级原因")
    total_templates: int = Field(default=0, description="全量可用模板数（兜底检索用）")
