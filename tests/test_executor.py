"""Executor 测试 —— 单元测试（mock）+ 集成测试（真实浏览器）。"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from classic_web_agent.common.action import ActionSpace
from classic_web_agent.subagent.executor import Executor
from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import Action, ActionResult

logger = logging.getLogger(__name__)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def executor_no_browser() -> Executor:
    """无浏览器的 Executor（测试内部动作和参数校验）。"""
    return Executor(action_space=ActionSpace(), browser=None, memory=Memory())


@pytest.fixture
def mock_browser() -> MagicMock:
    """Mock 的 Browser 实例。"""
    br = MagicMock()
    br._browser = MagicMock()  # _check_browser_ready() 通过
    return br


@pytest.fixture
def empty_memory() -> Memory:
    """空 Memory。"""
    return Memory()


# ══════════════════════════════════════════════════════════════════════════
# 内部动作
# ══════════════════════════════════════════════════════════════════════════


class TestExecutorInternalActions:
    """内部动作（THINK/REMEMBER/RECALL/DONE/FAIL）不需要浏览器。"""

    def test_THINK_stores_to_memory(self, executor_no_browser: Executor) -> None:
        """THINK 将推理内容存入工作记忆。"""
        result = executor_no_browser.execute(
            Action(action_type="THINK", text="当前页面是搜索页")
        )
        assert result.success is True
        memory = executor_no_browser.memory
        assert memory is not None
        entries = memory.get_working()
        assert any("当前页面是搜索页" in e.content for e in entries)
        logger.info("THINK 存入记忆 ✓")

    def test_THINK_empty_text(self, executor_no_browser: Executor) -> None:
        """THINK 无文本也返回成功。"""
        result = executor_no_browser.execute(Action(action_type="THINK"))
        assert result.success is True
        logger.info("THINK 空文本 ✓")

    def test_REMEMBER_stores_key_value(self, executor_no_browser: Executor) -> None:
        """REMEMBER 将 key=value 存入工作记忆。"""
        result = executor_no_browser.execute(
            Action(
                action_type="REMEMBER",
                extra={"key": "price", "value": "2999"},
            )
        )
        assert result.success is True
        assert "price" in result.message
        memory = executor_no_browser.memory
        assert memory is not None
        entries = memory.get_working()
        assert any("price" in e.content and "2999" in e.content for e in entries)
        logger.info("REMEMBER 存入 key=value ✓")

    def test_REMEMBER_missing_key(self, executor_no_browser: Executor) -> None:
        """REMEMBER 缺少 key 时返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="REMEMBER", extra={"value": "test"})
        )
        assert result.success is False
        logger.info("REMEMBER 缺少 key → 失败 ✓")

    def test_RECALL_finds_matching(self, executor_no_browser: Executor) -> None:
        """RECALL 检索到匹配的记忆条目。"""
        # 先存入一条
        executor_no_browser.execute(
            Action(action_type="REMEMBER", extra={"key": "city", "value": "北京"})
        )
        # 再检索
        result = executor_no_browser.execute(
            Action(action_type="RECALL", extra={"query": "city"})
        )
        assert result.success is True
        assert result.data is not None
        assert "北京" in str(result.data)
        logger.info("RECALL 检索匹配 ✓")

    def test_RECALL_no_match(self, executor_no_browser: Executor) -> None:
        """RECALL 无匹配时返回 success=False。"""
        result = executor_no_browser.execute(
            Action(action_type="RECALL", extra={"query": "不存在的内容"})
        )
        assert result.success is False
        logger.info("RECALL 无匹配 ✓")

    def test_RECALL_missing_query(self, executor_no_browser: Executor) -> None:
        """RECALL 缺少 query 时返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="RECALL", extra={})
        )
        assert result.success is False
        logger.info("RECALL 缺少 query → 失败 ✓")

    def test_DONE_returns_success(self, executor_no_browser: Executor) -> None:
        """DONE 返回成功，携带结束文案。"""
        result = executor_no_browser.execute(
            Action(action_type="DONE", text="搜索完成")
        )
        assert result.success is True
        assert "搜索完成" in result.message
        logger.info("DONE ✓")

    def test_FAIL_returns_success(self, executor_no_browser: Executor) -> None:
        """FAIL 返回成功（Executor 层面），携带失败原因。"""
        result = executor_no_browser.execute(
            Action(action_type="FAIL", text="未找到目标元素")
        )
        assert result.success is True
        assert "未找到目标元素" in result.message
        logger.info("FAIL ✓")


# ══════════════════════════════════════════════════════════════════════════
# 外部动作：参数校验（无浏览器）
# ══════════════════════════════════════════════════════════════════════════


class TestExecutorParameterValidation:
    """外部动作的参数缺失校验。"""

    def test_missing_element_id(self, executor_no_browser: Executor) -> None:
        """CLICK/ TYPE/ HOVER 缺少 element_id 返回失败。"""
        for atype in ("CLICK", "TYPE", "HOVER"):
            result = executor_no_browser.execute(Action(action_type=atype))
            assert result.success is False, f"{atype} 应因缺少 element_id 失败"
        logger.info("CLICK/TYPE/HOVER 缺少 element_id 均失败 ✓")

    def test_TYPE_missing_text(self, executor_no_browser: Executor) -> None:
        """TYPE 缺少 text 返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="TYPE", element_id=100)
        )
        assert result.success is False
        logger.info("TYPE 缺少 text → 失败 ✓")

    def test_MOUSE_CLICK_missing_coords(self, executor_no_browser: Executor) -> None:
        """MOUSE_CLICK 缺少坐标返回失败。"""
        result = executor_no_browser.execute(Action(action_type="MOUSE_CLICK"))
        assert result.success is False
        logger.info("MOUSE_CLICK 缺少坐标 → 失败 ✓")

    def test_GOTO_missing_url(self, executor_no_browser: Executor) -> None:
        """GOTO 缺少 url 返回失败。"""
        result = executor_no_browser.execute(Action(action_type="GOTO"))
        assert result.success is False
        logger.info("GOTO 缺少 url → 失败 ✓")

    def test_PRESS_missing_key(self, executor_no_browser: Executor) -> None:
        """PRESS 缺少 key 返回失败。"""
        result = executor_no_browser.execute(Action(action_type="PRESS"))
        assert result.success is False
        logger.info("PRESS 缺少 key → 失败 ✓")

    def test_SCROLL_invalid_direction(self, executor_no_browser: Executor) -> None:
        """SCROLL 非法的 direction 返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="SCROLL", extra={"direction": "left"})
        )
        assert result.success is False
        logger.info("SCROLL 非法 direction → 失败 ✓")

    def test_WAIT_invalid_condition(self, executor_no_browser: Executor) -> None:
        """WAIT 非法的 condition 返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="WAIT", extra={"condition": "invalid"})
        )
        assert result.success is False
        logger.info("WAIT 非法 condition → 失败 ✓")

    def test_SWITCH_TAB_missing_index(self, executor_no_browser: Executor) -> None:
        """SWITCH_TAB 缺少 tab_index 返回失败。"""
        result = executor_no_browser.execute(Action(action_type="SWITCH_TAB"))
        assert result.success is False
        logger.info("SWITCH_TAB 缺少 tab_index → 失败 ✓")

    def test_FIND_missing_text(self, executor_no_browser: Executor) -> None:
        """FIND 缺少 text 返回失败。"""
        result = executor_no_browser.execute(Action(action_type="FIND"))
        assert result.success is False
        logger.info("FIND 缺少 text → 失败 ✓")

    def test_unknown_action(self, executor_no_browser: Executor) -> None:
        """未知动作类型返回失败。"""
        result = executor_no_browser.execute(Action(action_type="UNKNOWN"))
        assert result.success is False
        logger.info("未知动作类型 → 失败 ✓")

    def test_no_browser_external(self, executor_no_browser: Executor) -> None:
        """浏览器未启动时外部动作返回失败。"""
        result = executor_no_browser.execute(
            Action(action_type="CLICK", element_id=100)
        )
        assert result.success is False
        assert "浏览器未启动" in result.message
        logger.info("浏览器未启动 → 失败 ✓")


# ══════════════════════════════════════════════════════════════════════════
# 外部动作：Mock 浏览器验证正确转发
# ══════════════════════════════════════════════════════════════════════════


class TestExecutorWithMockBrowser:
    """Mock 浏览器验证 Executor 正确调用 browser 方法。"""

    def test_CLICK_calls_browser_click(self, mock_browser: MagicMock) -> None:
        """CLICK 调用 browser.click()。"""
        executor = Executor(ActionSpace(), browser=mock_browser)
        result = executor.execute(Action(action_type="CLICK", element_id=100))
        assert result.success is True
        mock_browser.click.assert_called_once_with(100)
        logger.info("CLICK → browser.click(100) ✓")

    def test_TYPE_calls_browser_type(self, mock_browser: MagicMock) -> None:
        """TYPE 调用 browser.type()。"""
        executor = Executor(ActionSpace(), browser=mock_browser)
        result = executor.execute(
            Action(action_type="TYPE", element_id=101, text="你好")
        )
        assert result.success is True
        mock_browser.type.assert_called_once_with(101, "你好")
        logger.info("TYPE → browser.type(101, 你好) ✓")

    def test_GOTO_calls_browser_goto(self, mock_browser: MagicMock) -> None:
        """GOTO 调用 browser.goto()。"""
        executor = Executor(ActionSpace(), browser=mock_browser)
        result = executor.execute(
            Action(action_type="GOTO", extra={"url": "https://example.com"})
        )
        assert result.success is True
        mock_browser.goto.assert_called_once_with("https://example.com")
        logger.info("GOTO → browser.goto(url) ✓")

    def test_SCREENSHOT_returns_data_uri(self, mock_browser: MagicMock) -> None:
        """SCREENSHOT 返回 data URI 在 result.data。"""
        mock_browser.screenshot.return_value = "data:image/png;base64,abc123"
        executor = Executor(ActionSpace(), browser=mock_browser)
        result = executor.execute(Action(action_type="SCREENSHOT"))
        assert result.success is True
        assert result.data == "data:image/png;base64,abc123"
        logger.info("SCREENSHOT → result.data ✓")

    def test_NEW_TAB_returns_index(self, mock_browser: MagicMock) -> None:
        """NEW_TAB 返回新标签页索引。"""
        mock_browser.new_tab.return_value = 3
        executor = Executor(ActionSpace(), browser=mock_browser)
        result = executor.execute(
            Action(action_type="NEW_TAB", extra={"url": "https://example.com"})
        )
        assert result.success is True
        assert result.data == 3
        mock_browser.new_tab.assert_called_once_with("https://example.com")
        logger.info("NEW_TAB → result.data=3 ✓")

    def test_EXTRACT_returns_text(self, mock_browser: MagicMock) -> None:
        """EXTRACT 返回提取的文本。"""
        mock_browser.extract_text.return_value = "页面内容测试"
        executor = Executor(ActionSpace(), browser=mock_browser)
        # element_id in extra
        result = executor.execute(
            Action(action_type="EXTRACT", extra={"element_id": 200})
        )
        assert result.success is True
        assert result.data == "页面内容测试"
        mock_browser.extract_text.assert_called_once()
        logger.info("EXTRACT → result.data ✓")


# ══════════════════════════════════════════════════════════════════════════
# 集成测试：真实浏览器
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    not __import__("tests.conftest", fromlist=["playwright_available"]).playwright_available,
    reason="需要 Playwright 浏览器（安装: playwright install chromium）",
)
@pytest.mark.integration
class TestExecutorIntegration:
    """集成测试 — 需要真实浏览器。"""

    @pytest.fixture(autouse=True)
    def _setup(self, browser: "Browser") -> None:  # type: ignore[name-defined]
        """使用 conftest.py 的 browser fixture。"""
        self.browser = browser
        self.executor = Executor(
            action_space=ActionSpace(),
            browser=browser,
            memory=Memory(),
        )

    def test_goto_and_screenshot(self) -> None:
        """GOTO → SCREENSHOT 返回 data URI。"""
        # GOTO
        r1 = self.executor.execute(
            Action(action_type="GOTO", extra={"url": "https://example.com"})
        )
        assert r1.success is True
        # SCREENSHOT
        r2 = self.executor.execute(Action(action_type="SCREENSHOT"))
        assert r2.success is True
        assert isinstance(r2.data, str)
        assert r2.data.startswith("data:image/png;base64,")
        logger.info("集成: GOTO + SCREENSHOT → data URI ✓")

    def test_extract_text(self) -> None:
        """EXTRACT 提取页面文本。"""
        self.executor.execute(
            Action(action_type="GOTO", extra={"url": "https://example.com"})
        )
        result = self.executor.execute(Action(action_type="EXTRACT"))
        assert result.success is True
        assert isinstance(result.data, str)
        assert len(result.data) > 0
        logger.info("集成: EXTRACT 提取 %d 字符 ✓", len(result.data))

    def test_find_text(self) -> None:
        """FIND 找到/未找到文本。"""
        self.executor.execute(
            Action(action_type="GOTO", extra={"url": "https://example.com"})
        )
        # 存在的文本
        r1 = self.executor.execute(
            Action(action_type="FIND", extra={"text": "Example"})
        )
        assert r1.success is True
        # 不存在的文本
        r2 = self.executor.execute(
            Action(action_type="FIND", extra={"text": "这个文本不存在xyz"})
        )
        assert r2.success is False
        logger.info("集成: FIND 找到/未找到 ✓")

    def test_tab_management(self) -> None:
        """NEW_TAB → SWITCH_TAB → CLOSE_TAB。"""
        r1 = self.executor.execute(Action(action_type="NEW_TAB"))
        assert r1.success is True
        assert isinstance(r1.data, int)
        tab_count = self.browser.tab_count

        r2 = self.executor.execute(
            Action(action_type="SWITCH_TAB", extra={"tab_index": 0})
        )
        assert r2.success is True

        r3 = self.executor.execute(Action(action_type="CLOSE_TAB"))
        assert r3.success is True
        logger.info("集成: NEW_TAB + SWITCH_TAB + CLOSE_TAB ✓")
