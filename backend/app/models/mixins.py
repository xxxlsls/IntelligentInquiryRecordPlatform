"""
ORM 通用混入（Mixin）

提供可复用的主键与时间戳字段定义，减少各实体的重复代码。
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column


def _gen_uuid() -> str:
    """生成 32 位无连字符的 UUID 字符串，作为业务主键。

    使用字符串主键而非自增整数，便于分布式环境与数据迁移（NFR-U4）。
    """
    return uuid.uuid4().hex


class UUIDPrimaryKeyMixin:
    """字符串 UUID 主键混入。"""

    id: Mapped[str] = mapped_column(
        String(32),
        primary_key=True,
        default=_gen_uuid,
        comment="主键（UUID）",
    )


class TimestampMixin:
    """创建/更新时间戳混入（对应 7.2.1 created_at/updated_at 非空约束）。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )
