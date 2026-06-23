"""Perception 模块单元测试 + 集成测试。

用法：
    # 单元测试（无需浏览器）
    pytest tests/test_perception.py -v

    # 集成测试（有头浏览器，目标 URL 通过 .env.test 配置）
    pytest tests/test_perception.py -v -k "headed"
"""

import logging
import os
from pathlib import Path

import pytest

from classic_web_agent.subagent.perception import (
    Perception,
    EnhancedDOMNode,
    Bounds,
    _is_hidden,
    _is_interactive,
    _serialize,
)
from classic_web_agent.common.types import PageState

logger = logging.getLogger(__name__)


class TestPerceptionBasics:
    """Perception 基础功能测试。"""

    def test_perception_no_browser(self):
        """浏览器未启动时 observe() 应返回空 PageState（含新字段）。"""
        perception = Perception(vlm=None, browser=None)
        state = perception.observe()
        assert isinstance(state, PageState)
        assert state.screenshot == ""
        assert state.url == ""
        assert state.title == ""
        assert state.tree_text == ""
        assert state.current_tab_id == ""
        assert state.tabs_list == ""
        logger.info("空 PageState 验证通过 ✓")


class TestHiddenDetection:
    """隐藏元素判定测试 —— _is_hidden() 6 级判定。"""

    def test_is_hidden_by_attribute(self):
        """HTML hidden 属性应被判定为隐藏。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            attributes={"hidden": "", "class": "test"},
        )
        assert _is_hidden(node) is True
        logger.info("hidden 属性隐藏判定通过 ✓")

    def test_is_hidden_by_aria(self):
        """aria-hidden="true" 应被判定为隐藏。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            attributes={"aria-hidden": "true"},
        )
        assert _is_hidden(node) is True
        logger.info("aria-hidden 隐藏判定通过 ✓")

    def test_is_not_hidden(self):
        """普通可见节点不应被判定为隐藏。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            bounds=Bounds(x=0, y=0, width=100, height=50),
        )
        assert _is_hidden(node) is False
        logger.info("可见节点隐藏判定通过 ✓")

    def test_is_hidden_zero_bounds(self):
        """零宽零高节点应被判定为隐藏。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            bounds=Bounds(x=0, y=0, width=0, height=0),
        )
        assert _is_hidden(node) is True
        logger.info("零宽零高隐藏判定通过 ✓")


class TestInteractiveDetection:
    """可交互元素检测测试 —— _is_interactive() 5 级检测。"""

    def test_is_interactive_button_tag(self):
        """button 标签应被判定为可交互（级别 1）。"""
        node = EnhancedDOMNode(node_type=1, tag_name="button")
        assert _is_interactive(node) is True
        logger.info("button 标签交互判定通过 ✓")

    def test_is_interactive_input_tag(self):
        """input 标签应被判定为可交互（级别 1）。"""
        node = EnhancedDOMNode(node_type=1, tag_name="input")
        assert _is_interactive(node) is True
        logger.info("input 标签交互判定通过 ✓")

    def test_is_interactive_a_tag(self):
        """a 标签应被判定为可交互（级别 1）。"""
        node = EnhancedDOMNode(node_type=1, tag_name="a")
        assert _is_interactive(node) is True
        logger.info("a 标签交互判定通过 ✓")

    def test_is_interactive_by_role(self):
        """AX role 为 button 的 div 应被判定为可交互（级别 2）。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            ax_role="button",
        )
        assert _is_interactive(node) is True
        logger.info("AX role 交互判定通过 ✓")

    def test_is_interactive_by_event(self):
        """含 onclick 属性的 div 应被判定为可交互（级别 3）。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            attributes={"onclick": "submit()"},
        )
        assert _is_interactive(node) is True
        logger.info("onclick 事件交互判定通过 ✓")

    def test_is_interactive_by_tabindex(self):
        """含 tabindex 属性的 div 应被判定为可交互（级别 3）。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            attributes={"tabindex": "0"},
        )
        assert _is_interactive(node) is True
        logger.info("tabindex 交互判定通过 ✓")

    def test_is_not_interactive(self):
        """纯展示 div 不应被判定为可交互。"""
        node = EnhancedDOMNode(node_type=1, tag_name="div")
        assert _is_interactive(node) is False
        logger.info("纯展示 div 非交互判定通过 ✓")


class TestSerialize:
    """序列化测试 —— _serialize() 递归序列化。"""

    def test_serialize_text_node(self):
        """文本节点应输出缩进 + 文本内容。"""
        node = EnhancedDOMNode(node_type=3, node_value="  Hello World  ")
        result = _serialize(node)
        assert result == "Hello World\n"
        logger.info("文本节点序列化通过 ✓")

    def test_serialize_empty_text(self):
        """空白文本节点应输出空字符串。"""
        node = EnhancedDOMNode(node_type=3, node_value="   \n  ")
        result = _serialize(node)
        assert result == ""
        logger.info("空白文本节点序列化通过 ✓")

    def test_serialize_interactive_element(self):
        """可交互元素节点应输出 [id]<tag attr/> 格式。"""
        node = EnhancedDOMNode(
            backend_node_id=123,
            node_type=1,
            tag_name="button",
            attributes={"type": "submit", "class": "btn"},
            is_interactive=True,
            is_disabled=False,
        )
        result = _serialize(node)
        assert "[123]" in result
        assert "<button" in result
        assert "type=submit" in result
        assert "/>" in result
        logger.info("交互元素序列化格式通过 ✓")

    def test_serialize_interactive_with_bounds(self):
        """含坐标的可交互元素应输出 @(x,y,w,h)。"""
        node = EnhancedDOMNode(
            backend_node_id=456,
            node_type=1,
            tag_name="input",
            attributes={"type": "text"},
            bounds=Bounds(x=100, y=200, width=300, height=40),
            is_interactive=True,
            is_disabled=False,
        )
        result = _serialize(node)
        assert "@(100,200,300,40)" in result
        logger.info("坐标序列化格式通过 ✓")

    def test_serialize_hidden_node(self):
        """隐藏节点应输出空字符串。"""
        node = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            is_hidden=True,
        )
        result = _serialize(node)
        assert result == ""
        logger.info("隐藏节点跳过序列化通过 ✓")

    def test_serialize_nested_container(self):
        """嵌套结构应正确处理缩进和容器空行。"""
        text = EnhancedDOMNode(node_type=3, node_value="按钮文本")
        btn = EnhancedDOMNode(
            backend_node_id=1,
            node_type=1,
            tag_name="button",
            attributes={"class": "btn"},
            is_interactive=True,
            is_disabled=False,
            children=[text],
        )
        container = EnhancedDOMNode(
            node_type=1,
            tag_name="div",
            attributes={"class": "wrapper"},
            children=[btn],
        )
        result = _serialize(container).rstrip()
        assert "\t[1]<button class=btn />\n\t\t按钮文本" in result
        logger.info("嵌套容器序列化通过 ✓")


# ═════════════════════════════════════════════════════════════════════════════
# 集成测试 —— 需要真实有头浏览器 + Playwright + 网络连接
# ═════════════════════════════════════════════════════════════════════════════


def _get_perception_targets() -> list[tuple[str, str]]:
    """从环境变量读取 Perception 测试目标。

    格式（序号从 1 开始）：
        PERCEPTION_TEST_LABEL_1=百度
        PERCEPTION_TEST_URL_1=https://www.baidu.com
        PERCEPTION_TEST_LABEL_2=虎扑体育
        PERCEPTION_TEST_URL_2=https://soccer.hupu.com/

    无环境变量时返回默认的百度 + 虎扑。
    """
    targets: list[tuple[str, str]] = []
    i = 1
    while True:
        label = os.environ.get(f"PERCEPTION_TEST_LABEL_{i}")
        url = os.environ.get(f"PERCEPTION_TEST_URL_{i}")
        if label and url:
            targets.append((label.strip(), url.strip()))
            i += 1
        else:
            break

    if not targets:
        targets = [
            ("百度", "https://www.baidu.com"),
            ("虎扑体育", "https://soccer.hupu.com/"),
        ]

    return targets


def _get_perception_ids() -> list[str]:
    """生成 pytest id 列表（用于 -k 筛选）。"""
    return [t[0] for t in _get_perception_targets()]


@pytest.mark.skipif(
    not __import__("tests.conftest", fromlist=["playwright_available"]).playwright_available,
    reason="需要 Playwright 浏览器（安装: playwright install chromium）",
)
class TestPerceptionIntegration:
    """Perception 集成测试 —— 有头浏览器，结果写入 log/ 目录。

    目标 URL 通过 .env.test 配置，或使用默认的百度 + 虎扑。
    """

    @pytest.mark.parametrize(
        "target",
        _get_perception_targets(),
        ids=_get_perception_ids(),
    )
    def test_headed_perception(self, target: tuple[str, str]) -> None:
        """打开页面 → Perception.observe() → 验证 → 写入 log/。"""
        from urllib.parse import urlparse

        from classic_web_agent.browser import Browser

        label, url = target

        with Browser(headless=False) as browser:
            browser.goto(url)
            perception = Perception(vlm=None, browser=browser)
            state = perception.observe()

        # ── 验证 PageState 完整性 ──
        assert state.url, "URL 不应为空"
        assert state.current_tab_id, "current_tab_id 不应为空"
        assert state.tabs_list, "tabs_list 不应为空"
        assert state.current_tab_id in state.tabs_list, (
            f"tabs_list 不包含当前标签页标识 '{state.current_tab_id}':\n"
            f"{state.tabs_list}"
        )
        expected_host = urlparse(url).hostname or ""
        if expected_host:
            assert expected_host in state.url.lower(), (
                f"当前 URL '{state.url}' 不包含目标域名 '{expected_host}'"
            )

        assert len(state.title) > 0, f"页面标题为空 (url={state.url})"

        assert state.screenshot.startswith("data:image/"), (
            "screenshot 不是合法的 data URI"
        )
        assert len(state.screenshot) > 100, "screenshot data URI 过短"

        assert len(state.tree_text) > 0, (
            f"tree_text 为空!\nurl={state.url}\ntitle={state.title}"
        )

        assert "[" in state.tree_text, (
            f"未找到任何可交互元素 [backendNodeId]\n"
            f"url={state.url}\ntitle={state.title}\n"
            f"tree_text (前 500 字符):\n{state.tree_text[:500]}"
        )

        # ── 写入 log/{label}_tree_text.txt ──
        log_dir = Path("log")
        log_dir.mkdir(parents=True, exist_ok=True)

        safe_name = label.replace(" ", "_").replace("/", "_")
        output_path = log_dir / f"{safe_name}_tree_text.txt"
        output_path.touch(exist_ok=True)
        output_path.write_text(state.tree_text, encoding="utf-8")

        logger.info("[%s] %s → log/%s (%d 字符, %d 交互元素)",
                     label, state.url, output_path.name,
                     len(state.tree_text), state.tree_text.count("["))

    def test_tabs_list_multiple_tabs(self) -> None:
        """打开多个标签页后 tabs_list 应包含所有标签页信息。"""
        from classic_web_agent.browser import Browser

        with Browser(headless=False) as browser:
            perception = Perception(vlm=None, browser=browser)

            # 默认第一个标签页
            state = perception.observe()
            assert state.current_tab_id == "tab_0", (
                f"第一个标签页应为 tab_0，收到 '{state.current_tab_id}'"
            )
            assert state.tabs_list.count("tab_") == 1
            logger.info("初始标签页: %s", state.current_tab_id)

            # 打开新标签页
            browser.new_tab("https://example.com")
            state = perception.observe()
            assert state.current_tab_id == "tab_1", (
                f"新标签页应为 tab_1，收到 '{state.current_tab_id}'"
            )
            assert state.tabs_list.count("tab_") == 2
            assert "← 当前" in state.tabs_list, (
                "tabs_list 应标记当前标签页:\n" + state.tabs_list
            )
            logger.info("双标签页 tabs_list:\n%s", state.tabs_list)
