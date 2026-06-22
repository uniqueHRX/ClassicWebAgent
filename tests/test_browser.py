"""Browser 集成测试 —— 有头浏览器，可观察操作过程。

运行方式:
    # 安装 Playwright 浏览器（首次运行前）
    poetry run playwright install chromium

    # 运行全部测试（有头模式，观察浏览器窗口操作）
    poetry run python -m pytest tests/test_browser.py -v --timeout=60

    # 按标签筛选
    poetry run python -m pytest tests/test_browser.py -v -k "nav"
    poetry run python -m pytest tests/test_browser.py -v -k "tab"
    poetry run python -m pytest tests/test_browser.py -v -k "click"

前置条件:
    pyproject.toml 依赖：
        "playwright (>=1.60.0,<2.0.0)"          # 浏览器自动化
        "pillow (>=12.2.0,<13.0.0)"             # 截图优化

注意事项:
    - 根据用户要求，`headless=False`（有头模式），测试时会弹出 Chromium 窗口
    - 每个测试使用独立的 HTML 页面（`page.set_content()`），不依赖外部网络
    - 测试间插入 `time.sleep()` 延时，便于肉眼观察操作过程
    - 无需 `.env` 配置，不依赖任何外部 API
"""

import logging
import time
from typing import Any

import pytest
from PIL import Image

from classic_web_agent.browser import Browser, BrowserError

logger = logging.getLogger(__name__)

# 各测试步骤间的观察延时（秒）
OBSERVE_DELAY = 1.5

# ── 测试用 HTML 页面 ────────────────────────────────────────────────────

PAGE_INTERACT = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Browser 交互测试</title></head>
<body>
    <h1 id="title">Browser Test Page</h1>

    <section id="click-section">
        <h2>点击测试</h2>
        <button id="btn-click"
                onclick="document.getElementById('click-output').textContent='已点击'"
                style="padding:12px 24px;cursor:pointer;font-size:18px">
            Click Me
        </button>
        <p id="click-output">等待点击...</p>
    </section>

    <section id="type-section">
        <h2>输入测试</h2>
        <input id="input-field" type="text"
               placeholder="在此输入..."
               style="width:300px;padding:8px;font-size:16px">
        <p id="type-output">未输入</p>
    </section>

    <section id="hover-section">
        <h2>悬停测试</h2>
        <div id="hover-target"
             onmouseover="this.style.background='orange';document.getElementById('hover-output').textContent='已悬停'"
             onmouseout="this.style.background='#eee'"
             style="width:200px;height:80px;background:#eee;border:2px solid #ccc;
                    display:flex;align-items:center;justify-content:center;font-size:16px">
            悬停此区域
        </div>
        <p id="hover-output">等待悬停...</p>
    </section>

    <section id="long-section">
        <h2>滚动测试</h2>
        <div style="height:1200px;background:linear-gradient(white,#ccc);display:flex;
                    align-items:center;justify-content:center;font-size:20px">
            ↓ 下方有目标 ↓
        </div>
        <p id="scroll-target" style="background:yellow;padding:20px;font-size:18px">
            滚动到达目标
        </p>
    </section>

    <section id="find-section">
        <h2>搜索测试</h2>
        <p data-testid="find-target">UniqueSearchableText_42</p>
    </section>
</body>
</html>
"""

PAGE_MULTI_TAB = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>多标签页测试 - Tab A</title></head>
<body>
    <h1>这是标签页 A</h1>
    <p>当前标签页在 tab_index=0</p>
</body>
</html>
"""

PAGE_TAB_B = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>标签页 B</title></head>
<body>
    <h1>这是标签页 B</h1>
    <p>通过 NEW_TAB 创建的标签页</p>
</body>
</html>
"""


# ── 测试方法（browser fixture 来自 tests/conftest.py）───


class TestBrowserNavigation:
    """导航操作测试。"""

    def test_goto_and_page_info(self, browser: Browser) -> None:
        """GOTO 导航 + 页面信息获取。"""
        assert browser.tab_count == 1
        assert browser.active_index == 0

        # 设置页面内容
        browser.current_page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY)

        title = browser.current_page.title()
        assert "Browser 交互测试" in title
        logger.info("页面标题: %s", title)

    def test_go_back_and_forward(self, browser: Browser) -> None:
        """GO_BACK / GO_FORWARD 导航历史。"""
        page = browser.current_page

        # 第一页
        page.set_content(
            "<html><body><h1>Page 1 - 首页</h1></body></html>"
        )
        time.sleep(OBSERVE_DELAY * 0.5)

        # 第二页（通过 js_eval 改变内容来模拟导航历史）
        page.set_content(
            "<html><body><h1>Page 2</h1></body></html>"
        )
        time.sleep(OBSERVE_DELAY * 0.5)

        # 实际上 set_content 不会产生导航历史，用 goto 来产生历史
        # 改用 data URI 产生真实导航记录
        page.goto("data:text/html,<h1>Page 1</h1>")
        page.goto("data:text/html,<h1>Page 2</h1>")
        time.sleep(OBSERVE_DELAY * 0.5)

        # GO_BACK
        browser.go_back()
        time.sleep(OBSERVE_DELAY * 0.5)
        body_text = page.evaluate("document.body.innerText")
        assert "Page 1" in body_text
        logger.info("GO_BACK 后页面内容: %s", body_text)

        # GO_FORWARD
        browser.go_forward()
        time.sleep(OBSERVE_DELAY * 0.5)
        body_text = page.evaluate("document.body.innerText")
        assert "Page 2" in body_text
        logger.info("GO_FORWARD 后页面内容: %s", body_text)

    def test_scroll(self, browser: Browser) -> None:
        """SCROLL 滚动测试。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY)

        # 截图初始位置
        screenshot_before = browser.screenshot()
        img = _data_uri_to_pil(screenshot_before)
        _, _, w, h = img.getbbox()
        logger.info("初始截图尺寸: %dx%d", w, h)

        # 向下滚动
        browser.scroll("down")
        time.sleep(OBSERVE_DELAY)

        # 查找滚动后可见的元素
        is_visible = page.evaluate(
            "() => {"
            "  const el = document.getElementById('scroll-target');"
            "  const rect = el.getBoundingClientRect();"
            "  return rect.top >= 0 && rect.top < window.innerHeight;"
            "}"
        )
        if is_visible:
            logger.info("滚动目标已进入视口")
        else:
            logger.info("继续向下滚动...")
            browser.scroll("down")
            time.sleep(OBSERVE_DELAY)

        # 向上滚动回到顶部
        browser.scroll("up")
        time.sleep(OBSERVE_DELAY)


class TestBrowserTabs:
    """标签页管理测试。"""

    def test_new_and_switch_tab(self, browser: Browser) -> None:
        """NEW_TAB 创建 + SWITCH_TAB 切换。"""
        # 标签页 A（index=0）
        browser.current_page.set_content(PAGE_MULTI_TAB)
        time.sleep(OBSERVE_DELAY * 0.5)
        assert "Tab A" in browser.current_page.title()

        # NEW_TAB（自动切换到新页 index=1）
        tab_b_index = browser.new_tab()
        assert tab_b_index == 1
        assert browser.tab_count == 2

        # 在标签页 B 设置内容
        browser.current_page.set_content(PAGE_TAB_B)
        time.sleep(OBSERVE_DELAY * 0.5)
        assert "标签页 B" in browser.current_page.title()
        logger.info("标签页 B 已设置")

        # SWITCH_TAB 回标签页 A（index=0）
        browser.switch_tab(0)
        assert browser.active_index == 0
        assert "Tab A" in browser.current_page.title()
        logger.info("切换回标签页 A 成功")

        # SWITCH_TAB 回标签页 B（index=1）
        browser.switch_tab(1)
        assert browser.active_index == 1
        assert "标签页 B" in browser.current_page.title()
        logger.info("切换回标签页 B 成功")
        time.sleep(OBSERVE_DELAY)

    def test_close_tab(self, browser: Browser) -> None:
        """CLOSE_TAB 关闭标签页。"""
        # 标签页 A（index=0）：PAGE_MULTI_TAB
        browser.current_page.set_content(PAGE_MULTI_TAB)
        # 标签页 B（index=1，自动切换）：PAGE_TAB_B
        browser.new_tab()
        browser.current_page.set_content(PAGE_TAB_B)
        # 标签页 C（index=2，自动切换）：Tab C
        browser.new_tab()
        browser.current_page.set_content(
            "<html><body><h1>Tab C</h1></body></html>"
        )
        assert browser.tab_count == 3
        time.sleep(OBSERVE_DELAY * 0.5)

        # 关闭 Tab C（index=2）→ 自动切换到 B（index=1）
        browser.close_tab()
        assert browser.tab_count == 2
        assert browser.active_index == 1
        assert "标签页 B" in browser.current_page.title()
        logger.info("关闭 Tab C → 切换到 Tab B ✅")

        # 关闭 Tab B（index=1）→ 自动切换到 A（index=0）
        browser.close_tab()
        assert browser.tab_count == 1
        assert browser.active_index == 0
        assert "Tab A" in browser.current_page.title()
        logger.info("关闭 Tab B → 切换到 Tab A ✅")
        time.sleep(OBSERVE_DELAY * 0.5)

    def test_close_last_tab_error(self, browser: Browser) -> None:
        """只剩一个标签页时关闭抛出 BrowserError。"""
        browser.current_page.set_content(PAGE_MULTI_TAB)
        assert browser.tab_count == 1

        with pytest.raises(BrowserError, match="只剩一个标签页"):
            browser.close_tab()

    def test_switch_tab_out_of_range(self, browser: Browser) -> None:
        """标签页索引越界时抛出 BrowserError。"""
        with pytest.raises(BrowserError, match="超出范围"):
            browser.switch_tab(99)

    def test_new_tab_with_url(self, browser: Browser) -> None:
        """NEW_TAB 带 URL 参数。"""
        # 使用 about:blank 再 set_content，避免 data URI 加载问题
        index = browser.new_tab(url="about:blank")
        assert index == 1
        browser.current_page.set_content(
            "<html><body><h1>URL Tab Content</h1></body></html>"
        )
        time.sleep(OBSERVE_DELAY * 0.5)
        body_text = browser.current_page.evaluate(
            "document.body.innerText"
        )
        assert "URL Tab Content" in body_text
        logger.info("带 URL 的标签页内容: %s", body_text)
        time.sleep(OBSERVE_DELAY)


class TestBrowserInteraction:
    """元素交互测试。"""

    def test_click_button(self, browser: Browser) -> None:
        """CLICK 点击按钮。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        # 获取按钮的 backendNodeId
        backend_node_id = _get_backend_node_id(page, "#btn-click")
        logger.info("按钮 backendNodeId: %d", backend_node_id)

        # CLICK
        browser.click(backend_node_id)
        time.sleep(OBSERVE_DELAY * 0.5)

        output = page.evaluate(
            "document.getElementById('click-output').textContent"
        )
        assert output == "已点击"
        logger.info("点击后输出: %s", output)
        time.sleep(OBSERVE_DELAY)

    def test_type_text(self, browser: Browser) -> None:
        """TYPE 输入文本。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        backend_node_id = _get_backend_node_id(page, "#input-field")
        logger.info("输入框 backendNodeId: %d", backend_node_id)

        test_text = "Hello Browser Test!"
        browser.type(backend_node_id, test_text)
        time.sleep(OBSERVE_DELAY * 0.5)

        input_value = page.evaluate(
            "document.getElementById('input-field').value"
        )
        assert input_value == test_text
        logger.info("输入内容: %s", input_value)
        time.sleep(OBSERVE_DELAY)

    def test_hover_element(self, browser: Browser) -> None:
        """HOVER 悬停元素。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        backend_node_id = _get_backend_node_id(page, "#hover-target")
        logger.info("悬停区域 backendNodeId: %d", backend_node_id)

        browser.hover(backend_node_id)
        time.sleep(OBSERVE_DELAY * 0.5)

        output = page.evaluate(
            "document.getElementById('hover-output').textContent"
        )
        assert output == "已悬停"
        logger.info("悬停后输出: %s", output)
        time.sleep(OBSERVE_DELAY)

    def test_mouse_click(self, browser: Browser) -> None:
        """MOUSE_CLICK 坐标点击。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        # 获取按钮的坐标
        box = page.evaluate(
            "() => {"
            "  const el = document.getElementById('btn-click');"
            "  const rect = el.getBoundingClientRect();"
            "  return {x: rect.x, y: rect.y, w: rect.width, h: rect.height};"
            "}"
        )
        x = int(box["x"] + box["w"] / 2)
        y = int(box["y"] + box["h"] / 2)
        logger.info("按钮中心坐标: (%d, %d)", x, y)

        browser.mouse_click(x, y)
        time.sleep(OBSERVE_DELAY * 0.5)

        output = page.evaluate(
            "document.getElementById('click-output').textContent"
        )
        assert output == "已点击"
        logger.info("MOUSE_CLICK 后输出: %s", output)
        time.sleep(OBSERVE_DELAY)


class TestBrowserInformation:
    """信息获取测试。"""

    def test_screenshot(self, browser: Browser) -> None:
        """SCREENSHOT 截图 → PIL optimize PNG data URI。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY)

        data_uri = browser.screenshot()
        assert data_uri.startswith("data:image/png;base64,")
        logger.info("截图 data URI 前缀匹配 ✅")

        # 验证 PIL 优化后的图片可正常解码
        img = _data_uri_to_pil(data_uri)
        assert img is not None
        assert img.format == "PNG"
        w, h = img.size
        logger.info("截图尺寸: %dx%d", w, h)

    def test_extract_text_full_page(self, browser: Browser) -> None:
        """EXTRACT 提取页面全文（element_id=None）。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        text = browser.extract_text()
        assert "Browser Test Page" in text
        assert "点击测试" in text
        assert "悬停测试" in text
        logger.info("页面全文提取成功，长度: %d 字符", len(text))

    def test_extract_text_element(self, browser: Browser) -> None:
        """EXTRACT 提取特定元素文本（element_id=有值）。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        backend_node_id = _get_backend_node_id(page, "#click-output")
        text = browser.extract_text(backend_node_id)
        assert "等待点击" in text
        logger.info("元素文本提取: %s", text)

    def test_find_text(self, browser: Browser) -> None:
        """FIND 页内文本搜索。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        element = browser.find_text("UniqueSearchableText_42")
        assert element is not None
        text = element.inner_text()
        assert "UniqueSearchableText_42" in text
        logger.info("FIND 找到元素，文本: %s", text)
        time.sleep(OBSERVE_DELAY * 0.5)

    def test_find_text_not_found(self, browser: Browser) -> None:
        """FIND 搜索不存在文本返回 None。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)

        element = browser.find_text("NotExistText_" * 10)
        assert element is None
        logger.info("FIND 未找到文本返回 None ✅")

    def test_js_eval(self, browser: Browser) -> None:
        """JS_EVAL 执行自定义 JavaScript。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)

        result = browser.js_eval("document.title")
        assert "Browser 交互测试" in result
        logger.info("JS_EVAL document.title: %s", result)

        result = browser.js_eval(
            "document.getElementById('title').textContent"
        )
        assert "Browser Test Page" in result
        logger.info("JS_EVAL h1 文本: %s", result)


class TestBrowserCDP:
    """CDP Session 和 resolve_node 测试。"""

    def test_get_cdp_session(self, browser: Browser) -> None:
        """get_cdp_session 返回有效的 CDP session。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)

        cdp = browser.get_cdp_session()
        # 发送一个简单的 CDP 协议命令验证可用性
        result = cdp.send("DOM.getDocument", {"depth": 0})
        root = result.get("root", {})
        assert root.get("nodeName") == "#document"
        logger.info("CDP session 可用，文档根节点: %s", root.get("nodeName"))

    def test_resolve_node(self, browser: Browser) -> None:
        """resolve_node 通过 backendNodeId 解析为 ElementHandle。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        # 通过 JS 获取 h1 元素的 backendNodeId
        backend_node_id = _get_backend_node_id(page, "#title")
        logger.info("h1 backendNodeId: %d", backend_node_id)

        # resolve_node → ElementHandle
        handle = browser.resolve_node(backend_node_id)
        tag_name = handle.evaluate("el => el.tagName")
        text = handle.evaluate("el => el.textContent")
        assert tag_name == "H1"
        assert "Browser Test Page" in text
        logger.info("resolve_node 成功: tag=%s text=%s", tag_name, text)

    def test_resolve_node_invalid(self, browser: Browser) -> None:
        """无效 backendNodeId 时抛出 BrowserError。"""
        browser.current_page.set_content(PAGE_INTERACT)

        with pytest.raises(BrowserError, match="无法解析"):
            browser.resolve_node(99999999)

    def test_resolve_then_click(self, browser: Browser) -> None:
        """resolve_node → click_element 完整链路（模拟 executor 流程）。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        backend_node_id = _get_backend_node_id(page, "#btn-click")

        # executor 的典型流程：resolve → click_element
        handle = browser.resolve_node(backend_node_id)
        browser.click_element(handle)
        time.sleep(OBSERVE_DELAY * 0.5)

        output = page.evaluate(
            "document.getElementById('click-output').textContent"
        )
        assert output == "已点击"
        logger.info("resolve + click 完整链路测试通过 ✅")

    def test_resolve_then_type(self, browser: Browser) -> None:
        """resolve_node → type_text 完整链路（模拟 executor 流程）。"""
        page = browser.current_page
        page.set_content(PAGE_INTERACT)
        time.sleep(OBSERVE_DELAY * 0.5)

        backend_node_id = _get_backend_node_id(page, "#input-field")
        test_text = "Executor Complete Flow"

        handle = browser.resolve_node(backend_node_id)
        browser.type_text(handle, test_text)
        time.sleep(OBSERVE_DELAY * 0.5)

        value = page.evaluate(
            "document.getElementById('input-field').value"
        )
        assert value == test_text
        logger.info("resolve + type 完整链路测试通过 ✅")


class TestBrowserLifecycle:
    """浏览器生命周期测试。"""

    def test_context_manager(self) -> None:
        """with 语句自动启动/关闭浏览器。"""
        with Browser(headless=False) as b:
            b.current_page.set_content(PAGE_INTERACT)
            assert b.tab_count == 1
            title = b.current_page.title()
            assert "Browser 交互测试" in title
            logger.info("Context manager 生命周期测试通过")

        # 退出 with 后浏览器应已关闭
        logger.info("浏览器已自动关闭 ✅")

    def test_double_launch(self, browser: Browser) -> None:
        """重复 launch 不会产生错误。"""
        browser.launch()  # 第二次 launch
        assert browser.tab_count >= 1
        logger.info("重复 launch 安全忽略 ✅")

    def test_press_key(self, browser: Browser) -> None:
        """PRESS 键盘按键。"""
        page = browser.current_page
        page.set_content("""
            <html><body>
            <input id="press-input" type="text" style="width:300px;padding:8px">
            </body></html>
        """)
        time.sleep(OBSERVE_DELAY * 0.5)

        # 聚焦输入框
        page.evaluate("document.getElementById('press-input').focus()")
        time.sleep(OBSERVE_DELAY * 0.3)

        # PRESS 按键
        browser.press_key("a")
        browser.press_key("b")
        browser.press_key("c")
        time.sleep(OBSERVE_DELAY * 0.3)

        value = page.evaluate(
            "document.getElementById('press-input').value"
        )
        assert value == "abc"
        logger.info("PRESS 按键输入: %s", value)
        time.sleep(OBSERVE_DELAY)


# ── 辅助函数 ────────────────────────────────────────────────────────────


def _get_backend_node_id(page: Any, css_selector: str) -> int:
    """通过 CSS 选择器获取元素的 backendNodeId。

    先通过 DOM.getDocument 获取根节点 nodeId，再使用 DOM.querySelector 查询元素，
    最后用 DOM.describeNode 从 nodeId 获取 backendNodeId（整数）。

    Args:
        page: Playwright Page 对象。
        css_selector: CSS 选择器字符串。

    Returns:
        CDP backendNodeId（整数）。
    """
    cdp = page.context.new_cdp_session(page)
    doc = cdp.send("DOM.getDocument", {"depth": 0})
    root_node_id: int = doc["root"]["nodeId"]
    result = cdp.send("DOM.querySelector", {
        "nodeId": root_node_id,
        "selector": css_selector,
    })
    node_id: int = result["nodeId"]
    desc = cdp.send("DOM.describeNode", {"nodeId": node_id})
    return int(desc["node"]["backendNodeId"])


def _data_uri_to_pil(data_uri: str) -> Image.Image:
    """将 data URI 转换为 PIL Image（验证截图有效性）。"""
    import base64
    import io

    header, encoded = data_uri.split(",", 1)
    raw = base64.b64decode(encoded)
    return Image.open(io.BytesIO(raw))
