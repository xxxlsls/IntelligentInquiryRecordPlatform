"""
认证与权限路由（BE-1）

对应需求文档：
- FR-3.1.1 用户认证登录（POST /auth/login）；
- FR-3.1.2 角色权限管理（GET /auth/permissions）；
- FR-3.1.5 Cookie 会话管理与统一拦截（GET /auth/me 会话校验、POST /auth/logout）；
- SE-1~SE-4 会话管理。
"""

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import settings
from app.core.dependencies import CurrentUser, DbSession, get_permissions
from app.schemas.auth import LoginRequest, LoginResponse, UserInfo
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["BE-1 认证与权限"])


@router.post("/login", response_model=ApiResponse[LoginResponse], summary="用户认证登录")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
) -> ApiResponse[LoginResponse]:
    """用户登录（FR-3.1.1）。

    校验账号密码 → 加载角色与机构权限 → 签发会话凭证 → 写入登录审计。
    同时在 Cookie 中写入会话凭证，支持 Cookie + Token 双机制（SE-1）。
    """
    service = AuthService(db)
    user, token = service.authenticate(payload.officer_no, payload.password, request)

    # 组装用户身份信息（含权限清单，FR-3.1.2）
    permissions = [p.value for p in get_permissions(user)]
    user_info = UserInfo(
        id=user.id,
        officer_no=user.officer_no,
        name=user.name,
        role=user.role_enum,
        org_id=user.org_id,
        org_name=user.org.name if user.org else None,
        org_path=user.org.org_path if user.org else None,
        permissions=permissions,
    )
    login_resp = LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.SESSION_TIMEOUT_MINUTES * 60,
        user=user_info,
    )

    # 写入 Cookie 会话凭证（HttpOnly 防 XSS，SE-1/NFR-S4）
    response.set_cookie(
        key="access_token",
        value=token,
        max_age=settings.SESSION_TIMEOUT_MINUTES * 60,
        httponly=True,
        samesite="lax",
    )
    return ApiResponse.ok(login_resp, message="登录成功")


@router.get("/me", response_model=ApiResponse[UserInfo], summary="会话校验与当前用户")
def get_me(current_user: CurrentUser) -> ApiResponse[UserInfo]:
    """会话校验（FR-3.1.5）：返回当前登录用户身份、角色、机构与权限清单。

    依赖 get_current_user 完成凭证校验，失效时自动返回 401（SE-2）。
    """
    user_info = UserInfo(
        id=current_user.id,
        officer_no=current_user.officer_no,
        name=current_user.name,
        role=current_user.role_enum,
        org_id=current_user.org_id,
        org_name=current_user.org.name if current_user.org else None,
        org_path=current_user.org.org_path if current_user.org else None,
        permissions=[p.value for p in get_permissions(current_user)],
    )
    return ApiResponse.ok(user_info)


@router.post("/logout", response_model=ApiResponse, summary="登出")
def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """登出（SE-1/2.4.2）：写入登出审计并清除 Cookie 会话凭证。"""
    AuthService(db).logout(current_user, request)
    response.delete_cookie("access_token")
    return ApiResponse.ok(message="已安全登出")


@router.get("/permissions", response_model=ApiResponse[list[str]], summary="查询当前用户权限清单")
def get_my_permissions(current_user: CurrentUser) -> ApiResponse[list[str]]:
    """权限查询（BE-1 主要接口能力）：返回当前用户的权限项清单（FR-3.1.2）。"""
    return ApiResponse.ok([p.value for p in get_permissions(current_user)])
