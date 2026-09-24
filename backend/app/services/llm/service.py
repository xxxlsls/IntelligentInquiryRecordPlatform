"""
LLM 服务门面（大模型私有化接入 · 业务编排层）

对上层业务服务（ai_service / fiveflow_service / import_service）提供统一入口，
封装"提示词构造 → HTTP 调用 → 结构化校验 → 能力开关判定"的完整链路。

降级契约：以下方法在"未启用 / 分能力开关关闭 / 网络异常 / 输出校验失败"时，
统一抛出 LLMUnavailableError，业务层捕获后回落到既有规则算法，保证行为一致。

同时提供运维能力：
- status()            可达性与开关状态（供 /ai/llm/status 接口）
- reindex_templates() 批量计算并持久化启用模板的语义指纹向量（能力一支撑）
"""

import json
import logging

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.template import Template
from app.services.llm.client import LLMUnavailableError, get_llm_client
from app.services.llm.prompts import (
    build_extract_elements_prompt,
    build_judge_case_prompt,
    build_parse_record_prompt,
    build_semantic_fingerprint_text,
)
from app.services.llm.schemas import (
    LLMCaseJudgement,
    LLMExtractionResult,
    LLMParseResult,
)

logger = logging.getLogger("app.llm")


class LLMService:
    """大模型能力门面（持有 db，供各业务服务注入）。"""

    def __init__(self, db: Session):
        self.db = db
        self.client = get_llm_client()

    # ------------------------------------------------------------
    # 内部工具：能力开关判定
    # ------------------------------------------------------------
    @staticmethod
    def _ensure_capable(enabled_flag: bool, capability: str) -> None:
        """校验总开关与分能力开关；任一关闭即抛降级信号。"""
        if not settings.LLM_ENABLED:
            raise LLMUnavailableError(f"LLM 未启用，{capability}降级到规则算法")
        if not enabled_flag:
            raise LLMUnavailableError(f"{capability}能力开关已关闭，降级到规则算法")

    # ============================================================
    # 能力二：侦查研判建议生成
    # ============================================================
    def judge_case(self, context: str, categories: list[str] | None = None,
                   key_gaps: list[dict] | None = None) -> LLMCaseJudgement:
        """调用大模型生成侦查研判结构化结果（能力二）。

        :param context: 案情 + 已答问答拼接的上下文
        :param categories: 可选案由清单（默认内置 19 类）
        :param key_gaps: 五流重点缺口清单，用于引导追问
        :raises LLMUnavailableError: 未启用/开关关闭/网络异常/校验失败
        """
        self._ensure_capable(settings.LLM_ENABLE_ANALYSIS, "侦查研判")
        messages = build_judge_case_prompt(context, categories, key_gaps)
        raw = self.client.chat_json(messages)
        try:
            return LLMCaseJudgement.model_validate(raw)
        except ValidationError as exc:
            raise LLMUnavailableError(f"研判结果校验失败：{exc}") from exc

    # ============================================================
    # 能力三：五流要素抽取（LLM 侧候选）
    # ============================================================
    def extract_elements(self, qa_text: str, candidate_codes: list[str] | None = None) -> LLMExtractionResult:
        """调用大模型抽取五流要素（能力三，高召回，与正则高精度融合）。

        :param qa_text: 待抽取问答文本
        :param candidate_codes: 候选要素编号（缩小范围）
        :raises LLMUnavailableError: 未启用/开关关闭/网络异常/校验失败
        """
        self._ensure_capable(settings.LLM_ENABLE_EXTRACTION, "五流要素抽取")
        messages = build_extract_elements_prompt(qa_text, candidate_codes)
        raw = self.client.chat_json(messages)
        try:
            return LLMExtractionResult.model_validate(raw)
        except ValidationError as exc:
            raise LLMUnavailableError(f"要素抽取结果校验失败：{exc}") from exc

    # ============================================================
    # 能力四：历史笔录解析导入
    # ============================================================
    def parse_record(self, text: str) -> LLMParseResult:
        """调用大模型解析历史笔录为问答对 + 章节归类 + 缺口追问草稿（能力四）。

        :raises LLMUnavailableError: 未启用/开关关闭/网络异常/校验失败
        """
        self._ensure_capable(settings.LLM_ENABLE_IMPORT_PARSE, "历史笔录解析")
        messages = build_parse_record_prompt(text)
        raw = self.client.chat_json(messages)
        try:
            return LLMParseResult.model_validate(raw)
        except ValidationError as exc:
            raise LLMUnavailableError(f"笔录解析结果校验失败：{exc}") from exc

    # ============================================================
    # 能力一：语义向量（供语义匹配推荐）
    # ============================================================
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量计算文本向量（能力一底层原语）。

        :raises LLMUnavailableError: 未启用/网络异常
        """
        if not settings.LLM_ENABLED:
            raise LLMUnavailableError("LLM 未启用，无法计算语义向量")
        return self.client.embed(texts)

    def is_semantic_enabled(self) -> bool:
        """语义匹配能力是否可用（总开关 + 分能力开关）。"""
        return bool(settings.LLM_ENABLED and settings.LLM_ENABLE_SEMANTIC_MATCH)

    # ============================================================
    # 运维能力
    # ============================================================
    def status(self) -> dict:
        """返回 LLM 可达性与配置状态（供 /ai/llm/status 运维接口，不抛异常）。"""
        reachable = self.client.ping()
        return {
            "enabled": bool(settings.LLM_ENABLED),
            "reachable": reachable,
            "base_url": settings.LLM_BASE_URL,
            "chat_model": settings.LLM_CHAT_MODEL,
            "embedding_model": settings.LLM_EMBEDDING_MODEL,
            "capabilities": {
                "semantic_match": bool(settings.LLM_ENABLE_SEMANTIC_MATCH),
                "analysis": bool(settings.LLM_ENABLE_ANALYSIS),
                "extraction": bool(settings.LLM_ENABLE_EXTRACTION),
                "import_parse": bool(settings.LLM_ENABLE_IMPORT_PARSE),
            },
        }

    def reindex_templates(self) -> dict:
        """批量计算并持久化启用模板的语义指纹向量（能力一支撑）。

        管理员在模板变更后调用；启动时若开启语义能力亦 best-effort 预计算。
        向量以 JSON 字符串写入 Template.embedding，并记录生成模型 Template.embedding_model；
        模型变更后 embedding_model 不匹配即视为过期，下次推荐时即时重算。

        :return: {"indexed": 成功数, "failed": 失败数, "model": 向量模型名}
        """
        if not self.is_semantic_enabled():
            raise LLMUnavailableError("语义匹配能力未启用，无法重建模板向量索引")

        templates = list(
            self.db.execute(
                select(Template)
                .options(selectinload(Template.signal_words))
                .where(Template.is_enabled.is_(True))
            ).scalars().all()
        )
        if not templates:
            return {"indexed": 0, "failed": 0, "model": settings.LLM_EMBEDDING_MODEL}

        # 构造每个模板的语义指纹文本（与规则算法同源）
        fingerprints = [
            build_semantic_fingerprint_text(
                t.category, t.description, [w.word for w in (t.signal_words or []) if w.word]
            )
            for t in templates
        ]
        # 单次批量向量化，降低请求次数
        vectors = self.embed_texts(fingerprints)

        indexed = 0
        for tpl, vec in zip(templates, vectors):
            tpl.embedding = json.dumps(vec)
            tpl.embedding_model = settings.LLM_EMBEDDING_MODEL
            indexed += 1
        self.db.commit()
        logger.info("模板语义向量重建完成：成功 %d 条，模型 %s", indexed, settings.LLM_EMBEDDING_MODEL)
        return {"indexed": indexed, "failed": len(templates) - indexed, "model": settings.LLM_EMBEDDING_MODEL}
