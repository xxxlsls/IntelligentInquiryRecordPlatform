"""
统一异常体系与全局异常处理器

定义业务异常基类与常见异常子类，配合 FastAPI 异常处理器返回统一的 JSON 错误结构，
避免堆栈信息泄漏，并为越权/未认证等安全事件提供标准状态码（401/403）。

对应需求文档：
- FR-3.1.5 凭证过期/篡改 → 401 重定向；越权 → 403 记录审计；
- DR-4 越权请求返回 403 并记录审计；
- 各功能"异常与边界"章节的统一错误响应。
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 422 状态码：新版 Starlette 将 HTTP_422_UNPROCESSABLE_ENTITY 重命名为
# HTTP_422_UNPROCESSABLE_CONTENT（旧名已弃用）。此处做版本兼容，避免弃用告警。
if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _HTTP_422_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_CONTENT
else:  # 兼容旧版 Starlette
    _HTTP_422_UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_ENTITY


class BusinessException(Exception):
    """业务异常基类。

    所有可预期的业务错误（如案件编号重复、阶段流转非法、模板被引用不可删）
    均应抛出本类或其子类，由全局处理器转换为标准 4xx 响应。
    """

    # 默认 HTTP 状态码与业务错误码
    status_code: int = status.HTTP_400_BAD_REQUEST
    error_code: str = "BUSINESS_ERROR"
    default_message: str = "业务处理失败"

    def __init__(self, message: str | None = None, *, detail: dict | None = None):
        """
        :param message: 面向用户的错误提示（覆盖默认消息）
        :param detail: 附加错误明细（如字段级校验信息）
        """
        self.message = message or self.default_message
        self.detail = detail or {}
        super().__init__(self.message)


class UnauthorizedError(BusinessException):
    """未认证：会话凭证缺失/过期/非法（SE-2，返回 401 触发前端重定向）。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "UNAUTHORIZED"
    default_message = "登录状态已失效，请重新登录"


class ForbiddenError(BusinessException):
    """越权访问：登录态有效但无权限或超出机构数据范围（DR-4，返回 403 并审计）。"""

    status_code = status.HTTP_403_FORBIDDEN
    error_code = "FORBIDDEN"
    default_message = "无权执行该操作"


class NotFoundError(BusinessException):
    """资源不存在（如笔录会话、案件、模板未找到）。"""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    default_message = "请求的资源不存在"


class ConflictError(BusinessException):
    """资源冲突（如案件编号重复、警号重复、机构编码重复）。"""

    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"
    default_message = "资源已存在或状态冲突"


class ValidationError(BusinessException):
    """业务校验失败（如必填缺失、状态阈值不满足）。"""

    status_code = _HTTP_422_UNPROCESSABLE
    error_code = "VALIDATION_ERROR"
    default_message = "输入数据校验未通过"


class ExternalSystemError(BusinessException):
    """外部系统异常（智研判/智案管超时或不可用，FR-3.2.2 降级处理）。"""

    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "EXTERNAL_SYSTEM_ERROR"
    default_message = "外部系统暂不可用，请降级为手工录入"


# ============================================================
# 全局异常处理器注册
# ============================================================
def register_exception_handlers(app: FastAPI) -> None:
    """将统一异常处理器注册到 FastAPI 应用。

    处理器优先级：业务异常 → 参数校验异常 → HTTP 异常 → 兜底未知异常。
    统一响应结构：{ "success": false, "error_code": ..., "message": ..., "detail": ... }
    """

    @app.exception_handler(BusinessException)
    async def business_exception_handler(request: Request, exc: BusinessException):  # noqa: ARG001
        """处理所有可预期业务异常，返回标准错误结构。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": exc.error_code,
                "message": exc.message,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):  # noqa: ARG001
        """处理 Pydantic 请求体/参数校验异常，提取字段级错误明细。"""
        errors = [
            {
                "field": ".".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=_HTTP_422_UNPROCESSABLE,
            content={
                "success": False,
                "error_code": "VALIDATION_ERROR",
                "message": "请求参数校验未通过",
                "detail": {"errors": errors},
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):  # noqa: ARG001
        """处理框架抛出的标准 HTTP 异常（如 404 路由不存在、405 方法不允许）。"""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error_code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "detail": {},
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
        """兜底处理未知异常，避免堆栈泄漏；生产环境应记录日志并告警。"""
        # 调试模式下返回异常信息便于排查，生产模式仅返回通用提示
        from app.core.config import settings

        message = str(exc) if settings.DEBUG else "服务器内部错误，请稍后重试"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error_code": "INTERNAL_ERROR",
                "message": message,
                "detail": {},
            },
        )
