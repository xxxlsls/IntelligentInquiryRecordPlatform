"""
组织机构与警员维护路由（BE-1）

对应需求文档 FR-3.1.3 组织机构维护：树形机构增删改查、警员账号维护、机构树。
权限：仅系统管理员可维护（2.2 权限矩阵），通过 require_permission 二次校验。
"""

from fastapi import APIRouter, Depends, Request

from app.core.dependencies import (
    CurrentUser,
    DbSession,
    require_permission,
)
from app.core.enums import Permission, Role
from app.schemas.auth import (
    OrgCreate,
    OrgOut,
    OrgTreeNode,
    OrgUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.schemas.common import ApiResponse
from app.services.org_service import OrgService

router = APIRouter(prefix="/orgs", tags=["BE-1 组织机构与警员"])

# 管理员权限依赖（FR-3.1.3：仅系统管理员）
_admin_required = Depends(require_permission(Permission.ORG_MANAGE))
_user_manage_required = Depends(require_permission(Permission.USER_MANAGE))


def _to_org_tree(org) -> OrgTreeNode:
    """将机构 ORM 对象递归转换为机构树节点。"""
    return OrgTreeNode(
        id=org.id,
        name=org.name,
        code=org.code,
        level=org.level_enum,
        parent_id=org.parent_id,
        children=[_to_org_tree(child) for child in org.children],
    )


# ============================================================
# 机构维护
# ============================================================
@router.get("/tree", response_model=ApiResponse[list[OrgTreeNode]], summary="获取机构树")
def get_org_tree(
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[list[OrgTreeNode]]:
    """获取三级机构树（2.3.1，供前端渲染与数据范围展示）。"""
    orgs = OrgService(db).get_org_tree()
    return ApiResponse.ok([_to_org_tree(o) for o in orgs])


@router.get("", response_model=ApiResponse[list[OrgOut]], summary="获取机构列表")
def list_orgs(
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[list[OrgOut]]:
    """获取扁平机构列表。"""
    orgs = OrgService(db).list_orgs()
    return ApiResponse.ok([OrgOut.model_validate(o) for o in orgs])


@router.post("", response_model=ApiResponse[OrgOut], summary="新增机构",
             dependencies=[_admin_required])
def create_org(
    data: OrgCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[OrgOut]:
    """新增机构（FR-3.1.3，仅管理员）。机构编码唯一性校验。"""
    org = OrgService(db).create_org(data, current_user, request)
    return ApiResponse.ok(OrgOut.model_validate(org), message="机构创建成功")


@router.put("/{org_id}", response_model=ApiResponse[OrgOut], summary="更新机构",
            dependencies=[_admin_required])
def update_org(
    org_id: str,
    data: OrgUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[OrgOut]:
    """更新机构（名称/上级/排序，编码不可改）。"""
    org = OrgService(db).update_org(org_id, data, current_user, request)
    return ApiResponse.ok(OrgOut.model_validate(org), message="机构更新成功")


@router.delete("/{org_id}", response_model=ApiResponse, summary="删除机构",
               dependencies=[_admin_required])
def delete_org(
    org_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse:
    """删除机构（存在下辖机构或在职警员时拒绝，FR-3.1.3 异常与边界）。"""
    OrgService(db).delete_org(org_id, current_user, request)
    return ApiResponse.ok(message="机构删除成功")


# ============================================================
# 警员账号维护（FR-3.1.3）
# ============================================================
@router.get("/users/list", response_model=ApiResponse[list[UserOut]], summary="获取警员列表")
def list_users(
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
    org_id: str | None = None,
    role: Role | None = None,
    _: None = _user_manage_required,
) -> ApiResponse[list[UserOut]]:
    """按机构/角色筛选警员列表（仅管理员）。"""
    users = OrgService(db).list_users(org_id=org_id, role=role)
    result = []
    for u in users:
        out = UserOut.model_validate(u)
        out.org_name = u.org.name if u.org else None
        result.append(out)
    return ApiResponse.ok(result)


@router.post("/users", response_model=ApiResponse[UserOut], summary="新增警员",
             dependencies=[_user_manage_required])
def create_user(
    data: UserCreate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[UserOut]:
    """新增警员账号（警号唯一性校验，FR-3.1.3）。"""
    user = OrgService(db).create_user(data, current_user, request)
    out = UserOut.model_validate(user)
    out.org_name = user.org.name if user.org else None
    return ApiResponse.ok(out, message="警员创建成功")


@router.put("/users/{user_id}", response_model=ApiResponse[UserOut], summary="更新警员",
            dependencies=[_user_manage_required])
def update_user(
    user_id: str,
    data: UserUpdate,
    request: Request,
    current_user: CurrentUser,
    db: DbSession,
) -> ApiResponse[UserOut]:
    """更新警员账号（可重置密码、变更角色/机构/状态）。"""
    user = OrgService(db).update_user(user_id, data, current_user, request)
    out = UserOut.model_validate(user)
    out.org_name = user.org.name if user.org else None
    return ApiResponse.ok(out, message="警员更新成功")
