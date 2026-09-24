"""
模板配置模型（DE-4：Template + 标准问题集 + 特征信号词）

实现需求文档：
- FR-3.3.1 19 类电诈模板库与通用模板管理（元数据、专属问题集、特征信号词、启用状态）；
- FR-3.3.2 AI 智能推荐（信号词权重用于 F_sig 因子计算）；
- FR-3.3.3 多模板组合装配（问题按大纲章节归类）；
- 12.1 19 类案由清单。
"""

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import Chapter
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Template(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问询模板（19 类电诈案由模板 + 通用兜底模板）。

    对应 FR-3.3.1：维护模板元数据、案由类别、大纲章节结构、启用状态。
    停用模板不出现在推荐结果；被进行中会话引用的模板不可删除，仅可停用。
    """

    __tablename__ = "template"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="模板名称")
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True, comment="模板编码（唯一）"
    )
    # 案由类别：与 12.1 案由名称一致，用于 F_cat 类别因子匹配
    category: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, comment="案由类别（对应 12.1 案由名称）"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="模板描述（用于 F_sem 语义相似因子计算）"
    )
    is_general: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否通用兜底模板"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="启用状态（停用不参与推荐）"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="排序号")

    # 关系：标准问题集、特征信号词
    questions: Mapped[list["TemplateQuestion"]] = relationship(
        "TemplateQuestion", back_populates="template", cascade="all, delete-orphan",
        order_by="TemplateQuestion.sort_order",
    )
    signal_words: Mapped[list["TemplateSignalWord"]] = relationship(
        "TemplateSignalWord", back_populates="template", cascade="all, delete-orphan",
    )


class TemplateQuestion(Base, UUIDPrimaryKeyMixin):
    """模板标准问题（预设问题集）。

    对应 FR-3.3.1 标准问题库、FR-3.3.3 大纲装配（按章节归类）。
    """

    __tablename__ = "template_question"

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("template.id"), nullable=False, index=True, comment="所属模板ID"
    )
    chapter: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="所属大纲章节：fixed_opening/contact_lure/..."
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="问题内容")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="章节内排序号")
    # 关联五流要素编号（可选）：标记该问题主要采集哪些五流要素，用于覆盖度引导
    target_elements: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="目标五流要素编号（逗号分隔，如 F-01,F-02）"
    )

    template: Mapped["Template"] = relationship("Template", back_populates="questions")

    @property
    def chapter_enum(self) -> Chapter:
        """返回章节枚举。"""
        return Chapter(self.chapter)


class TemplateSignalWord(Base, UUIDPrimaryKeyMixin):
    """模板特征信号词（用于 AI 推荐的 F_sig 信号词命中因子）。

    对应 FR-3.3.2 匹配度加权算法：F_sig = Σ(w_i·hit_i)/Σw_i，
    其中 w_i 为信号词权重，hit_i 表示案情文本是否命中该信号词。
    """

    __tablename__ = "template_signal_word"

    template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("template.id"), nullable=False, index=True, comment="所属模板ID"
    )
    word: Mapped[str] = mapped_column(String(50), nullable=False, comment="特征信号词")
    weight: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False, comment="信号词权重 w_i（默认 1.0）"
    )

    template: Mapped["Template"] = relationship("Template", back_populates="signal_words")
