"""LLM/VLM 客户端 —— OpenAI 兼容 API 调用封装。

支持 LLM（文本推理）和 VLM（视觉感知）双模式。
图片编码由调用方处理，本模块不做任何编码类工作。

用法:
    # LLM 模式（文本推理）
    llm = LLMClient(mode="llm")
    resp = llm.chat([{"role": "user", "content": "你好"}])

    # VLM 模式（视觉感知，图片由调用方构造为 content part）
    vlm = LLMClient(mode="vlm")
    resp = vlm.chat([
        {"role": "user", "content": [
            {"type": "text", "text": "描述这个页面"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
        ]},
    ])
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from classic_web_agent.config import load_config

logger = logging.getLogger(__name__)


class LLMConfigError(Exception):
    """LLM 配置错误 —— API 密钥、端点或模型名称缺失。"""
    pass


@dataclass
class ChatResponse:
    """对话调用结果。

    Attributes:
        content: 模型生成的文本回复。
        reasoning: 模型推理过程（如 DeepSeek-R1 的 reasoning_content），
            非 reasoning 模型返回空字符串。
    """
    content: str
    reasoning: str = ""


class LLMClient:
    """OpenAI 兼容 API 客户端，支持 LLM/VLM 双模式。

    配置来源（优先级）：构造参数 > 环境变量（LLM_* / VLM_*）。

    Attributes:
        mode: "llm" 或 "vlm"
        model_name: 当前使用的模型名称
    """

    def __init__(
        self,
        mode: str = "llm",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        max_retries: int = 3,
        timeout: int = 180,
    ) -> None:
        """初始化 LLM/VLM 客户端。

        Args:
            mode: "llm"（文本推理）或 "vlm"（视觉感知）。
            api_key: API 密钥。默认读取 LLM_API_KEY 或 VLM_API_KEY 环境变量。
            base_url: API 端点。默认读取 LLM_BASE_URL 或 VLM_BASE_URL 环境变量。
            model_name: 模型名称。默认读取 LLM_MODEL_NAME 或 VLM_MODEL_NAME 环境变量。
            max_retries: 失败重试次数（默认 3）。
            timeout: 请求超时秒数（默认 60）。

        Raises:
            LLMConfigError: 缺少必要配置项。
        """
        self.mode = mode.lower()
        if self.mode not in ("llm", "vlm"):
            raise LLMConfigError(
                f"mode 必须是 'llm' 或 'vlm'，收到 '{mode}'"
            )

        prefix = self.mode.upper()

        self.api_key = api_key or os.getenv(f"{prefix}_API_KEY") or ""
        self.base_url = (base_url or os.getenv(f"{prefix}_BASE_URL") or "").rstrip("/")
        self.model_name = model_name or os.getenv(f"{prefix}_MODEL_NAME") or ""
        self.max_retries = max_retries
        self.timeout = timeout

        # 验证配置完整性
        missing = []
        if not self.api_key:
            missing.append(f"{prefix}_API_KEY")
        if not self.base_url:
            missing.append(f"{prefix}_BASE_URL")
        if not self.model_name:
            missing.append(f"{prefix}_MODEL_NAME")
        if missing:
            raise LLMConfigError(
                f"LLMClient[{self.mode}] 缺少必要配置："
                f"{', '.join(missing)}。"
                f"请设置环境变量或传入构造参数。"
            )

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,
        )

        logger.info(
            "LLMClient[%s] 初始化完成 model=%s base_url=%s",
            self.mode, self.model_name, self.base_url,
        )

    # ── 公开 API ────────────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """对话调用 —— 传入消息上下文，返回模型回复（含 reasoning）。

        Args:
            messages: OpenAI 格式消息列表。VLM 模式时由调用方
                在 content 中构造 text + image_url 等 multi-part 内容。
            temperature: 采样温度（默认 0.7）。
            max_tokens: 最大输出 token 数。
            response_format: 结构化输出格式，如 {"type": "json_object"}。
            **kwargs: 透传给 OpenAI API 的额外参数。

        Returns:
            ChatResponse 对象，包含 content（回复）和 reasoning（推理过程）。

        Raises:
            APIError: API 返回错误（重试耗尽后）。
        """
        return self._call(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **kwargs,
        )

    # ── 内部方法 ────────────────────────────────────────────────────────

    def _call(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """统一的 API 调用入口，带指数退避重试逻辑。"""
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    timeout=self.timeout,
                    **kwargs,
                )
                choice = response.choices[0].message
                content = choice.content or ""
                reasoning = getattr(choice, "reasoning_content", None) or ""
                logger.debug(
                    "LLMClient[%s] 调用成功 tokens=%s reasoning=%s",
                    self.mode,
                    response.usage.total_tokens if response.usage else None,
                    "yes" if reasoning else "no",
                )
                return ChatResponse(content=content, reasoning=reasoning)

            except RateLimitError as e:
                last_error = e
                wait = min(2**attempt * 2, 30)  # 4s, 8s, 16s, 上限 30s
                logger.warning(
                    "速率限制（尝试 %d/%d），等待 %ds 后重试...",
                    attempt, self.max_retries, wait,
                )
                time.sleep(wait)

            except APITimeoutError as e:
                last_error = e
                logger.warning(
                    "请求超时（尝试 %d/%d）...",
                    attempt, self.max_retries,
                )
                if attempt < self.max_retries:
                    time.sleep(1)

            except APIError as e:
                last_error = e
                logger.error(
                    "API 错误（尝试 %d/%d）：status=%s %s",
                    attempt, self.max_retries,
                    getattr(e, "status_code", "N/A"),
                    e.message or str(e),
                )
                if attempt < self.max_retries:
                    time.sleep(1)

        # 所有重试耗尽
        logger.error(
            "LLMClient[%s] 调用失败，已耗尽 %d 次重试：%s",
            self.mode, self.max_retries, last_error,
        )
        raise last_error  # type: ignore[misc]
