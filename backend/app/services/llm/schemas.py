"""
LLM 结构化输出校验模型（大模型私有化接入 · 契约层）

用途：约束大模型返回的 JSON 结构，将其校验/规整为业务可安全消费的对象。
设计原则：
- 校验失败视为"模型不可用"，由上层捕获 ValidationError 触发降级到规则算法；
- 章节、要素编号等业务枚举字段需回落到合法取值，非法项直接丢弃（不阻断整体解析）；
- 模型可能返回多余字段或缺省字段，统一以宽松但受控的方式归一化。

对应四类能力：
- LLMCaseJudgement    能力二：侦查研判建议（涉诈类型判定 + 依据支撑链 + 侦查指引 + 追问）
- LLMExtractionResult 能力三：五流要素抽取（正则 + LLM 融合的 LLM 侧候选）
- LLMParseResult      能力四：历史笔录解析导入（问答对 + 章节归类 + 缺口追问草稿）
"""

import re

from pydantic import BaseModel, Field, field_validator

from app.core.enums import CHAPTER_LABEL, Chapter

# 合法章节取值集合（用于将模型返回的章节回落到合法枚举）
_VALID_CHAPTERS: set[str] = {c.value for c in Chapter}
# 要素编号格式：如 P-01 / F-04 / N-02（字母前缀-两位数字），完整目录校验在服务层完成
_ELEMENT_CODE_RE = re.compile(r"^[A-Z]{1,3}-\d{2,3}$")


def _normalize_chapter(raw: object) -> str:
    """将模型返回的章节值回落到合法 Chapter 枚举；非法时归入"证据补充"兜底章节。"""
    if isinstance(raw, str):
        val = raw.strip()
        # 兼容中文名（如"资金损失"）与英文枚举值（如"fund_loss"）
        if val in _VALID_CHAPTERS:
            return val
        for chapter in Chapter:
            if CHAPTER_LABEL.get(chapter) == val:
                return chapter.value
        lowered = val.lower()
        if lowered in _VALID_CHAPTERS:
            return lowered
    return Chapter.EVIDENCE_SUPPLEMENT.value


def _as_str_list(raw: object) -> list[str]:
    """将任意输入规整为去空的字符串列表（容忍模型返回单字符串或 None）。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if x is not None and str(x).strip()]
    return []


class LLMCaseJudgement(BaseModel):
    """能力二：侦查研判结构化输出。

    字段对应需求文档 8.3 AI 侦查研判指引报告：涉诈类型判定结论、判定依据支撑链、
    嫌疑人画像、资金链拦截、后续补充侦查，以及推荐补充追问问题。
    """

    case_type: str = Field(default="", description="涉诈类型判定结论（应为 19 类案由之一或通用）")
    confidence: float = Field(default=0.0, description="判定置信度 0~1")
    basis: list[str] = Field(default_factory=list, description="判定依据支撑链（事实特征描述）")
    fact_features: list[str] = Field(default_factory=list, description="提取的事实特征描述")
    suspect_profile: str | None = Field(default=None, description="嫌疑人画像推断")
    fund_interception: str | None = Field(default=None, description="下游资金链拦截建议")
    followup_investigation: str | None = Field(default=None, description="后续补充侦查指引")
    followup_questions: list[str] = Field(default_factory=list, description="推荐补充追问问题")

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: object) -> float:
        """置信度容错：非法值归零，越界裁剪到 [0,1]。"""
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    @field_validator("basis", "fact_features", "followup_questions", mode="before")
    @classmethod
    def _normalize_lists(cls, v: object) -> list[str]:
        """列表字段容错归一化。"""
        return _as_str_list(v)

    @field_validator("case_type", mode="before")
    @classmethod
    def _strip_case_type(cls, v: object) -> str:
        return v.strip() if isinstance(v, str) else ""


class LLMExtractionItem(BaseModel):
    """能力三：单条五流要素抽取候选（LLM 侧）。"""

    element_code: str = Field(description="五流要素编号（如 F-04），需在定义目录内")
    value: str = Field(default="", description="抽取到的要素值")
    evidence_snippet: str | None = Field(default=None, description="证据摘要片段（原文出处）")
    confidence: float = Field(default=0.6, description="抽取置信度 0~1")

    @field_validator("element_code", mode="before")
    @classmethod
    def _normalize_code(cls, v: object) -> str:
        """要素编号规整为大写并去除空白；非法格式在服务层进一步过滤。"""
        return v.strip().upper() if isinstance(v, str) else ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: object) -> float:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.6
        return max(0.0, min(1.0, f))


class LLMExtractionResult(BaseModel):
    """能力三：五流要素抽取结构化输出（仅保留编号合法、值非空的项）。"""

    items: list[LLMExtractionItem] = Field(default_factory=list, description="抽取到的要素项")

    @field_validator("items", mode="after")
    @classmethod
    def _drop_invalid(cls, items: list[LLMExtractionItem]) -> list[LLMExtractionItem]:
        """丢弃编号格式非法或值为空的项（完整目录校验在服务层结合定义表完成）。"""
        return [it for it in items if _ELEMENT_CODE_RE.match(it.element_code) and it.value.strip()]


class LLMParsedQA(BaseModel):
    """能力四：单组解析出的问答对（含章节归类）。"""

    question: str = Field(description="问题内容")
    answer: str | None = Field(default=None, description="答案内容")
    chapter: str = Field(default=Chapter.EVIDENCE_SUPPLEMENT.value, description="归类的大纲章节")

    @field_validator("chapter", mode="before")
    @classmethod
    def _fallback_chapter(cls, v: object) -> str:
        """章节回落到合法枚举，非法值归入证据补充章节。"""
        return _normalize_chapter(v)


class LLMParseResult(BaseModel):
    """能力四：历史笔录解析结构化输出（问答对 + 缺口追问草稿）。"""

    qa: list[LLMParsedQA] = Field(default_factory=list, description="解析出的问答对")
    followup_draft: list[str] = Field(default_factory=list, description="缺口追问草稿问题")

    @field_validator("qa", mode="after")
    @classmethod
    def _drop_empty_questions(cls, qa: list[LLMParsedQA]) -> list[LLMParsedQA]:
        """丢弃问题为空的问答对。"""
        return [item for item in qa if item.question and item.question.strip()]

    @field_validator("followup_draft", mode="before")
    @classmethod
    def _normalize_draft(cls, v: object) -> list[str]:
        return _as_str_list(v)
