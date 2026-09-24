"""
FastAPI 依赖注入：认证、权限校验与数据范围控制

实现需求文档：
- FR-3.1.5 Cookie 会话管理与统一拦截（后端过滤器校验登录态）；
- SE-1/SE-2 会话凭证校验，失效返回 401 触发前端重定向；
- FR-3.1.2 角色权限管理（RBAC 后端接口二次校验，越权返回 403）；
- DR-2/DR-3/DR-4 数据权限与机构隔离（机构路径前缀匹配 + 越权拦截审计）。

提供三类核心依赖：
- get_current_user     解析 JWT 得到当前登录用户（未认证抛 401）
- require_permission   校验用户是否具备某功能权限（越权抛 403 并审计）
- require_roles        校验用户角色是否在允许集合内
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import ROLE_PERMISSIONS, Permission, Role
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.models.user import User
from app.services.audit_service import AuditService

# HTTPBearer：从 Authorization: Bearer <token> 头提取凭证；auto_error=False 便于自定义 401 提示
bearer_scheme = HTTPBearer(auto_error=False)

# 便捷类型别名：数据库会话依赖
DbSession = Annotated[Session, Depends(get_db)]


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
    request: Request,
) -> str | None:
    """从 Authorization 头或 Cookie 中提取会话凭证（FR-3.1.5：请求头/Cookie 中的会话凭证）。

    优先 Authorization Bearer 头，其次读取名为 access_token 的 Cookie，
    以同时支持前后端分离的 Token 与 Cookie 会话机制（SE-1）。
    """
    if credentials and credentials.credentials:
        return credentials.credentials
    # 兼容 Cookie 会话（SE-1：Cookie + Token 会话机制）
    return request.cookies.get("access_token")


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    """解析会话凭证并返回当前登录用户（FR-3.1.5 后端过滤器校验）。

    校验流程：
    1) 提取凭证；缺失 → 401；
    2) 解码校验 JWT；过期/篡改/非法 → 401（SE-2 重定向登录）；
    3) 按 subject（警号）查询用户；不存在 → 401；
    4) 校验账号状态；停用 → 403。

    :raises UnauthorizedError: 凭证缺失/失效（401）
    :raises ForbiddenError: 账号已停用（403）
    """
    token = _extract_token(credentials, request)
    if not token:
        raise UnauthorizedError("未提供会话凭证，请先登录")

    payload = decode_access_token(token)
    if payload is None:
        # 凭证过期/篡改/非法（SE-2：会话失效重定向登录页）
        raise UnauthorizedError("登录状态已失效，请重新登录")

    officer_no = payload.get("sub")
    if not officer_no:
        raise UnauthorizedError("会话凭证无效")

    user = db.execute(select(User).where(User.officer_no == officer_no)).scalar_one_or_none()
    if user is None:
        raise UnauthorizedError("用户不存在或已注销")

    if not user.is_active:
        # 账号停用（FR-3.1.1 异常与边界：停用警员不可登录）
        raise ForbiddenError("账号已停用，请联系管理员")

    # 将请求与用户挂载到 request.state，供后续数据范围校验与审计复用
    request.state.current_user = user
    return user


# 便捷类型别名：当前登录用户依赖
CurrentUser = Annotated[User, Depends(get_current_user)]


def get_permissions(user: User) -> set[Permission]:
    """获取用户的权限项集合（基于 RBAC 角色映射，FR-3.1.2）。"""
    return ROLE_PERMISSIONS.get(user.role_enum, set())


def require_permission(permission: Permission):
    """构造"需要指定功能权限"的依赖（FR-3.1.2 后端接口二次校验）。

    用法：`Depends(require_permission(Permission.RECORD_CREATE))`

    :param permission: 需要的权限项
    :return: FastAPI 依赖函数，校验通过返回当前用户，越权抛 403 并记录审计
    """

    def _dependency(
        request: Request,
        current_user: CurrentUser,
        db: DbSession,
    ) -> User:
        user_perms = get_permissions(current_user)
        if permission not in user_perms:
            # 越权拦截（DR-4：返回 403 并记录审计）
            AuditService(db).log_permission_denied(
                officer_no=current_user.officer_no,
                request=request,
                resource=permission.value,
                reason=f"缺少权限 {permission.value}",
            )
            raise ForbiddenError(f"无权执行该操作（缺少权限：{permission.value}）")
        return current_user

    return _dependency


def require_roles(*roles: Role):
    """构造"需要指定角色之一"的依赖（角色级访问控制）。

    用法：`Depends(require_roles(Role.SYSTEM_ADMIN))`

    :param roles: 允许的角色集合
    :return: FastAPI 依赖函数，角色匹配返回当前用户，否则抛 403 并审计
    """
    allowed = set(roles)

    def _dependency(
        request: Request,
        current_user: CurrentUser,
        db: DbSession,
    ) -> User:
        if current_user.role_enum not in allowed:
            AuditService(db).log_permission_denied(
                officer_no=current_user.officer_no,
                request=request,
                resource="role_check",
                reason=f"角色 {current_user.role} 不在允许集合 {[r.value for r in allowed]}",
            )
            raise ForbiddenError("当前角色无权访问该资源")
        return current_user

    return _dependency


# ============================================================
# 数据权限范围（DR-2 / DR-3 / DR-4）
# ============================================================
class DataScope:
    """数据访问范围封装（机构隔离规则）。

    根据用户角色计算可见的机构路径前缀与警号范围：
    - 办案民警：本机构范围内自己参与/创建的笔录（DR-2）；
    - 反诈研判员：本机构范围内全部笔录（只读，DR-2）；
    - 系统管理员：全量（只读台账）。
    上级机构经授权可向下查看（DR-3，通过 org_path 前缀匹配实现）。
    """

    def __init__(self, user: User):
        self.user = user
        self.role = user.role_enum
        # 机构路径前缀：用于 org_path LIKE 'prefix%' 匹配下辖数据
        self.org_path_prefix: str = user.org.org_path if user.org else ""
        self.org_id: str = user.org_id

    @property
    def is_admin(self) -> bool:
        """是否系统管理员（可见全量）。"""
        return self.role == Role.SYSTEM_ADMIN

    @property
    def is_analyst(self) -> bool:
        """是否反诈研判员（本机构只读全部）。"""
        return self.role == Role.ANTI_FRAUD_ANALYST

    @property
    def is_officer(self) -> bool:
        """是否办案民警（本机构自己创建的笔录）。"""
        return self.role == Role.CASE_OFFICER

    def can_access_org_path(self, target_org_path: str) -> bool:
        """判断当前用户是否可访问目标机构路径的数据（DR-3 逐级授权）。

        管理员可访问全部；其他用户仅可访问 org_path 以自身机构路径为前缀的数据。
        """
        if self.is_admin:
            return True
        if not self.org_path_prefix:
            return False
        return target_org_path.startswith(self.org_path_prefix)


def get_data_scope(current_user: CurrentUser) -> DataScope:
    """FastAPI 依赖：构造当前用户的数据访问范围对象。"""
    return DataScope(current_user)


# 便捷类型别名：数据范围依赖
CurrentScope = Annotated[DataScope, Depends(get_data_scope)]


def get_client_ip(request: Request) -> str | None:
    """获取客户端 IP（供审计记录，8.4 ip 字段）。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.headers.get("X-Real-IP") or (request.client.host if request.client else None)
