"""
认证与权限服务（BE-1）

实现需求文档 FR-3.1.1 用户认证登录：
处理逻辑：
1) 校验账号存在且状态正常；
2) 校验密码（加盐哈希比对）；
3) 加载角色与机构权限；
4) 签发会话凭证；
5) 写入登录审计。

异常与边界：
- 账号不存在/密码错误统一提示"账号或密码错误"（防枚举）；
- 账号停用；
- 连续失败锁定（默认 5 次锁定 15 分钟）；
- 会话并发限制。
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import ROLE_PERMISSIONS, AuditOpType
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.services.audit_service import AuditService


class AuthService:
    """认证服务：负责登录校验、失败锁定、令牌签发与登录审计。"""

    def __init__(self, db: Session):
        self.db = db
        self.audit = AuditService(db)

    def _get_user_by_no(self, officer_no: str) -> User | None:
        """按警号查询用户。"""
        return self.db.execute(
            select(User).where(User.officer_no == officer_no)
        ).scalar_one_or_none()

    def authenticate(self, officer_no: str, password: str, request=None) -> tuple[User, str]:
        """执行登录认证（FR-3.1.1 处理逻辑）。

        :param officer_no: 警号（登录账号）
        :param password: 明文密码
        :param request: 当前请求（用于审计提取 IP）
        :return: (用户对象, JWT 令牌)
        :raises UnauthorizedError: 账号或密码错误（统一提示，防枚举）
        :raises ForbiddenError: 账号停用或处于锁定期
        """
        user = self._get_user_by_no(officer_no)

        # 步骤 1：账号存在性与状态校验
        if user is None:
            # 防枚举：账号不存在与密码错误返回统一提示
            self._record_login_failure(officer_no, request, reason="账号不存在")
            raise UnauthorizedError("账号或密码错误")

        # 锁定期校验（FR-3.1.1：连续失败锁定）
        if user.is_locked:
            remaining = int((user.locked_until - datetime.now()).total_seconds() // 60) + 1
            self._record_login_failure(officer_no, request, reason="账号锁定中", user=user)
            raise ForbiddenError(f"账号已锁定，请 {remaining} 分钟后重试")

        # 账号停用校验
        if not user.is_active:
            self._record_login_failure(officer_no, request, reason="账号停用", user=user)
            raise ForbiddenError("账号已停用，请联系管理员")

        # 步骤 2：密码校验（加盐哈希比对）
        if not verify_password(password, user.password_hash):
            self._handle_password_failure(user, request)
            raise UnauthorizedError("账号或密码错误")

        # 密码正确：重置失败计数与锁定状态
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = datetime.now()

        # 步骤 3&4：加载权限并签发会话凭证（SE-1）
        permissions = [p.value for p in ROLE_PERMISSIONS.get(user.role_enum, set())]
        token = create_access_token(
            subject=user.officer_no,
            extra_claims={
                "user_id": user.id,
                "role": user.role,
                "org_id": user.org_id,
                "org_path": user.org.org_path if user.org else "",
                "permissions": permissions,
            },
        )

        self.db.commit()

        # 步骤 5：写入登录审计（2.4.2：账号、时间、IP、结果）
        self.audit.log(
            op_type=AuditOpType.LOGIN,
            officer_no=user.officer_no,
            request=request,
            op_result="success",
            description=f"用户 {user.name}({user.officer_no}) 登录成功",
            detail={"role": user.role, "org_id": user.org_id},
        )
        return user, token

    def _handle_password_failure(self, user: User, request=None) -> None:
        """处理密码错误：累加失败计数，达阈值则锁定账号（FR-3.1.1）。"""
        user.failed_login_count += 1
        if user.failed_login_count >= settings.LOGIN_MAX_FAILURES:
            # 达到阈值：锁定 LOGIN_LOCK_MINUTES 分钟，并清零计数
            user.locked_until = datetime.now() + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            user.failed_login_count = 0
        self.db.commit()
        self._record_login_failure(user.officer_no, request, reason="密码错误", user=user)

    def _record_login_failure(self, officer_no: str, request, reason: str, user: User | None = None) -> None:
        """记录登录失败审计（2.4.2 登录/登出：结果）。"""
        self.audit.log(
            op_type=AuditOpType.LOGIN,
            officer_no=officer_no,
            request=request,
            op_result="failure",
            description=f"登录失败：{reason}",
            detail={"reason": reason, "locked": bool(user and user.is_locked)},
        )

    def logout(self, user: User, request=None) -> None:
        """登出：写入登出审计（SE-1/2.4.2）。

        注：JWT 为无状态令牌，登出主要通过前端清除凭证 + 审计留痕实现；
        如需服务端强制失效，可引入令牌黑名单（本期以审计留痕为主）。
        """
        self.audit.log(
            op_type=AuditOpType.LOGOUT,
            officer_no=user.officer_no,
            request=request,
            op_result="success",
            description=f"用户 {user.name}({user.officer_no}) 登出",
        )

    def is_captcha_required(self, officer_no: str) -> bool:
        """判断是否需要验证码（FR-3.1.1：连续失败 3 次后启用）。"""
        user = self._get_user_by_no(officer_no)
        if user is None:
            return False
        return user.failed_login_count >= settings.CAPTCHA_ENABLE_AFTER_FAILURES
