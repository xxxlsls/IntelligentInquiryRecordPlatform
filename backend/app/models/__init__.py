"""
models 包 · SQLAlchemy ORM 数据模型

集中导出所有实体模型，确保在 init_db() 建表前全部注册到 Base.metadata。
实体编号对应需求文档 7.1 核心实体清单（DE-1 ~ DE-10）。
"""

from app.core.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import Org, User
from app.models.case import Case, Reporter
from app.models.template import Template, TemplateQuestion, TemplateSignalWord
from app.models.record import RecordSession, QAItem, AiSuggestion, SessionTemplate
from app.models.fiveflow import FiveFlowElement, FlowElementDefinition
from app.models.material import Material
from app.models.audit import AuditLog

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "Org",
    "User",
    "Case",
    "Reporter",
    "Template",
    "TemplateQuestion",
    "TemplateSignalWord",
    "RecordSession",
    "QAItem",
    "AiSuggestion",
    "SessionTemplate",
    "FiveFlowElement",
    "FlowElementDefinition",
    "Material",
    "AuditLog",
]
