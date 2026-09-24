"""
用户与组织机构模型（DE-9：User / Org）

实现需求文档：
- 2.3.1 组织机构模型（市局→分局→所队三级）；
- FR-3.1.3 组织机构维护（机构树、警员归属、警号唯一性）；
- FR-3.1.1 用户认证（密码哈希、账号状态、登录失败锁定）；
- 2.3.2 数据授权规则（机构编码前缀实现逐级可见范围）。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import OrgLevel, Role
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Org(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """组织机构（市局/分局/所队）。

    采用邻接表（parent_id 自引用）+ 物化路径（org_path）双重结构：
    - parent_id 便于树形增删改查（FR-3.1.3）；
    - org_path（形如 "/市局编码/分局编码/所队编码"）便于数据权限前缀匹配（DR-3 逐级授权），
      上级机构可查看 org_path 以其自身路径为前缀的所有下辖数据。
    """

    __tablename__ = "org"

    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="机构名称")
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True, comment="机构编码（唯一）"
    )
    level: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="机构层级：city_bureau/sub_bureau/station"
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("org.id"), nullable=True, comment="上级机构ID（顶级为空）"
    )
    # 物化路径：从根到当前节点的编码链，用于数据权限前缀匹配
    org_path: Mapped[str] = mapped_column(
        String(500), nullable=False, default="", index=True, comment="机构物化路径（编码链）"
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, comment="同级排序号")

    # 自引用关系：上级机构与下级机构列表
    parent: Mapped["Org | None"] = relationship("Org", remote_side="Org.id", back_populates="children")
    children: Mapped[list["Org"]] = relationship("Org", back_populates="parent", cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship("User", back_populates="org")

    @property
    def level_enum(self) -> OrgLevel:
        """返回机构层级枚举。"""
        return OrgLevel(self.level)

    def is_ancestor_of(self, other_path: str) -> bool:
        """判断本机构是否为给定 org_path 的祖先（含自身）。

        用于 DR-3 逐级授权：上级机构可查看路径前缀匹配的下辖数据。
        """
        return other_path.startswith(self.org_path)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """警员账号（办案民警/反诈研判员/系统管理员）。

    对应 FR-3.1.1（认证）、FR-3.1.3（警号唯一、机构归属、角色、状态）、
    FR-3.1.1 异常与边界（连续失败锁定）。
    """

    __tablename__ = "user"
    __table_args__ = (
        UniqueConstraint("officer_no", name="uq_user_officer_no"),
    )

    officer_no: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True, comment="警号（唯一，登录账号）"
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="警员姓名")
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="密码加盐哈希")
    role: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="角色：case_officer/analyst/admin"
    )
    org_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("org.id"), nullable=False, comment="所属机构ID"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="账号状态（停用不可登录）"
    )
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="联系电话")

    # ---------- 登录失败锁定相关字段（FR-3.1.1） ----------
    failed_login_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="连续登录失败次数"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="锁定截止时间（超过则自动解锁）"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近登录时间"
    )

    # 关系
    org: Mapped["Org"] = relationship("Org", back_populates="users")

    @property
    def role_enum(self) -> Role:
        """返回角色枚举。"""
        return Role(self.role)

    @property
    def is_locked(self) -> bool:
        """判断账号当前是否处于锁定状态（FR-3.1.1：默认 5 次锁定 15 分钟）。"""
        if self.locked_until is None:
            return False
        return datetime.now() < self.locked_until

    @property
    def org_path(self) -> str:
        """返回所属机构物化路径，供数据权限范围计算使用。"""
        return self.org.org_path if self.org else ""
