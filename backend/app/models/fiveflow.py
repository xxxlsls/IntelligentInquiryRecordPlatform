"""
五流要素模型（DE-6：FiveFlowElement + 五流要素定义目录 FlowElementDefinition）

实现需求文档：
- 5.1 五流各要素明细表（人员流 P-01~P-04、通信流 C-01~C-05、网络流 N-01~N-06、
  资金流 F-01~F-08、寄递流 D-01~D-05），以 FlowElementDefinition 目录表持久化；
- 7.2.3 五流要素（element_id、session_id、flow_type、element_code、value、status、evidence_snippet）；
- 5.3 覆盖度计算与状态判定（status 四状态、is_core 核心要素标记）。
"""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import ElementStatus, FlowType
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FlowElementDefinition(Base, UUIDPrimaryKeyMixin):
    """五流要素定义目录（对应 5.1 五流各要素明细表）。

    系统级配置表，定义每个流下"应收集要素"的编号、名称、类型与是否核心要素。
    覆盖度计算的分母 N_required 由此目录结合案由动态确定（5.3）。
    管理员可维护扩展（NFR-U4 可扩展性）。
    """

    __tablename__ = "flow_element_definition"
    __table_args__ = (
        UniqueConstraint("element_code", name="uq_flow_element_code"),
    )

    flow_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="流类型：person/communication/network/fund/delivery"
    )
    element_code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, comment="要素编号（如 P-01、F-04）"
    )
    element_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="要素名称")
    field_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="text", comment="字段类型：text/phone/amount/card_no/url/time/..."
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="要素说明")
    is_core: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否核心要素（核心要素缺失→重点缺口，5.3）"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="流内排序号")

    @property
    def flow_type_enum(self) -> FlowType:
        """返回流类型枚举。"""
        return FlowType(self.flow_type)


class FiveFlowElement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """会话级五流要素抽取结果（DE-6）。

    对应 7.2.3 字段表。每条记录表示某会话下某要素的抽取值与状态。
    由五流要素分析引擎（BE-6）在问答变更后异步抽取写入（ER-1/ER-3）。
    """

    __tablename__ = "five_flow_element"
    __table_args__ = (
        UniqueConstraint("session_id", "element_code", name="uq_session_element"),
    )

    session_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("record_session.id"), nullable=False, index=True, comment="所属会话ID"
    )
    flow_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True, comment="流类型：person/communication/network/fund/delivery"
    )
    element_code: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="要素编号（如 F-04）"
    )
    value: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="抽取值（可空，空=未采集）"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ElementStatus.NEED_SUPPLEMENT.value,
        comment="状态：collected/need_supplement/key_gap/not_involved",
    )
    evidence_snippet: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="证据摘要片段（ER-5，展示于右栏）"
    )
    # 抽取来源问答项ID（ER-3 增量更新时定位变更项）
    source_qa_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="抽取来源问答项ID"
    )
    confidence: Mapped[float | None] = mapped_column(
        nullable=True, comment="抽取置信度（ER-4：低置信度标记待手动确认）"
    )
    need_manual_confirm: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否需手动确认（ER-4 抽取降级）"
    )

    @property
    def status_enum(self) -> ElementStatus:
        """返回状态枚举。"""
        return ElementStatus(self.status)

    @property
    def flow_type_enum(self) -> FlowType:
        """返回流类型枚举。"""
        return FlowType(self.flow_type)

    @property
    def is_collected(self) -> bool:
        """该要素是否已采集（value 非空）。用于覆盖度分子 N_collected 统计。"""
        return bool(self.value and self.value.strip())
