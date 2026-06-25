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
    _build_enhanced_tree,
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


class TestHiddenPropagation:
    """隐藏传递机制测试 —— _build_enhanced_tree() 的 parent_hidden 传播。"""

    @staticmethod
    def _make_el(
        tag: str,
        attrs: list[str] | None = None,
        children: list[dict] | None = None,
        backend_id: int = 0,
    ) -> dict:
        """构造简化 CDP DOM 节点（仅含 _build_enhanced_tree 需要的字段）。"""
        node: dict = {
            "nodeId": backend_id,
            "backendNodeId": backend_id,
            "nodeType": 1,
            "nodeName": tag.upper(),
            "nodeValue": "",
            "attributes": attrs or [],
            "children": children or [],
        }
        return node

    def test_parent_display_none_hides_children(self) -> None:
        """父元素 display:none → 子元素自动隐藏。"""
        child = self._make_el("button", attrs=["id", "btn"], backend_id=2)
        parent = self._make_el(
            "div",
            attrs=["style", "display: none", "class", "hide"],
            children=[child],
            backend_id=1,
        )
        tree = _build_enhanced_tree(parent, {}, {})
        assert tree.is_hidden is True, "父元素应隐藏"
        assert len(tree.children) == 1
        assert tree.children[0].is_hidden is True, "子元素应继承父元素隐藏"
        assert tree.children[0].is_interactive is False, "隐藏元素不应可交互"
        logger.info("parent display:none → child hidden ✓")

    def test_parent_visibility_hidden_hides_children(self) -> None:
        """父元素 visibility:hidden → 子元素自动隐藏。"""
        child = self._make_el("a", attrs=["href", "/"], backend_id=2)
        parent = self._make_el(
            "div",
            attrs=["style", "visibility: hidden"],
            children=[child],
            backend_id=1,
        )
        tree = _build_enhanced_tree(parent, {}, {})
        assert tree.is_hidden is True
        assert tree.children[0].is_hidden is True
        assert tree.children[0].is_interactive is False
        logger.info("parent visibility:hidden → child hidden ✓")

    def test_nested_multi_level_hidden(self) -> None:
        """三级嵌套隐藏：祖父 hidden → 父 hidden → 子 hidden。"""
        leaf = self._make_el("input", attrs=["type", "text"], backend_id=3)
        parent = self._make_el("div", children=[leaf], backend_id=2)
        grandparent = self._make_el(
            "div",
            attrs=["class", "hidden"],
            children=[parent],
            backend_id=1,
        )
        tree = _build_enhanced_tree(grandparent, {}, {})
        assert tree.is_hidden is True
        assert tree.children[0].is_hidden is True
        assert tree.children[0].children[0].is_hidden is True
        assert tree.children[0].children[0].is_interactive is False
        logger.info("三级嵌套隐藏继承 ✓")

    def test_visible_parent_visible_child(self) -> None:
        """父元素可见 → 子元素正常检测可见性。"""
        child = self._make_el(
            "button",
            attrs=["id", "btn"],
            backend_id=2,
        )
        parent = self._make_el("div", children=[child], backend_id=1)
        tree = _build_enhanced_tree(parent, {}, {})
        # 父元素无隐藏属性，不应被隐藏
        assert tree.is_hidden is False
        # 子元素 button 应可交互且可见
        assert tree.children[0].is_hidden is False
        assert tree.children[0].is_interactive is True
        logger.info("可见父元素 → 子元素正常可见 ✓")

    def test_mixed_visibility_siblings(self) -> None:
        """同级元素：一个隐藏父元素中的按钮 + 一个可见的按钮。"""
        hidden_child = self._make_el("button", attrs=["id", "h-btn"], backend_id=3)
        hidden_parent = self._make_el(
            "div",
            attrs=["style", "display: none"],
            children=[hidden_child],
            backend_id=2,
        )
        visible_child = self._make_el("button", attrs=["id", "v-btn"], backend_id=5)

        root = self._make_el(
            "div",
            children=[hidden_parent, visible_child],
            backend_id=1,
        )
        tree = _build_enhanced_tree(root, {}, {})
        # 根节点可见
        assert tree.is_hidden is False
        # 两个子节点
        assert len(tree.children) == 2
        # 第一个子节点（父元素隐藏）→ 隐藏
        assert tree.children[0].is_hidden is True
        # 第二个子节点（可见的 button）→ 可见且可交互
        assert tree.children[1].is_hidden is False
        assert tree.children[1].is_interactive is True
        logger.info("混合可见性同级元素 ✓")


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


# ═════════════════════════════════════════════════════════════════════════
# SoM 标注测试
# ═════════════════════════════════════════════════════════════════════════


class TestSomCollectedElements:
    """_collect_som_elements() 单元测试 —— 收集可交互元素的准确性。"""

    def test_collects_interactive_elements(self) -> None:
        from classic_web_agent.subagent.perception import (
            EnhancedDOMNode, Bounds, _collect_som_elements,
        )

        btn = EnhancedDOMNode(
            backend_node_id=1234, node_type=1, tag_name="button",
            is_interactive=True, is_hidden=False,
            bounds=Bounds(x=10, y=20, width=100, height=30),
        )
        result = _collect_som_elements(btn)
        assert len(result) == 1
        assert result[0]["backend_node_id"] == 1234
        assert result[0]["x"] == 10
        assert result[0]["y"] == 20

    def test_skips_hidden_elements(self) -> None:
        from classic_web_agent.subagent.perception import (
            EnhancedDOMNode, Bounds, _collect_som_elements,
        )

        hidden_btn = EnhancedDOMNode(
            backend_node_id=1, node_type=1, tag_name="button",
            is_interactive=True, is_hidden=True,
            bounds=Bounds(x=0, y=0, width=100, height=30),
        )
        result = _collect_som_elements(hidden_btn)
        assert len(result) == 0

    def test_skips_non_interactive(self) -> None:
        from classic_web_agent.subagent.perception import (
            EnhancedDOMNode, Bounds, _collect_som_elements,
        )

        div = EnhancedDOMNode(
            backend_node_id=2, node_type=1, tag_name="div",
            is_interactive=False, is_hidden=False,
            bounds=Bounds(x=0, y=0, width=200, height=100),
        )
        result = _collect_som_elements(div)
        assert len(result) == 0

    def test_skips_tiny_elements(self) -> None:
        from classic_web_agent.subagent.perception import (
            EnhancedDOMNode, Bounds, _collect_som_elements,
        )

        tiny = EnhancedDOMNode(
            backend_node_id=3, node_type=1, tag_name="a",
            is_interactive=True, is_hidden=False,
            bounds=Bounds(x=0, y=0, width=3, height=2),
        )
        result = _collect_som_elements(tiny)
        assert len(result) == 0

    def test_collects_nested_elements(self) -> None:
        from classic_web_agent.subagent.perception import (
            EnhancedDOMNode, Bounds, _collect_som_elements,
        )

        container = EnhancedDOMNode(
            backend_node_id=0, node_type=1, tag_name="div",
            is_interactive=False, is_hidden=False,
        )
        btn1 = EnhancedDOMNode(
            backend_node_id=10, node_type=1, tag_name="button",
            is_interactive=True, is_hidden=False,
            bounds=Bounds(x=0, y=0, width=50, height=20),
        )
        btn2 = EnhancedDOMNode(
            backend_node_id=11, node_type=1, tag_name="a",
            is_interactive=True, is_hidden=False,
            bounds=Bounds(x=100, y=0, width=50, height=20),
        )
        container.children = [btn1, btn2]
        result = _collect_som_elements(container)
        assert len(result) == 2
        assert result[0]["backend_node_id"] == 10
        assert result[1]["backend_node_id"] == 11


class TestSomAnnotation:
    """annotate_screenshot() 单元测试 —— 截图标注的正确性。"""

    def test_returns_original_on_empty(self) -> None:
        from classic_web_agent.subagent.som import annotate_screenshot

        result = annotate_screenshot("", [])
        assert result == ""

    def test_annotates_valid_png(self) -> None:
        from classic_web_agent.subagent.som import annotate_screenshot
        from PIL import Image, ImageDraw
        import io, base64

        # 创建一张纯色测试 PNG
        img = Image.new("RGB", (200, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        elements = [
            {
                "backend_node_id": 42,
                "tag_name": "button",
                "x": 10, "y": 20,
                "width": 80, "height": 30,
            },
        ]
        result = annotate_screenshot(data_uri, elements)
        assert result.startswith("data:image/png;base64,")
        assert len(result) > len(data_uri), "标注后图片应比原始大（含编号）"

    def test_out_of_bounds_label_clamped(self) -> None:
        """元素靠近边缘时标签不应超出截图边界。"""
        from classic_web_agent.subagent.som import annotate_screenshot
        from PIL import Image
        import io, base64

        img = Image.new("RGB", (100, 50), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        # 元素在左上角，标签应被 clamp 到截图内
        elements = [{"backend_node_id": 1, "tag_name": "button", "x": 0, "y": 0, "width": 10, "height": 10}]
        result = annotate_screenshot(data_uri, elements)
        assert result.startswith("data:image/png;base64,")
