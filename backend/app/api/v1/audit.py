"""
操作审计路由（BE-8）

对应需求文档：
- FR-3.1.4 操作审计日志（条件检索：案件编号/警号/操作类型/时间范围）；
- 8.4 操作审计流水记录字段；
- NFR-S5/NFR-C3 审计日志只增不删不改；
- 2.2 权限矩阵审计查看范围：
    · 办案民警  AUDIT_VIEW_SELF → 仅本人审计；
    · 反诈研判员 AUDIT_VIEW_ORG  → 本机构（含下辖）审计；
    · 系统管理员 AUDIT_VIEW_ALL  → 全量审计。

接口能力：
1) GET /audit/logs  按条件分页检索审计流水（数据范围随角色收敛）。
"""

import json
from datetime import datetime

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.dependencies import CurrentScope, CurrentUser, DbSession
from app.core.enums import AuditOpType, Permission
from app.core.exceptions import ForbiddenError
from app.models.user import User
from app.schemas.audit import AuditLogOut
from app.schemas.common import ApiResponse, PageResult
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["BE-8 操作审计"])

# 三级审计查看权限
_AUDIT_PERMS = (Permission.AUDIT_VIEW_ALL, Permission.AUDIT_VIEW_ORG, Permission.AUDIT_VIEW_SELF)


def _resolve_audit_scope(scope, db) -> list[str] | None:
    """根据角色解析审计数据范围（返回可见警号列表；None 表示全量）。

    - 管理员（AUDIT_VIEW_ALL）：全量，返回 None；
    - 反诈研判员（AUDIT_VIEW_ORG）：本机构及下辖机构的全部警号；
    - 办案民警（AUDIT_VIEW_SELF）：仅本人警号。
    """
    from app.core.dependencies import get_permissions

    perms = get_permissions(scope.user)
    if Permission.AUDIT_VIEW_ALL in perms:
        return None  # 全量
    if Permission.AUDIT_VIEW_ORG in perms:
        # 本机构范围（org_path 前缀匹配下辖机构）：收集范围内全部警号
        prefix = scope.org_path_prefix
        if not prefix:
            return [scope.user.officer_no]
        # 逐用户按机构路径前缀过滤（兼容 SQLite/PostgreSQL/MySQL 各方言）
        all_users = db.execute(select(User)).scalars().all()
        officer_nos = [
            u.officer_no for u in all_users
            if u.org and u.org.org_path and u.org.org_path.startswith(prefix)
        ]
        return officer_nos or [scope.user.officer_no]
    if Permission.AUDIT_VIEW_SELF in perms:
        return [scope.user.officer_no]
    # 无任何审计查看权限
    return []


@router.get("/logs", response_model=ApiResponse[PageResult[AuditLogOut]], summary="审计日志检索")
def query_audit_logs(
    scope: CurrentScope,
    current_user: CurrentUser,
    db: DbSession,
    case_no: str | None = Query(default=None, description="案件编号"),
    officer_no: str | None = Query(default=None, description="警员警号"),
    op_type: AuditOpType | None = Query(default=None, description="操作类型"),
    start_time: datetime | None = Query(default=None, description="起始时间"),
    end_time: datetime | None = Query(default=None, description="结束时间"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
) -> ApiResponse[PageResult[AuditLogOut]]:
    """按条件分页检索审计流水（FR-3.1.4），数据范围随角色收敛。

    越权（无任一审计查看权限）返回 403；范围外的警号检索被自动收敛到可见范围。
    """
    from app.core.dependencies import get_permissions

    perms = get_permissions(current_user)
    if not any(p in perms for p in _AUDIT_PERMS):
        raise ForbiddenError("无权查看审计日志")

    # 解析可见警号范围（None=全量）
    officer_scope = _resolve_audit_scope(scope, db)
    if officer_scope is not None and not officer_scope:
        # 无任何可见范围，直接返回空
        return ApiResponse.ok(PageResult.of([], 0, page, page_size))

    # 若指定了 officer_no 检索，需确保其在可见范围内（防止越权窥探）
    if officer_no and officer_scope is not None and officer_no not in officer_scope:
        raise ForbiddenError("无权查看该警员的审计记录（超出数据范围）")

    items, total = AuditService(db).query(
        case_no=case_no,
        officer_no=officer_no,
        op_type=op_type,
        start_time=start_time,
        end_time=end_time,
        officer_no_scope=officer_scope,
        page=page,
        page_size=page_size,
    )
    # 组装输出（detail 字段在库中为 JSON 字符串，需先反序列化为 dict 再校验）
    result = []
    for log in items:
        detail_dict = None
        if log.detail:
            try:
                detail_dict = json.loads(log.detail)
            except (json.JSONDecodeError, TypeError):
                detail_dict = None
        data = {
            "id": log.id,
            "case_no": log.case_no,
            "session_id": log.session_id,
            "officer_no": log.officer_no,
            "op_type": log.op_type,
            "op_time": log.op_time,
            "op_result": log.op_result,
            "change_fingerprint": log.change_fingerprint,
            "ip": log.ip,
            "description": log.description,
            "detail": detail_dict,
        }
        result.append(AuditLogOut.model_validate(data))
    return ApiResponse.ok(PageResult.of(result, total, page, page_size))
