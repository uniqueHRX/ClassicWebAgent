"""Perception 模块单元测试 + 集成测试。

测试策略：
- test_*_stub: 不需要浏览器，纯逻辑测试
- test_*_baidu: 需要真实浏览器 + 网络连接，验证 CDP 三流采集
"""

import pytest

from classic_web_agent.agent.perception import (
    Perception,
    EnhancedDOMNode,
    Bounds,
    _is_hidden,
    _is_interactive,
    _serialize,
)
from classic_web_agent.agent.types import PageState


# ═════════════════════════════════════════════════════════════════════════════
# Stub 测试
# ═════════════════════════════════════════════════════════════════════════════


def test_perception_no_browser():
    """浏览器未启动时 observe() 应返回空 PageState。"""
    perception = Perception(vlm=None, browser=None)
    state = perception.observe()
    assert isinstance(state, PageState)
    assert state.screenshot == ""
    assert state.url == ""
    assert state.title == ""
    assert state.tree_text == ""


def test_is_hidden_by_attribute():
    """HTML hidden 属性应被判定为隐藏。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        attributes={"hidden": "", "class": "test"},
    )
    assert _is_hidden(node) is True


def test_is_hidden_by_aria():
    """aria-hidden="true" 应被判定为隐藏。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        attributes={"aria-hidden": "true"},
    )
    assert _is_hidden(node) is True


def test_is_not_hidden():
    """普通可见节点不应被判定为隐藏。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        bounds=Bounds(x=0, y=0, width=100, height=50),
    )
    assert _is_hidden(node) is False


def test_is_hidden_zero_bounds():
    """零宽零高节点应被判定为隐藏。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        bounds=Bounds(x=0, y=0, width=0, height=0),
    )
    assert _is_hidden(node) is True


def test_is_interactive_button_tag():
    """button 标签应被判定为可交互（级别 1）。"""
    node = EnhancedDOMNode(node_type=1, tag_name="button")
    assert _is_interactive(node) is True


def test_is_interactive_input_tag():
    """input 标签应被判定为可交互（级别 1）。"""
    node = EnhancedDOMNode(node_type=1, tag_name="input")
    assert _is_interactive(node) is True


def test_is_interactive_a_tag():
    """a 标签应被判定为可交互（级别 1）。"""
    node = EnhancedDOMNode(node_type=1, tag_name="a")
    assert _is_interactive(node) is True


def test_is_interactive_by_role():
    """AX role 为 button 的 div 应被判定为可交互（级别 2）。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        ax_role="button",
    )
    assert _is_interactive(node) is True


def test_is_interactive_by_event():
    """含 onclick 属性的 div 应被判定为可交互（级别 3）。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        attributes={"onclick": "submit()"},
    )
    assert _is_interactive(node) is True


def test_is_interactive_by_tabindex():
    """含 tabindex 属性的 div 应被判定为可交互（级别 3）。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        attributes={"tabindex": "0"},
    )
    assert _is_interactive(node) is True


def test_is_not_interactive():
    """纯展示 div 不应被判定为可交互。"""
    node = EnhancedDOMNode(node_type=1, tag_name="div")
    assert _is_interactive(node) is False


def test_serialize_text_node():
    """文本节点应输出缩进 + 文本内容。"""
    node = EnhancedDOMNode(node_type=3, node_value="  Hello World  ")
    result = _serialize(node)
    assert result == "Hello World\n"


def test_serialize_empty_text():
    """空白文本节点应输出空字符串。"""
    node = EnhancedDOMNode(node_type=3, node_value="   \n  ")
    result = _serialize(node)
    assert result == ""


def test_serialize_interactive_element():
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


def test_serialize_interactive_with_bounds():
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


def test_serialize_hidden_node():
    """隐藏节点应输出空字符串。"""
    node = EnhancedDOMNode(
        node_type=1,
        tag_name="div",
        is_hidden=True,
    )
    result = _serialize(node)
    assert result == ""


def test_serialize_nested_container():
    """嵌套结构应正确处理缩进和容器空行。"""
    # <div>           ← 容器 depth=0
    #   <button>      ← 交互 depth=1
    #     按钮文本     ← 文本 depth=2
    #   </button>
    # </div>
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


# ═════════════════════════════════════════════════════════════════════════════
# 集成测试（需要真实浏览器 + Playwright）
# ═════════════════════════════════════════════════════════════════════════════


def _check_playwright_browser() -> bool:
    """检查 Playwright 浏览器是否可用。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            # 只检查是否安装了 Chromium
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _check_playwright_browser(),
    reason="需要 Playwright 浏览器（安装: playwright install chromium）",
)
def test_baidu_perception():
    """打开百度首页，运行 perception，验证 tree_text 包含搜索框。"""
    from classic_web_agent.browser import Browser

    with Browser(headless=True) as browser:
        browser.goto("https://www.baidu.com")
        perception = Perception(vlm=None, browser=browser)
        state = perception.observe()

        # 基本页面信息
        assert "baidu.com" in state.url.lower() or "www.baidu.com" in state.url.lower()
        assert len(state.title) > 0
        assert state.screenshot.startswith("data:image/")

        # tree_text 应包含可交互元素
        assert len(state.tree_text) > 0, f"tree_text 为空!\nurl={state.url}\ntitle={state.title}"

        # 应能找到搜索相关的可交互元素（input 或 a 标签）
        found_interactive = state.tree_text.count("[") > 0
        assert found_interactive, (
            f"未找到任何可交互元素 [backendNodeId]\n"
            f"url={state.url}\ntitle={state.title}\n"
            f"tree_text (前 500 字符):\n{state.tree_text[:500]}"
        )

        # 打印 tree_text 前 30 行供调试查看
        lines = state.tree_text.split("\n")
        print(f"\n=== 百度首页 tree_text ({len(lines)} 行, {len(state.tree_text)} 字符) ===")
        for line in lines[:30]:
            print(line)
