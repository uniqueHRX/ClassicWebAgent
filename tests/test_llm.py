"""LLMClient 测试 —— 单元测试（mock）+ 集成测试（真实 API）。

---
【调用方法】
---

  # 单元测试（无需 API key）
  poetry run python -m pytest tests/test_llm.py -v

  # 按类别筛选
  poetry run python -m pytest tests/test_llm.py -v -k "Init or Chat or Retry"

  # 集成测试（需 .env.test 中配置 LLM_* / VLM_*）
  poetry run python -m pytest tests/test_llm.py -v -m integration

  # 跳过集成测试（只跑 mock）
  poetry run python -m pytest tests/test_llm.py -v -k "not integration"


【测试结构】
---

| 类 | 类型 | 数 | 说明 |
| TestLLMClientInit | 单元 | 8 | 构造参数、环境变量、配置校验 |
| TestLLMClientChat | 单元 | 6 | ChatResponse 返回值、消息传递 |
| TestLLMClientRetry | 单元 | 4 | RateLimit/Timeout/APIError 重试 |
| TestLLMClientIntegration | 集成 | 2 | 真实 LLM+VLM（需 .env.test 配置，默认跳过） |
---
"""

import base64
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import logging
from dotenv import load_dotenv
from openai import APIError, APITimeoutError, RateLimitError

from classic_web_agent.llm import LLMClient, LLMConfigError, ChatResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_env_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """设置 LLM 模式所需的环境变量。"""
    monkeypatch.setenv("LLM_API_KEY", "test-llm-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("LLM_MODEL_NAME", "test-llm-model")


@pytest.fixture
def mock_env_vlm(monkeypatch: pytest.MonkeyPatch) -> None:
    """设置 VLM 模式所需的环境变量。"""
    monkeypatch.setenv("VLM_API_KEY", "test-vlm-key")
    monkeypatch.setenv("VLM_BASE_URL", "https://vlm.example.com/v1")
    monkeypatch.setenv("VLM_MODEL_NAME", "test-vlm-model")


# ── 单元测试：构造与配置 ────────────────────────────────────────────────

class TestLLMClientInit:
    """LLMClient 初始化与配置验证。"""

    def test_llm_mode_from_env(self, mock_env_llm: None) -> None:
        """LLM 模式从环境变量读取配置。"""
        client = LLMClient(mode="llm")
        assert client.mode == "llm"
        assert client.api_key == "test-llm-key"
        assert client.base_url == "https://api.example.com/v1"
        assert client.model_name == "test-llm-model"

    def test_vlm_mode_from_env(self, mock_env_vlm: None) -> None:
        """VLM 模式从环境变量读取配置。"""
        client = LLMClient(mode="vlm")
        assert client.mode == "vlm"
        assert client.api_key == "test-vlm-key"
        assert client.base_url == "https://vlm.example.com/v1"
        assert client.model_name == "test-vlm-model"

    def test_constructor_overrides_env(self, mock_env_llm: None) -> None:
        """构造参数优先级高于环境变量。"""
        client = LLMClient(
            mode="llm",
            api_key="override-key",
            base_url="https://override.com/v1",
            model_name="override-model",
        )
        assert client.api_key == "override-key"
        assert client.base_url == "https://override.com/v1"
        assert client.model_name == "override-model"

    def test_missing_api_key_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺少 API_KEY 时抛出 LLMConfigError（需清除环境变量）。"""
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        monkeypatch.delenv("VLM_API_KEY", raising=False)
        with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
            LLMClient(
                mode="llm",
                api_key="",
                base_url="https://example.com",
                model_name="test",
            )

    def test_missing_base_url_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺少 BASE_URL 时抛出 LLMConfigError（需清除环境变量）。"""
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("VLM_BASE_URL", raising=False)
        with pytest.raises(LLMConfigError, match="LLM_BASE_URL"):
            LLMClient(
                mode="llm",
                api_key="key",
                base_url="",
                model_name="test",
            )

    def test_missing_model_name_raises_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺少 MODEL_NAME 时抛出 LLMConfigError（需清除环境变量）。"""
        monkeypatch.delenv("LLM_MODEL_NAME", raising=False)
        monkeypatch.delenv("VLM_MODEL_NAME", raising=False)
        with pytest.raises(LLMConfigError, match="LLM_MODEL_NAME"):
            LLMClient(
                mode="llm",
                api_key="key",
                base_url="https://example.com",
                model_name="",
            )

    def test_invalid_mode_raises_error(self) -> None:
        """非法的 mode 值抛出 LLMConfigError。"""
        with pytest.raises(LLMConfigError, match="mode 必须是"):
            LLMClient(
                mode="invalid",
                api_key="key",
                base_url="https://example.com",
                model_name="test",
            )

    def test_base_url_trailing_slash_stripped(
        self, mock_env_llm: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """base_url 末尾斜杠被自动去掉。"""
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1/")
        client = LLMClient(mode="llm")
        assert client.base_url == "https://api.example.com/v1"


# ── 单元测试：chat 调用 ─────────────────────────────────────────────────

class TestLLMClientChat:
    """chat() 方法的 mock 测试。"""

    def test_chat_returns_chat_response(self, mock_env_llm: None) -> None:
        """chat() 返回 ChatResponse 对象。"""
        with patch(
            "classic_web_agent.llm.OpenAI",
            return_value=self._make_openai("hello", ""),
        ):
            client = LLMClient(mode="llm")
            resp = client.chat([{"role": "user", "content": "Hello"}])
            assert isinstance(resp, ChatResponse)
            assert resp.content == "hello"
            assert resp.reasoning == ""

    def test_chat_with_reasoning(self, mock_env_llm: None) -> None:
        """ChatResponse 包含 reasoning 字段。"""
        with patch(
            "classic_web_agent.llm.OpenAI",
            return_value=self._make_openai("answer", "thinking step by step..."),
        ):
            client = LLMClient(mode="llm")
            resp = client.chat([{"role": "user", "content": "think"}])
            assert resp.content == "answer"
            assert resp.reasoning == "thinking step by step..."

    def test_chat_passes_messages_to_api(self, mock_env_llm: None) -> None:
        """chat() 传递的 messages 参数正确到达 API。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_raw_response("ok", "")
        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm")
            messages = [{"role": "user", "content": "test"}]
            client.chat(messages, temperature=0.5, max_tokens=100)

            mock_client.chat.completions.create.assert_called_once()
            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["messages"] == messages
            assert call_kwargs["temperature"] == 0.5
            assert call_kwargs["max_tokens"] == 100
            assert call_kwargs["model"] == "test-llm-model"

    def test_chat_response_format(self, mock_env_llm: None) -> None:
        """response_format 参数透传给 API。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_raw_response('{"key": "val"}', "")
        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm")
            fmt = {"type": "json_object"}
            client.chat([{"role": "user", "content": "give json"}], response_format=fmt)

            call_kwargs = mock_client.chat.completions.create.call_args.kwargs
            assert call_kwargs["response_format"] == fmt

    def test_chat_empty_content(self, mock_env_llm: None) -> None:
        """API 返回 None/空内容时返回空字符串。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._make_raw_response(None, "")
        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm")
            resp = client.chat([{"role": "user", "content": "test"}])
            assert resp.content == ""

    def test_vlm_chat_works_same_as_llm(self, mock_env_vlm: None) -> None:
        """VLM 模式的 chat() 调用原理同 LLM，仅配置不同。"""
        with patch(
            "classic_web_agent.llm.OpenAI",
            return_value=self._make_openai("vlm response", ""),
        ):
            client = LLMClient(mode="vlm")
            resp = client.chat([
                {"role": "user", "content": [
                    {"type": "text", "text": "描述页面"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
                ]},
            ])
            assert resp.content == "vlm response"

    @staticmethod
    def _make_openai(content: str, reasoning: str) -> MagicMock:
        """创建返回指定内容的 mock OpenAI 客户端。"""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = TestLLMClientChat._make_raw_response(content, reasoning)
        return mock_client

    @staticmethod
    def _make_raw_response(content: str | None, reasoning: str) -> MagicMock:
        """创建模拟的 API 原始响应。"""
        resp = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        choice.message.reasoning_content = reasoning
        resp.choices = [choice]
        resp.usage = MagicMock()
        resp.usage.total_tokens = 10
        return resp


# ── 单元测试：重试逻辑 ─────────────────────────────────────────────────

class TestLLMClientRetry:
    """重试逻辑测试 —— 各类 API 错误的重试行为。"""

    def test_retry_on_rate_limit(self, mock_env_llm: None) -> None:
        """RateLimitError 触发重试，最终成功。"""
        mock_client = MagicMock()
        ok_resp = self._make_raw_response("ok", "")
        mock_client.chat.completions.create = self._make_side_effect(
            [RateLimitError("rate limited", response=MagicMock(), body=None)] * 2  # type: ignore[arg-type]
            + [ok_resp]
        )

        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm", max_retries=3)
            resp = client.chat([{"role": "user", "content": "hi"}])
            assert resp.content == "ok"
            assert mock_client.chat.completions.create.call_count == 3

    def test_retry_on_timeout(self, mock_env_llm: None) -> None:
        """APITimeoutError 触发重试，最终成功。"""
        mock_client = MagicMock()
        ok_resp = self._make_raw_response("ok", "")
        mock_client.chat.completions.create = self._make_side_effect(
            [APITimeoutError("timeout")] * 2  # type: ignore[arg-type]
            + [ok_resp]
        )

        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm", max_retries=3)
            resp = client.chat([{"role": "user", "content": "hi"}])
            assert resp.content == "ok"
            assert mock_client.chat.completions.create.call_count == 3

    def test_retry_on_api_error(self, mock_env_llm: None) -> None:
        """APIError（5xx）触发重试，最终成功。"""
        mock_client = MagicMock()
        api_err = APIError("server error", request=MagicMock(), body=None)
        ok_resp = self._make_raw_response("ok", "")
        mock_client.chat.completions.create = self._make_side_effect(
            [api_err] * 2 + [ok_resp]
        )

        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm", max_retries=3)
            resp = client.chat([{"role": "user", "content": "hi"}])
            assert resp.content == "ok"
            assert mock_client.chat.completions.create.call_count == 3

    def test_retry_exhausted_raises(self, mock_env_llm: None) -> None:
        """重试耗尽时抛出最终异常。"""
        mock_client = MagicMock()
        api_err = APIError("always fail", request=MagicMock(), body=None)
        api_err.status_code = 500
        mock_client.chat.completions.create = self._make_side_effect([api_err] * 5)

        with patch("classic_web_agent.llm.OpenAI", return_value=mock_client):
            client = LLMClient(mode="llm", max_retries=3)
            with pytest.raises(APIError, match="always fail"):
                client.chat([{"role": "user", "content": "hi"}])
            assert mock_client.chat.completions.create.call_count == 3

    @staticmethod
    def _make_side_effect(items: list[Any]) -> MagicMock:
        mock = MagicMock()
        mock.side_effect = items
        return mock

    @staticmethod
    def _make_raw_response(content: str | None, reasoning: str) -> MagicMock:
        resp = MagicMock()
        choice = MagicMock()
        choice.message.content = content
        choice.message.reasoning_content = reasoning
        resp.choices = [choice]
        resp.usage = MagicMock()
        resp.usage.total_tokens = 5
        return resp


# ── 集成测试：真实 API 调用（需要配置环境变量）─────────────────────────

@pytest.mark.integration
class TestLLMClientIntegration:
    """集成测试 —— 需要真实 API 配置（.env.test），默认跳过。

    包含 2 个测试：
    - test_llm_chat: LLM 文本，prompt 来自 LLM_TEST_PROMPT
    - test_vlm_chat: VLM 视觉（含图片），prompt/图片路径来自环境变量
    """

    @pytest.fixture(autouse=True)
    def load_env_and_check(self) -> None:
        """检查 LLM_API_KEY 是否就绪（.env.test 由 conftest 自动加载）。"""
        if not os.getenv("LLM_API_KEY"):
            pytest.skip("LLM_API_KEY 未设置，跳过 LLM 集成测试")

    def test_llm_chat(self) -> None:
        """LLM 文本集成测试 —— prompt 来自环境变量 LLM_TEST_PROMPT。"""
        prompt = os.getenv("LLM_TEST_PROMPT", "用一句话介绍你自己")
        client = LLMClient(mode="llm")
        resp = client.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=10000,
        )
        logger.info("\n\n[LLM推理过程]\n%s", resp.reasoning or "(无)")
        logger.info("\n\n[LLM响应内容]\n%s", resp.content)
        assert isinstance(resp, ChatResponse)
        assert len(resp.content) > 0

    def test_vlm_chat(self) -> None:
        """VLM 视觉集成测试 —— prompt + 图片路径来自环境变量。"""
        if not os.getenv("VLM_API_KEY"):
            pytest.skip("VLM_API_KEY 未设置，跳过 VLM 集成测试")

        prompt = os.getenv("VLM_TEST_PROMPT", "请用中文描述这张图片的内容")
        image_path = os.getenv("VLM_TEST_IMAGE", "")

        if not image_path or not os.path.exists(image_path):
            pytest.skip(f"VLM 测试图片不存在: {image_path}")

        with open(image_path, "rb") as f:
            img_data = f.read()
        b64 = base64.b64encode(img_data).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64}"

        client = LLMClient(mode="vlm")
        resp = client.chat(
            [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            temperature=0.1,
            max_tokens=10000,
        )
        logger.info("\n\n[VLM推理过程]\n%s", resp.reasoning or "(无)")
        logger.info("\n\n[VLM响应内容]\n%s", resp.content)
        assert isinstance(resp, ChatResponse)
        assert len(resp.content) > 0
