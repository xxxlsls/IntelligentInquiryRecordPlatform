"""
数据库连接与会话管理（SQLAlchemy 2.x）

采用声明式 ORM 映射，提供引擎、会话工厂与 FastAPI 依赖注入用的会话获取器。
演示环境使用 SQLite（自动开启外键约束），生产可通过 DATABASE_URL 无缝切换。

对应需求文档：第 7 章 数据模型、NFR-P5 并发支持（连接池）。
"""

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


def _build_engine() -> Engine:
    """根据配置构建数据库引擎。

    - SQLite：关闭同一线程检查以适配多线程 Web 服务，并通过 PRAGMA 开启外键约束；
    - 其他数据库：配置连接池以支撑并发（NFR-P5）。
    """
    url = settings.DATABASE_URL
    if url.startswith("sqlite"):
        engine = create_engine(
            url,
            echo=settings.DB_ECHO,
            # SQLite 在 FastAPI 多线程环境下需关闭同线程限制
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, connection_record):  # noqa: ANN001
            """为每个 SQLite 连接开启外键约束（默认关闭）。"""
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        return engine

    # 非 SQLite（PostgreSQL/MySQL）：启用连接池
    return create_engine(
        url,
        echo=settings.DB_ECHO,
        pool_size=20,
        max_overflow=40,
        pool_pre_ping=True,   # 取连接前探活，避免使用失效连接
        pool_recycle=3600,    # 连接回收周期（秒）
    )


# 全局引擎与会话工厂
engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：为每个请求提供独立的数据库会话，请求结束后自动关闭。

    用法：`db: Session = Depends(get_db)`
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """初始化数据库：创建所有表结构。

    注意：演示环境使用 create_all 建表；生产环境建议使用 Alembic 迁移管理。
    需在调用前确保所有 models 已被导入（在 app.main 中完成）。
    """
    # 导入模型以注册到 Base.metadata（避免循环导入，函数内导入）
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
