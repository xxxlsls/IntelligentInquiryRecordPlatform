"""
组织机构维护服务（BE-1）

实现需求文档 FR-3.1.3 组织机构维护：
- 树形机构增删改查；
- 警号唯一性校验；
- 机构删除前校验是否存在下辖机构或在职警员；
- 物化路径 org_path 维护（用于 DR-3 逐级授权数据隔离）。

异常与边界：
- 机构编码/警号重复拒绝；
- 存在下级或在职警员的机构不可删除（提示先迁移）；
- 停用警员不可登录。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AuditOpType, OrgLevel, Role
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.user import Org, User
from app.schemas.auth import OrgCreate, OrgUpdate, UserCreate, UserUpdate
from app.services.audit_service import AuditService


class OrgService:
    """组织机构与警员账号维护服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    # ============================================================
    # 机构维护
    # ============================================================
    def _build_org_path(self, code: str, parent_id: str | None) -> str:
        """构建机构物化路径：父路径 + "/" + 当前编码。

        物化路径用于数据权限前缀匹配（DR-3：上级机构可查看下辖数据）。
        """
        if parent_id:
            parent = self.db.get(Org, parent_id)
            if parent is None:
                raise ValidationError("上级机构不存在")
            return f"{parent.org_path}/{code}"
        return f"/{code}"

    def create_org(self, data: OrgCreate, operator: User, request=None) -> Org:
        """新增机构（FR-3.1.3）。机构编码唯一性校验。"""
        # 编码唯一性校验（异常与边界：机构编码重复拒绝）
        exists = self.db.execute(select(Org).where(Org.code == data.code)).scalar_one_or_none()
        if exists:
            raise ConflictError(f"机构编码 {data.code} 已存在")

        # 层级与上级机构一致性校验
        if data.level != OrgLevel.CITY_BUREAU and not data.parent_id:
            raise ValidationError("非市局级机构必须指定上级机构")

        org = Org(
            name=data.name,
            code=data.code,
            level=data.level.value,
            parent_id=data.parent_id,
            org_path=self._build_org_path(data.code, data.parent_id),
            sort_order=data.sort_order,
        )
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)

        # 配置变更审计（2.4.2：账号机构变更）
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"新增机构 {org.name}({org.code})",
            detail={"action": "create_org", "org_id": org.id, "code": org.code},
        )
        return org

    def update_org(self, org_id: str, data: OrgUpdate, operator: User, request=None) -> Org:
        """更新机构（名称/上级/排序）。编码不可改。"""
        org = self.db.get(Org, org_id)
        if org is None:
            raise NotFoundError("机构不存在")

        if data.name is not None:
            org.name = data.name
        if data.sort_order is not None:
            org.sort_order = data.sort_order
        if data.parent_id is not None:
            # 防止将机构挂载到自身或自身下辖（造成环）
            if data.parent_id == org.id:
                raise ValidationError("上级机构不能是自身")
            new_parent = self.db.get(Org, data.parent_id)
            if new_parent is None:
                raise ValidationError("上级机构不存在")
            if new_parent.org_path.startswith(org.org_path + "/"):
                raise ValidationError("不能将机构挂载到其下辖机构，会造成层级环")
            org.parent_id = data.parent_id
            org.org_path = f"{new_parent.org_path}/{org.code}"

        self.db.commit()
        self.db.refresh(org)
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"更新机构 {org.name}({org.code})",
            detail={"action": "update_org", "org_id": org.id},
        )
        return org

    def delete_org(self, org_id: str, operator: User, request=None) -> None:
        """删除机构（FR-3.1.3 异常与边界：存在下级或在职警员不可删除）。"""
        org = self.db.get(Org, org_id)
        if org is None:
            raise NotFoundError("机构不存在")

        # 校验是否存在下辖机构
        child_count = self.db.execute(
            select(func.count()).select_from(Org).where(Org.parent_id == org_id)
        ).scalar()
        if child_count and child_count > 0:
            raise ConflictError("该机构存在下辖机构，请先迁移或删除下级机构")

        # 校验是否存在在职警员
        user_count = self.db.execute(
            select(func.count()).select_from(User).where(User.org_id == org_id)
        ).scalar()
        if user_count and user_count > 0:
            raise ConflictError("该机构存在在职警员，请先迁移警员归属")

        self.db.delete(org)
        self.db.commit()
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"删除机构 {org.name}({org.code})",
            detail={"action": "delete_org", "org_id": org_id},
        )

    def get_org_tree(self) -> list[Org]:
        """获取全部机构（顶级列表，含 children 关系，供前端构建机构树）。"""
        return list(
            self.db.execute(
                select(Org).where(Org.parent_id.is_(None)).order_by(Org.sort_order)
            ).scalars().all()
        )

    def list_orgs(self) -> list[Org]:
        """获取扁平机构列表。"""
        return list(self.db.execute(select(Org).order_by(Org.org_path)).scalars().all())

    # ============================================================
    # 警员账号维护（FR-3.1.3）
    # ============================================================
    def create_user(self, data: UserCreate, operator: User, request=None) -> User:
        """新增警员账号。警号唯一性校验（异常与边界：警号重复拒绝）。"""
        exists = self.db.execute(select(User).where(User.officer_no == data.officer_no)).scalar_one_or_none()
        if exists:
            raise ConflictError(f"警号 {data.officer_no} 已存在")

        org = self.db.get(Org, data.org_id)
        if org is None:
            raise ValidationError("所属机构不存在")

        user = User(
            officer_no=data.officer_no,
            name=data.name,
            password_hash=hash_password(data.password),
            role=data.role.value,
            org_id=data.org_id,
            phone=data.phone,
            is_active=data.is_active,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"新增警员 {user.name}({user.officer_no})",
            detail={"action": "create_user", "user_id": user.id, "role": user.role},
        )
        return user

    def update_user(self, user_id: str, data: UserUpdate, operator: User, request=None) -> User:
        """更新警员账号（警号不可改）。可重置密码、变更角色/机构/状态。"""
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFoundError("警员不存在")

        if data.name is not None:
            user.name = data.name
        if data.role is not None:
            user.role = data.role.value
        if data.org_id is not None:
            org = self.db.get(Org, data.org_id)
            if org is None:
                raise ValidationError("所属机构不存在")
            user.org_id = data.org_id
        if data.phone is not None:
            user.phone = data.phone
        if data.is_active is not None:
            user.is_active = data.is_active
        if data.password is not None:
            user.password_hash = hash_password(data.password)
            user.failed_login_count = 0
            user.locked_until = None

        self.db.commit()
        self.db.refresh(user)
        self.audit.log(
            op_type=AuditOpType.CONFIG_CHANGE,
            officer_no=operator.officer_no,
            request=request,
            description=f"更新警员 {user.name}({user.officer_no})",
            detail={"action": "update_user", "user_id": user.id},
        )
        return user

    def list_users(self, org_id: str | None = None, role: Role | None = None) -> list[User]:
        """按机构/角色筛选警员列表。"""
        stmt = select(User)
        if org_id:
            stmt = stmt.where(User.org_id == org_id)
        if role:
            stmt = stmt.where(User.role == role.value)
        stmt = stmt.order_by(User.officer_no)
        return list(self.db.execute(stmt).scalars().all())

    def get_user(self, user_id: str) -> User:
        """获取警员详情。"""
        user = self.db.get(User, user_id)
        if user is None:
            raise NotFoundError("警员不存在")
        return user
