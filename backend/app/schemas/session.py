"""
笔录会话与问答 Schema（DE-1 / DE-5）

对应需求文档：
- FR-3.2.1 草稿保存与阶段流转；
- FR-3.3.3 多模板组合选定与大纲装配；
- FR-3.4.1 结构化大纲章节问答编排；
- 4.5 四阶段断点续问；
- 6.1 笔录台账检索。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Chapter, QASource, Stage
from app.schemas.case import CaseOut


# ============================================================
# 笔录会话（DE-1）
# ============================================================
class SessionCreate(BaseModel):
    """新增笔录会话请求（FR-3.2.1：新增笔录 → 接报录入）。

    一次性提交案件 + 报案人信息，服务端创建 Case/Reporter/RecordSession 三实体，
    初始阶段为 intake。
    """

    case_no: str = Field(..., min_length=1, max_length=50, description="案件编号（必填，唯一）")
    case_category: str = Field(..., min_length=1, max_length=50, description="案件类别")
    brief: str = Field(..., min_length=10, description="简要案情（≥10 字）")
    handling_org: str | None = Field(default=None, max_length=100, description="办案单位（默认当前机构）")
    report_time: datetime | None = Field(default=None, description="接报时间（默认当前）")
    reporter_name: str = Field(..., min_length=1, max_length=50, description="报案人姓名（必填）")
    reporter_id_card: str | None = Field(default=None, max_length=30, description="报案人证件号（选填）")
    reporter_phone: str | None = Field(default=None, max_length=20, description="报案人联系电话（选填）")


class SessionUpdate(BaseModel):
    """笔录会话草稿更新请求（intake 阶段可修改案件与报案人信息）。"""

    case_category: str | None = Field(default=None, max_length=50, description="案件类别")
    brief: str | None = Field(default=None, min_length=10, description="简要案情")
    handling_org: str | None = Field(default=None, max_length=100, description="办案单位")
    report_time: datetime | None = Field(default=None, description="接报时间")
    reporter_name: str | None = Field(default=None, max_length=50, description="报案人姓名")
    reporter_id_card: str | None = Field(default=None, max_length=30, description="报案人证件号")
    reporter_phone: str | None = Field(default=None, max_length=20, description="报案人联系电话")


class StageTransitRequest(BaseModel):
    """阶段流转请求（4.5 状态机）。

    仅允许向前推进一个阶段或停留当前阶段（Stage.can_transit_to 校验）。
    """

    target_stage: Stage = Field(..., description="目标阶段")


class TemplateSelectRequest(BaseModel):
    """多模板组合选定请求（FR-3.3.3）。

    校验规则：选中模板集合 ≥1 个。确认后装配大纲并流转 templates→inquiry。
    """

    template_ids: list[str] = Field(..., min_length=1, description="选中模板ID集合（≥1 个）")


class SessionListItem(BaseModel):
    """笔录台账列表项（6.1 数据表格区）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="会话ID")
    case_no: str = Field(description="案件编号")
    case_category: str = Field(description="案件类别")
    brief: str = Field(description="简要案情（前端截断+悬浮气泡）")
    reporter_name: str | None = Field(default=None, description="报案人")
    creator_no: str = Field(description="办案民警警号")
    creator_name: str | None = Field(default=None, description="办案民警姓名")
    stage: Stage = Field(description="问询状态（阶段）")
    progress: int = Field(description="问询进度 0~100")
    updated_at: datetime = Field(description="更新时间")


class SessionDetail(BaseModel):
    """笔录会话详情（含案件、模板、阶段快照，用于断点恢复 BP-5）。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    stage: Stage
    progress: int
    creator_no: str
    creator_org_id: str
    is_archived: bool
    stage_snapshot: dict | None = Field(default=None, description="断点现场快照")
    selected_template_ids: list[str] = Field(default_factory=list, description="已选模板ID")
    case_info: CaseOut | None = Field(default=None, description="案件与报案人信息")
    created_at: datetime
    updated_at: datetime


class SessionRestore(BaseModel):
    """断点续问恢复响应（4.5：识别阶段 + 恢复目标界面 + 恢复内容）。"""

    session_id: str = Field(description="会话ID")
    stage: Stage = Field(description="当前阶段（决定恢复目标界面）")
    target_view: str = Field(description="恢复目标界面标识：intake_modal/template_page/workbench/preview_page")
    restore_data: dict = Field(default_factory=dict, description="恢复内容（表单/模板/问答/五流/材料/AI建议）")


# ============================================================
# 问答项（DE-5）
# ============================================================
class QACreate(BaseModel):
    """新增问答项请求（FR-3.4.1：新增问答插入指定章节）。"""

    chapter: Chapter = Field(..., description="所属章节")
    question: str = Field(..., min_length=1, description="问题文本（必填）")
    answer: str | None = Field(default=None, description="答案文本（可空，空为未作答）")
    source: QASource = Field(default=QASource.MANUAL, description="来源标识")
    sort_order: int | None = Field(default=None, description="排序号（空则追加到章节末尾）")


class QAUpdate(BaseModel):
    """问答项行内编辑请求（FR-3.4.1：问答双向绑定实时保存）。"""

    question: str | None = Field(default=None, min_length=1, description="问题文本")
    answer: str | None = Field(default=None, description="答案文本")
    chapter: Chapter | None = Field(default=None, description="所属章节")
    sort_order: int | None = Field(default=None, description="排序号")


class QAOut(BaseModel):
    """问答项输出模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    chapter: Chapter
    question: str
    answer: str | None = None
    source: QASource
    sort_order: int
    is_answered: bool = Field(description="是否已作答")
    updated_at: datetime


class QAChapterGroup(BaseModel):
    """按章节归类的问答分组（6.4 左栏卡片流）。"""

    chapter: Chapter = Field(description="章节")
    chapter_label: str = Field(description="章节中文名")
    items: list[QAOut] = Field(default_factory=list, description="该章节问答项")


class WorkbenchData(BaseModel):
    """三栏工作台聚合数据（6.4：左栏问答 + 中栏 AI + 右栏五流）。"""

    session_id: str
    stage: Stage
    progress: int
    qa_chapters: list[QAChapterGroup] = Field(default_factory=list, description="左栏：按章节归类的问答")
    case_info: CaseOut | None = Field(default=None, description="案件基础信息")
