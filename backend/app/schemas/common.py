"""
通用响应模型

统一 API 响应结构，便于前端拦截器统一处理（FR-3.1.5）。
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应包装。

    结构：{ success, code, message, data }
    前端拦截器据 success 判定成功/失败，失败时读取 message 提示（SE-2）。
    """

    success: bool = Field(default=True, description="请求是否成功")
    code: str = Field(default="OK", description="业务状态码")
    message: str = Field(default="操作成功", description="提示信息")
    data: T | None = Field(default=None, description="业务数据载荷")

    @classmethod
    def ok(cls, data: T | None = None, message: str = "操作成功") -> "ApiResponse[T]":
        """构造成功响应。"""
        return cls(success=True, code="OK", message=message, data=data)

    @classmethod
    def fail(cls, message: str, code: str = "ERROR", data: T | None = None) -> "ApiResponse[T]":
        """构造失败响应。"""
        return cls(success=False, code=code, message=message, data=data)


class PageResult(BaseModel, Generic[T]):
    """分页结果包装（对应 UI-1 分页导航、FR-3.1.4 审计分页检索）。"""

    items: list[T] = Field(default_factory=list, description="当前页数据列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码（从 1 开始）")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")

    @classmethod
    def of(cls, items: list[T], total: int, page: int, page_size: int) -> "PageResult[T]":
        """根据列表与总数构造分页结果，自动计算总页数。"""
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


class IDResponse(BaseModel):
    """仅返回新建资源 ID 的轻量响应。"""

    id: str = Field(description="资源主键 ID")


class OperationResult(BaseModel):
    """操作结果响应（含可选附加信息）。"""

    success: bool = Field(default=True, description="操作是否成功")
    message: str = Field(default="", description="结果描述")
    extra: dict | None = Field(default=None, description="附加数据")
