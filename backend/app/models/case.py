"""
案件与报案人模型（DE-2：Case / DE-3：Reporter）

实现需求文档：
- FR-3.2.1 案件接报录入（案件编号唯一、案件类别、简要案情、办案单位、接报时间）；
- FR-3.2.2 外部系统字段回填（记录外部来源与外部案件ID，便于审计追溯）；
- 7.3 实体关系（Case ||--|| RecordSession，Case ||--|| Reporter）；
- NFR-S2 数据脱敏（报案人证件号/电话脱敏展示）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Case(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """案件基本信息（DE-2）。

    一条案件对应一条笔录会话（1:1），承载接报录入与外部同步回填的主数据。
    """

    __tablename__ = "case"

    case_no: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True, comment="案件编号（必填，唯一，格式校验）"
    )
    case_category: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="案件类别（19 类案由名称或其他）"
    )
    brief: Mapped[str] = mapped_column(
        Text, nullable=False, comment="简要案情（必填，长文本，≥10 字）"
    )
    handling_org: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="办案单位（默认当前机构）"
    )
    handling_org_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="办案单位机构编码"
    )
    report_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="接报时间（默认当前，可调整）"
    )
    # 数据权限归属：绑定创建民警所属机构，机构字段不可篡改（DR-1）
    owner_org_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("org.id"), nullable=False, comment="归属机构ID（DR-1，不可篡改）"
    )
    owner_org_path: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", index=True, comment="归属机构物化路径（数据权限前缀匹配）"
    )
    creator_no: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="创建民警警号"
    )

    # ---------- 外部系统同步来源（FR-3.2.2 / OOS-1 只读，不回写） ----------
    external_source: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="外部系统来源：zhiyanpan/zhianguan（空表示手工录入）"
    )
    external_case_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="外部系统案件ID（用于同步审计追溯）"
    )

    # 关系：报案人（1:1）、笔录会话（1:1）
    reporter: Mapped["Reporter"] = relationship(
        "Reporter", back_populates="case", uselist=False, cascade="all, delete-orphan"
    )
    session: Mapped["RecordSession"] = relationship(  # noqa: F821
        "RecordSession", back_populates="case", uselist=False, cascade="all, delete-orphan"
    )


class Reporter(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """报案人/受害人信息（DE-3）。

    对应 FR-3.2.1 输入项：报案人姓名（必填）、证件号（选填，格式校验）、联系电话（选填，手机号校验）。
    敏感字段展示时经 mask_sensitive 脱敏（NFR-S2）。
    """

    __tablename__ = "reporter"

    case_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("case.id"), nullable=False, unique=True, comment="关联案件ID（1:1）"
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="报案人姓名（必填）")
    id_card: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="报案人证件号（选填，格式校验）"
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="报案人联系电话（选填，手机号校验）"
    )
    gender: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="性别")
    address: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="住址")

    # 关系
    case: Mapped["Case"] = relationship("Case", back_populates="reporter")
