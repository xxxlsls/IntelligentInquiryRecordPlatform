"""
应用配置（基于 pydantic-settings）

集中管理系统运行参数，支持通过环境变量或 .env 文件覆盖默认值。
配置项对应需求文档中的可配置策略（会话超时、锁定阈值、AI 权重、文件大小限制、
五流核心要素清单、数据保留期限等），实现 NFR-U4 可扩展性要求。

对应需求文档：
- 2.4.1 SE-3 会话超时策略（默认 30 分钟）
- FR-3.1.1 连续失败锁定（默认 5 次锁定 15 分钟）
- FR-3.3.2 匹配度加权算法 α/β/γ 与置信度阈值
- FR-3.4.4 文件大小/类型限制
- 5.3 五流核心要素清单可配
- 9.4 NFR-C2 数据保留期限
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置对象。字段名大小写不敏感，可通过同名环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",           # 支持从 .env 加载
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用基础信息 ----------
    APP_NAME: str = "智能问询笔录平台"
    APP_VERSION: str = "1.0.0"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # ---------- 数据库 ----------
    # 演示环境默认使用 SQLite；生产可替换为 postgresql+psycopg2://... 或 mysql+pymysql://...
    DATABASE_URL: str = "sqlite:///./inquiry_platform.db"
    DB_ECHO: bool = False          # 是否打印 SQL（调试用）

    # ---------- 安全与会话（SE-1 ~ SE-4） ----------
    JWT_SECRET_KEY: str = "change-this-secret-key-in-production-2026"
    JWT_ALGORITHM: str = "HS256"
    # 会话空闲超时（分钟），默认 30（SE-3，可配置，对应 12.3 Q-4）
    SESSION_TIMEOUT_MINUTES: int = 30
    # 登录连续失败锁定阈值（FR-3.1.1）
    LOGIN_MAX_FAILURES: int = 5
    # 锁定时长（分钟）
    LOGIN_LOCK_MINUTES: int = 15
    # 启用验证码的连续失败次数（FR-3.1.1：连续失败 3 次后启用）
    CAPTCHA_ENABLE_AFTER_FAILURES: int = 3

    # ---------- CORS 跨域（前后端分离） ----------
    CORS_ORIGINS: list[str] = ["*"]

    # ---------- AI 匹配度加权算法（FR-3.3.2） ----------
    # S(D,T) = α·F_sig + β·F_cat + γ·F_sem，且 α+β+γ=1
    AI_WEIGHT_SIGNAL: float = 0.4   # α 信号词命中因子权重
    AI_WEIGHT_CATEGORY: float = 0.2  # β 案由类别因子权重
    AI_WEIGHT_SEMANTIC: float = 0.4  # γ 语义相似因子权重
    # 高置信度推荐阈值（默认 0.6，可配置）
    AI_CONFIDENCE_THRESHOLD: float = 0.6
    # 推荐模板 TOP N（默认 5）
    AI_RECOMMEND_TOP_N: int = 5
    # 同类近似案由的类别因子取值（FR-3.3.2：一致 1.0 / 近似 0.6 / 不一致 0）
    AI_CATEGORY_SIMILAR_SCORE: float = 0.6

    # ---------- 五流要素分析（5.3 / Q-5） ----------
    # 核心要素清单（可配），默认资金流 F-01/F-02/F-04/F-06/F-08 为核心要素
    FIVEFLOW_CORE_ELEMENTS: list[str] = ["F-01", "F-02", "F-04", "F-06", "F-08"]

    # ---------- 文件与存储（FR-3.4.4 / BE-7） ----------
    UPLOAD_DIR: str = "./uploads"               # 辅助材料存储目录
    MAX_FILE_SIZE_MB: int = 50                  # 单文件大小上限（默认 50MB，可配）
    ENABLE_VIRUS_SCAN: bool = True              # 是否启用病毒扫描（演示为模拟扫描）

    # ---------- 审计与数据保留（9.4 NFR-C2） ----------
    AUDIT_RETENTION_YEARS: int = 3              # 审计/笔录保留期限（默认≥3 年）

    # ---------- 跨机构协作（DR-5，本期默认关闭，Q-3 预留） ----------
    ENABLE_CROSS_ORG_ACCESS: bool = False

    # ---------- 演示数据 ----------
    SEED_DEMO_DATA: bool = True                 # 启动时是否初始化种子数据


@lru_cache
def get_settings() -> Settings:
    """获取全局配置单例（带缓存，避免重复读取环境变量）。"""
    return Settings()


# 全局配置实例，供各模块直接导入使用
settings = get_settings()
