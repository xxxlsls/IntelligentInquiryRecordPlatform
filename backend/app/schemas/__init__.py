"""
schemas 包 · Pydantic 请求/响应模型

定义 API 层的输入校验与输出序列化模型，与 ORM 模型解耦。
按业务模块组织，对应需求文档各功能点的"输入项及校验规则"与"输出/结果"。
"""

from app.schemas.common import (
    ApiResponse,
    PageResult,
    IDResponse,
    OperationResult,
)

__all__ = [
    "ApiResponse",
    "PageResult",
    "IDResponse",
    "OperationResult",
]
