"""
应用入口（FastAPI）

智能问询笔录平台后端服务启动装配：
1) 创建 FastAPI 应用（标题/版本/文档）；
2) 注册全局异常处理器（统一错误响应结构）；
3) 配置 CORS（前后端分离跨域）；
4) 挂载 v1 路由（八大后端模块，前缀 /api/v1）；
5) 启动生命周期：初始化数据库表结构 + 幂等种子数据（五流要素/机构/账号/19 类模板）。

对应需求文档：3.7 后端模块划分、9 非功能需求、10 验收标准（AC-1 演示账号）。

运行：
    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
或使用启动脚本：
    python run.py
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.exceptions import register_exception_handlers

# 日志配置（审计/种子/应用）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化数据库与种子数据。

    - init_db()：创建全部表结构（演示环境 create_all，生产建议 Alembic 迁移）；
    - seed_all()：幂等初始化五流要素定义、三级机构、演示账号、19 类模板库。
    已存在的数据不重复写入，可安全多次启动。
    """
    logger.info("正在初始化数据库表结构 ...")
    init_db()

    if settings.SEED_DEMO_DATA:
        logger.info("正在初始化种子数据（五流要素/机构/账号/模板）...")
        # 导入种子编排（延迟导入，确保模型已注册）
        from app.seed.seed_data import seed_all

        db = SessionLocal()
        try:
            stats = seed_all(db)
            logger.info("种子数据初始化完成：%s", stats)
        finally:
            db.close()

    # 大模型私有化接入：若总开关与语义能力开启，best-effort 预计算模板语义向量（能力一）。
    # 异常仅告警不阻断启动：模型不可达时推荐链路会自动降级到字符 bigram。
    if settings.LLM_ENABLED and settings.LLM_ENABLE_SEMANTIC_MATCH:
        from app.services.llm import LLMService, LLMUnavailableError

        db = SessionLocal()
        try:
            result = LLMService(db).reindex_templates()
            logger.info("模板语义向量预计算完成：%s", result)
        except LLMUnavailableError as exc:
            logger.warning("模板语义向量预计算跳过（模型不可达）：%s", exc)
        except Exception as exc:  # noqa: BLE001 预计算失败不得阻断启动
            logger.warning("模板语义向量预计算异常（已忽略）：%s", exc)
        finally:
            db.close()

    logger.info("%s v%s 启动完成，API 前缀：%s", settings.APP_NAME, settings.APP_VERSION, settings.API_V1_PREFIX)
    yield
    # 关闭时的清理逻辑（当前无需释放的资源）
    logger.info("应用正在关闭 ...")


def create_app() -> FastAPI:
    """应用工厂：装配并返回 FastAPI 实例。"""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "面向公安执法与电信网络诈骗侦查场景的智能问询笔录平台后端服务。\n\n"
            "涵盖八大后端模块：BE-1 认证与权限、BE-2 笔录生命周期、BE-3 外部系统集成、"
            "BE-4 模板配置、BE-5 AI 研判推荐、BE-6 五流要素分析、BE-7 文件存储与文书导出、BE-8 操作审计。"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 全局异常处理器（统一错误响应结构，避免堆栈泄漏）
    register_exception_handlers(app)

    # CORS 跨域（前后端分离，NFR-U4；生产应通过配置收敛允许来源）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # 暴露文书版本指纹等自定义响应头（IR-4）
        expose_headers=["X-Document-Fingerprint", "X-Document-Name", "Content-Disposition"],
    )

    # 挂载 v1 业务路由
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # ---------- 基础探活接口 ----------
    @app.get("/", tags=["系统"], summary="服务根路径")
    def root() -> dict:
        """服务根路径：返回应用名称、版本与文档地址。"""
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "api_prefix": settings.API_V1_PREFIX,
        }

    @app.get("/health", tags=["系统"], summary="健康检查")
    def health() -> dict:
        """健康检查（NFR-A1 可用性监控探针）。"""
        return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}

    return app


# 全局应用实例（供 uvicorn app.main:app 加载）
app = create_app()
