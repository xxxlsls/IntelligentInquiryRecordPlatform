"""
大模型私有化接入基础设施层（app.services.llm）

以 OpenAI 兼容 HTTP 接口接入内网私有化部署的大模型（Ollama / vLLM / Xinference），
仅依赖 httpx，不引入任何厂商 SDK。核心设计：
- LLM 为主，超时/异常/未启用时自动降级到既有规则算法（复用 is_degraded/is_timeout）；
- LLM_ENABLED=False（默认）时零行为变化，全部能力走规则链路；
- 分能力开关，可单独降级语义匹配/研判/抽取/导入解析任一能力。

对外导出：
- LLMClient / get_llm_client  传输层客户端与懒加载单例
- LLMService                  业务门面（各业务服务注入）
- LLMUnavailableError         降级信号异常
- LLMCaseJudgement / LLMExtractionResult / LLMParseResult  结构化输出校验模型
"""

from app.services.llm.client import LLMClient, LLMUnavailableError, get_llm_client
from app.services.llm.schemas import (
    LLMCaseJudgement,
    LLMExtractionItem,
    LLMExtractionResult,
    LLMParsedQA,
    LLMParseResult,
)
from app.services.llm.service import LLMService

__all__ = [
    "LLMClient",
    "get_llm_client",
    "LLMUnavailableError",
    "LLMService",
    "LLMCaseJudgement",
    "LLMExtractionResult",
    "LLMExtractionItem",
    "LLMParseResult",
    "LLMParsedQA",
]
