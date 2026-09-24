"""
审计监控服务（BE-8）

实现需求文档：
- FR-3.1.4 操作审计日志（关键操作切面拦截 → 写入审计存储 → 生成变更指纹）；
- 2.4.2 敏感操作审计（登录/登出、案件访问、外部同步、问答修改、采纳建议、
  上传材料、文书导出、越权拦截、配置变更）；
- 8.4 审计流水字段；
- NFR-S5/NFR-C3 审计日志只增不删不改；
- 异常与边界：审计写入失败不阻断主流程但需告警重试。
"""

import json
import logging
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AuditOpType
from app.core.security import compute_fingerprint
from app.models.audit import AuditLog

# 审计模块专用日志器（写入失败时告警，FR-3.1.4 异常与边界）
logger = logging.getLogger("audit")


class AuditService:
    """审计监控服务。

    提供审计写入与检索能力。写入采用"尽力而为"策略：失败仅告警不抛异常，
    确保审计不阻断主业务流程（FR-3.1.4）。
    """

    def __init__(self, db: Session):
        """
        :param db: 数据库会话
        """
        self.db = db

    # ---------- 内部工具 ----------
    @staticmethod
    def _extract_client_info(request: Request | None) -> tuple[str | None, str | None]:
        """从请求中提取客户端 IP 与 User-Agent（8.4 ip 字段）。

        优先读取代理转发头 X-Forwarded-For / X-Real-IP，兼容反向代理部署。
        """
        if request is None:
            return None, None
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.headers.get("X-Real-IP") or (
                request.client.host if request.client else None
            )
        user_agent = request.headers.get("User-Agent")
        return ip, user_agent

    # ---------- 写入 ----------
    def log(
        self,
        *,
        op_type: AuditOpType,
        officer_no: str,
        case_no: str | None = None,
        session_id: str | None = None,
        request: Request | None = None,
        op_result: str = "success",
        description: str | None = None,
        detail: dict[str, Any] | None = None,
        change_fingerprint: str | None = None,
        commit: bool = True,
    ) -> AuditLog | None:
        """写入一条审计流水（通用入口）。

        :param op_type: 操作类型（见 AuditOpType）
        :param officer_no: 操作警员警号
        :param case_no: 关联案件编号（可选）
        :param session_id: 关联会话ID（可选）
        :param request: 当前请求对象（用于提取 IP/UA）
        :param op_result: 操作结果 success/failure/denied
        :param description: 人类可读操作描述
        :param detail: 操作明细字典（序列化为 JSON 存储）
        :param change_fingerprint: 变更指纹（若不传且 detail 存在则自动计算）
        :param commit: 是否立即提交（默认 True）
        :return: 写入成功返回审计对象，失败返回 None（不抛异常）
        """
        try:
            ip, user_agent = self._extract_client_info(request)
            # 变更指纹：未显式提供时，基于明细自动计算（8.4 change_fingerprint）
            fingerprint = change_fingerprint
            if fingerprint is None and detail:
                fingerprint = compute_fingerprint(detail)

            audit = AuditLog(
                case_no=case_no,
                session_id=session_id,
                officer_no=officer_no,
                op_type=op_type.value,
                op_result=op_result,
                change_fingerprint=fingerprint,
                ip=ip,
                user_agent=user_agent,
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                description=description,
            )
            self.db.add(audit)
            if commit:
                self.db.commit()
                self.db.refresh(audit)
            return audit
        except Exception as exc:  # noqa: BLE001
            # 审计写入失败不阻断主流程，仅告警（FR-3.1.4 异常与边界）
            logger.warning("审计写入失败（不阻断主流程）：op_type=%s, err=%s", op_type, exc)
            self.db.rollback()
            return None

    def log_permission_denied(
        self,
        *,
        officer_no: str,
        request: Request | None = None,
        resource: str | None = None,
        reason: str | None = None,
    ) -> None:
        """记录越权拦截审计（DR-4：越权请求返回 403 并记录审计）。"""
        self.log(
            op_type=AuditOpType.PERMISSION_DENIED,
            officer_no=officer_no,
            request=request,
            op_result="denied",
            description=f"越权拦截：{reason or '无权限'}",
            detail={"resource": resource, "reason": reason, "path": str(request.url.path) if request else None},
        )

    def log_qa_change(
        self,
        *,
        officer_no: str,
        session_id: str,
        case_no: str | None,
        action: str,
        qa_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
        request: Request | None = None,
    ) -> None:
        """记录问答修改审计（2.4.2：含变更前后指纹）。"""
        fingerprint = compute_fingerprint(before, after)
        self.log(
            op_type=AuditOpType.QA_MODIFY,
            officer_no=officer_no,
            session_id=session_id,
            case_no=case_no,
            request=request,
            description=f"问答{action}：{qa_id}",
            detail={"action": action, "qa_id": qa_id, "before": before, "after": after},
            change_fingerprint=fingerprint,
        )

    # ---------- 检索（FR-3.1.4 支持条件检索） ----------
    def query(
        self,
        *,
        case_no: str | None = None,
        officer_no: str | None = None,
        op_type: AuditOpType | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        org_path_prefix: str | None = None,
        officer_no_scope: list[str] | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AuditLog], int]:
        """按条件分页检索审计流水。

        :param org_path_prefix: 机构路径前缀（本机构范围审计，反诈研判员用）
        :param officer_no_scope: 警号范围（本人审计，办案民警用）
        :return: (当前页审计列表, 总记录数)
        """
        stmt = select(AuditLog)
        if case_no:
            stmt = stmt.where(AuditLog.case_no == case_no)
        if officer_no:
            stmt = stmt.where(AuditLog.officer_no == officer_no)
        if op_type:
            stmt = stmt.where(AuditLog.op_type == op_type.value)
        if start_time:
            stmt = stmt.where(AuditLog.op_time >= start_time)
        if end_time:
            stmt = stmt.where(AuditLog.op_time <= end_time)
        if officer_no_scope is not None:
            stmt = stmt.where(AuditLog.officer_no.in_(officer_no_scope))

        # 先统计总数（基于过滤后的子查询做 count，避免笛卡尔积）
        total_count = self.db.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()

        # 分页与排序（按时间倒序）
        stmt = stmt.order_by(AuditLog.op_time.desc()).offset((page - 1) * page_size).limit(page_size)
        items = list(self.db.execute(stmt).scalars().all())
        return items, total_count
