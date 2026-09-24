"""
笔录会话与问答模型（DE-1：RecordSession / DE-5：QAItem / DE-10：AiSuggestion）

实现需求文档：
- 7.2.1 笔录会话（四阶段生命周期、机构归属、已选模板、进度）；
- 4.5 四阶段断点续问（stage 字段 + 现场快照）；
- 7.2.2 问答项（章节、来源、排序、作答状态）；
- FR-3.4.2 AI 侦查研判建议（涉诈类型判定、依据、侦查指引、推荐问题）；
- 7.3 实体关系（RecordSession }o--o{ Template 多对多，通过 SessionTemplate 关联）。
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import Chapter, QASource, Stage, SuggestionType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class RecordSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """笔录会话（DE-1）——核心实体，贯穿四阶段生命周期。

    对应 7.2.1 字段表：session_id(PK)、case_id(FK)、stage、creator_org、creator_no、
    selected_templates、progress、created_at/updated_at。
    断点续问（BP-5）依赖 stage 与 stage_snapshot 精准恢复现场。
    """

    __tablename__ = "record_session"

    case_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("case.id"), nullable=False, unique=True, comment="关联案件ID（1:1）"
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default=Stage.INTAKE.value, index=True,
        comment="阶段标识：intake/templates/inquiry/completed",
    )
    # 数据权限归属（DR-1：机构字段不可篡改）
    creator_org_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("org.id"), nullable=False, comment="创建机构ID（不可篡改）"
    )
    creator_org_path: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", index=True, comment="创建机构物化路径（数据权限前缀匹配）"
    )
    creator_no: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True, comment="创建民警警号"
    )
    progress: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="问询进度 0~100"
    )
    # 断点现场快照（JSON 字符串）：保存各阶段恢复所需的上下文（已勾选模板、AI建议状态等）
    stage_snapshot: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="断点现场快照（JSON，用于 BP-5 精准恢复）"
    )
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已归档（completed→归档）"
    )
    # 并发控制（SE-4）：记录当前编辑实例标识，避免多端并发覆盖
    editing_lock_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="编辑锁标识（SE-4 单实例编辑并发控制）"
    )

    # 关系
    case: Mapped["Case"] = relationship("Case", back_populates="session")  # noqa: F821
    qa_items: Mapped[list["QAItem"]] = relationship(
        "QAItem", back_populates="session", cascade="all, delete-orphan",
        order_by="QAItem.sort_order",
    )
    ai_suggestions: Mapped[list["AiSuggestion"]] = relationship(
        "AiSuggestion", back_populates="session", cascade="all, delete-orphan",
    )
    # 多对多：已选模板（通过 SessionTemplate 关联表）
    selected_templates: Mapped[list["Template"]] = relationship(  # noqa: F821
        "Template", secondary="session_template", backref="selected_by_sessions"
    )

    @property
    def stage_enum(self) -> Stage:
        """返回阶段枚举。"""
        return Stage(self.stage)


class SessionTemplate(Base):
    """笔录会话与模板的多对多关联表（DE-1 }o--o{ DE-4）。

    记录会话选定的模板集合（FR-3.3.3 多模板组合选定），保留选定顺序。
    """

    __tablename__ = "session_template"
    __table_args__ = (
        UniqueConstraint("session_id", "template_id", name="uq_session_template"),
    )

    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_session.id"), primary_key=True, comment="会话ID"
    )
    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("template.id"), primary_key=True, comment="模板ID"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="选定顺序")


class QAItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问答项（DE-5）——单个问答对，含章节归类与来源标识。

    对应 7.2.2 字段表：qa_id(PK)、session_id(FK)、chapter、question、answer、source、sort_order。
    answer 为空表示未作答，导出 DOCX 时自动过滤（IR-2 空白过滤）。
    """

    __tablename__ = "qa_item"

    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_session.id"), nullable=False, index=True, comment="所属会话ID"
    )
    chapter: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True, comment="大纲章节：fixed_opening/contact_lure/..."
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="问题内容（非空）")
    answer: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="答案内容（可空，空=未作答）"
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=QASource.TEMPLATE.value,
        comment="来源标识：template/ai_recommend/manual",
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="排序号（非空）")
    # 关联模板问题ID（来源=模板预置时记录，便于追溯）
    template_question_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="来源模板问题ID（模板预置时）"
    )

    session: Mapped["RecordSession"] = relationship("RecordSession", back_populates="qa_items")

    @property
    def is_answered(self) -> bool:
        """是否已作答（answer 非空且非纯空白）。用于 IR-2 空白过滤。"""
        return bool(self.answer and self.answer.strip())

    @property
    def chapter_enum(self) -> Chapter:
        """返回章节枚举。"""
        return Chapter(self.chapter)

    @property
    def source_enum(self) -> QASource:
        """返回来源枚举。"""
        return QASource(self.source)


class AiSuggestion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """AI 侦查研判建议（DE-10）——中栏研判与推荐问题。

    对应 FR-3.4.2：涉诈类型判定、判定依据支撑链、侦查指引、推荐补充问题。
    重点缺口追问（GR-2）通过 is_pinned 置顶展示。
    """

    __tablename__ = "ai_suggestion"

    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_session.id"), nullable=False, index=True, comment="所属会话ID"
    )
    suggestion_type: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="建议类型：case_type_judge/investigation_guide/followup_question/key_gap_question"
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="建议标题（如涉诈类型判定结论）")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="建议正文/推荐问题内容")
    # 判定依据支撑链（JSON 字符串）：命中信号词、事实特征列表
    basis: Mapped[str | None] = mapped_column(Text, nullable=True, comment="判定依据支撑链（JSON）")
    confidence: Mapped[float | None] = mapped_column(
        nullable=True, comment="置信度评分（0~1）"
    )
    target_chapter: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="推荐问题追加的目标章节（一键采纳时用）"
    )
    target_element_code: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="针对的缺失五流要素编号（重点缺口追问用，如 F-04）"
    )
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否置顶（重点缺口追问 GR-2）"
    )
    is_adopted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已被采纳（一键加入问询 GR-4）"
    )
    adopted_qa_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="采纳后生成的问答项ID"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="展示排序号")

    session: Mapped["RecordSession"] = relationship("RecordSession", back_populates="ai_suggestions")

    @property
    def type_enum(self) -> SuggestionType:
        """返回建议类型枚举。"""
        return SuggestionType(self.suggestion_type)
