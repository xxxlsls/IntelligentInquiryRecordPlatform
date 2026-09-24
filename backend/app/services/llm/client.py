"""
LLM HTTP 客户端（大模型私有化接入 · 传输层）

职责：以 OpenAI 兼容 HTTP 协议与内网推理服务（Ollama / vLLM / Xinference）通信，
仅依赖 httpx，不引入任何厂商 SDK。核心特性：
- 模块级懒加载单例，复用 httpx.Client 连接池（避免频繁握手，降低问询交互延迟）；
- 统一超时/重试策略，取自 settings；
- 任何失败（超时、连接错误、非 2xx、JSON 解析失败）统一抛 LLMUnavailableError，
  由业务层捕获后降级到规则算法（复用 is_degraded / is_timeout 标识）；
- 未启用（LLM_ENABLED=False）时任何调用立即抛 LLMUnavailableError，保证零行为变化。
"""

import json
import logging
import re
import threading

import httpx

from app.core.config import settings

logger = logging.getLogger("app.llm")

# 剥离模型可能包裹的 Markdown 代码块围栏（```json ... ```）
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class LLMUnavailableError(Exception):
    """LLM 不可用信号异常。

    业务层捕获此异常即触发降级到规则算法链路（超时/连接失败/未启用/解析失败统一归因）。
    """


class LLMClient:
    """OpenAI 兼容 HTTP 客户端（懒加载单例，复用连接池）。"""

    def __init__(self) -> None:
        # 基础地址去除末尾斜杠，便于拼接子路径
        self._base_url = settings.LLM_BASE_URL.rstrip("/")
        self._api_key = settings.LLM_API_KEY
        self._chat_model = settings.LLM_CHAT_MODEL
        self._embedding_model = settings.LLM_EMBEDDING_MODEL
        self._timeout = settings.LLM_TIMEOUT_SECONDS
        self._max_retries = max(0, settings.LLM_MAX_RETRIES)
        self._temperature = settings.LLM_TEMPERATURE
        # httpx.Client 连接池（延迟创建，首次调用时初始化）
        self._http: httpx.Client | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """LLM 总开关是否开启。"""
        return bool(settings.LLM_ENABLED)

    def _client(self) -> httpx.Client:
        """获取（并惰性创建）复用的 httpx.Client 连接池。"""
        if self._http is None:
            with self._lock:
                if self._http is None:
                    self._http = httpx.Client(
                        base_url=self._base_url,
                        timeout=self._timeout,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                    )
        return self._http

    def _ensure_enabled(self) -> None:
        """未启用时立即抛降级信号，避免任何网络调用。"""
        if not self.enabled:
            raise LLMUnavailableError("LLM 未启用（LLM_ENABLED=False）")

    def _post_json(self, path: str, payload: dict) -> dict:
        """带重试的 POST 请求，返回解析后的 JSON；任何失败抛 LLMUnavailableError。"""
        client = self._client()
        attempts = self._max_retries + 1
        last_err: str = ""
        for i in range(attempts):
            try:
                resp = client.post(path, json=payload)
                if resp.status_code // 100 != 2:
                    last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    # 4xx 通常为请求本身问题，重试无意义，直接降级
                    if resp.status_code // 100 == 4:
                        raise LLMUnavailableError(f"LLM 接口返回错误 {last_err}")
                    continue
                return resp.json()
            except LLMUnavailableError:
                raise
            except httpx.TimeoutException as exc:
                last_err = f"请求超时：{exc}"
            except httpx.HTTPError as exc:
                last_err = f"连接错误：{exc}"
            except ValueError as exc:  # resp.json() 解析失败
                raise LLMUnavailableError(f"LLM 响应非合法 JSON：{exc}") from exc
            logger.warning("LLM 请求 %s 第 %d/%d 次失败：%s", path, i + 1, attempts, last_err)
        raise LLMUnavailableError(f"LLM 请求失败（已重试 {self._max_retries} 次）：{last_err}")

    @staticmethod
    def _strip_fence(text: str) -> str:
        """剥离模型输出可能包裹的代码块围栏与首尾空白。"""
        cleaned = text.strip()
        cleaned = _CODE_FENCE_RE.sub("", cleaned).strip()
        return cleaned

    # ------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------
    def chat_json(self, messages: list[dict], temperature: float | None = None) -> dict:
        """请求 chat/completions 并返回解析后的 JSON 对象。

        强制 response_format={"type":"json_object"}；超时/连接错误/非 2xx/JSON 解析失败
        统一抛 LLMUnavailableError 触发降级。

        :param messages: OpenAI messages 结构
        :param temperature: 生成温度（默认取 settings.LLM_TEMPERATURE）
        :return: 模型输出的 JSON（已解析为 dict）
        """
        self._ensure_enabled()
        payload = {
            "model": self._chat_model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        data = self._post_json("/chat/completions", payload)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM 响应结构异常：{exc}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMUnavailableError("LLM 返回内容为空")
        try:
            parsed = json.loads(self._strip_fence(content))
        except json.JSONDecodeError as exc:
            raise LLMUnavailableError(f"LLM 输出非合法 JSON：{exc}") from exc
        if not isinstance(parsed, dict):
            raise LLMUnavailableError("LLM 输出 JSON 非对象结构")
        return parsed

    def embed(self, texts: list[str]) -> list[list[float]]:
        """请求 embeddings，返回文本向量列表（顺序与输入一致）。"""
        self._ensure_enabled()
        if not texts:
            return []
        payload = {"model": self._embedding_model, "input": texts}
        data = self._post_json("/embeddings", payload)
        try:
            items = sorted(data["data"], key=lambda d: d.get("index", 0))
            vectors = [list(map(float, it["embedding"])) for it in items]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMUnavailableError(f"LLM 向量响应结构异常：{exc}") from exc
        if len(vectors) != len(texts):
            raise LLMUnavailableError("LLM 向量数量与输入不一致")
        return vectors

    def ping(self) -> bool:
        """探活：优先 GET /models，失败则视为不可达（供状态接口使用，不抛异常）。"""
        if not self.enabled:
            return False
        try:
            client = self._client()
            resp = client.get("/models")
            return resp.status_code // 100 == 2
        except httpx.HTTPError as exc:
            logger.info("LLM 探活失败：%s", exc)
            return False

    def close(self) -> None:
        """关闭连接池（应用退出时调用，释放底层 socket）。"""
        if self._http is not None:
            try:
                self._http.close()
            finally:
                self._http = None


# ------------------------------------------------------------
# 模块级懒加载单例
# ------------------------------------------------------------
_singleton: LLMClient | None = None
_singleton_lock = threading.Lock()


def get_llm_client() -> LLMClient:
    """获取 LLMClient 模块级单例（懒加载，线程安全）。"""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = LLMClient()
    return _singleton
