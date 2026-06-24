"""Playwright 浏览器驱动 —— 生命周期管理 + 原子操作封装。

==== 职责范围 ====
本模块是纯基础设施层，不包含 Action/ActionType 引用。
executor.py 负责 Action → Browser 原子操作的映射编排。

公开方法分类：
- 浏览器生命周期: launch, close, __enter__, __exit__
- 属性: current_page, tab_count, active_index, all_pages
- CDP 基础设施: get_cdp_session
- 元素定位: resolve_node(backendNodeId → ElementHandle)
- 元素交互: click, type, hover, mouse_click (backendNodeId 方式)
            click_element, type_text, hover_element (ElementHandle 方式)
- 页面操作: scroll, press_key
- 导航: goto, go_back, go_forward
- 标签页: new_tab, close_tab, switch_tab
- 信息获取: screenshot(PIL optimize → data URI), extract_text, find_text, js_eval

==== 依赖边界 ====
- executor.py — 负责 Action → Browser 的映射编排
- perception.py — 通过 get_cdp_session() 获取 CDP session 做三流采集
- types.py — 本模块不 import 任何 types，保持基础设施层纯度

异常:
    BrowserError: 浏览器操作异常。
"""

import base64
import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image
from playwright.sync_api import (
    Browser as PW_Browser,
    BrowserContext as PW_BrowserContext,
    CDPSession as PW_CDPSession,
    ElementHandle,
    Page as PW_Page,
    Playwright as PW_Playwright,
    sync_playwright,
)

logger = logging.getLogger(__name__)


class BrowserError(Exception):
    """浏览器操作异常。"""


class Browser:
    """Playwright 浏览器管理器。

    自动管理浏览器实例、上下文、标签页列表和 CDP session。
    调用方无需关心 Playwright 对象的生命周期。

    全部原子操作按动作类型分组（箭头右端为 action-space.md 映射）：

    浏览器生命周期:    launch / close
    属性:               current_page / tab_count / active_index / all_pages
    元素交互:           click(backendNodeId) → CLICK
                       type(backendNodeId, text) → TYPE
                       hover(backendNodeId) → HOVER
                       mouse_click(x, y) → MOUSE_CLICK
    页面操作:           scroll(direction) → SCROLL
                       press_key(key) → PRESS
    导航:               goto(url) → GOTO
                       go_back() → GO_BACK
                       go_forward() → GO_FORWARD
    标签页管理:         new_tab(url?) → NEW_TAB
                       close_tab() → CLOSE_TAB
                       switch_tab(index) → SWITCH_TAB
    信息获取:           screenshot() → SCREENSHOT
                       extract_text(id?) → EXTRACT
                       find_text(text) → FIND
                       js_eval(code)

    ElementHandle 底层方法（供 executor 在已有 handle 时直接调用）:
                       click_element(handle)
                       type_text(handle, text)
                       hover_element(handle)

    CDP 基础设施:       get_cdp_session(page?) / resolve_node(backendNodeId)

    用法:
        # 通过 context manager 自动管理生命周期
        with Browser(headless=True) as browser:
            browser.goto("https://example.com")
            browser.click(1548)           # 通过 backendNodeId 点击
            browser.type(1549, "搜索词")  # 通过 backendNodeId 输入
            data_uri = browser.screenshot()  # 截图 → PIL optimize → data URI
            text = browser.extract_text()    # 提取页面全文

        # 手动管理生命周期
        browser = Browser(headless=False)
        browser.launch()
        browser.goto("https://example.com")
        browser.close()
    """

    def __init__(self, headless: bool = True,
                 user_data_dir: str | None = None) -> None:
        """初始化浏览器管理器（此时未启动 Playwright）。

        Args:
            headless: 是否无头模式。True 为无头（默认，适合 CI/脚本）；
                       False 为有头（开发调试时可观察浏览器操作）。
            user_data_dir: Chrome 用户数据目录路径（持久化 cookies/localStorage）。
                          为 None 时不使用持久化配置。
        """
        self.headless = headless
        self.user_data_dir = user_data_dir

        self._pw: PW_Playwright | None = None
        self._browser: PW_Browser | None = None
        self._context: PW_BrowserContext | None = None
        self._pages: list[PW_Page] = []
        self._cdp_sessions: dict[int, PW_CDPSession] = {}
        self._active_index: int = 0

    # ── 生命周期 ────────────────────────────────────────────────────────

    def _apply_stealth(self) -> None:
        """对浏览器 context 应用 playwright-stealth 反检测补丁。

        使用 hook_playwright_context 钩住 context，确保 NEW_PAGE 时自动应用补丁，
        而不是在页面创建之后手动 patch。这样：
        1. stealth 在页面脚本执行前注入
        2. 所有页面（包括 popup 等自动创建的）都自动获得保护
        3. 部分依赖 CLI 参数级别的 evasion 才能生效
        """
        if self._context is None:
            return
        try:
            from playwright_stealth import Stealth
            Stealth().hook_playwright_context(self._context)
            logger.debug("Stealth 钩子已挂载到 BrowserContext")
        except Exception:
            logger.debug("Stealth 挂载失败（忽略）")

    def launch(self) -> None:
        """启动 Chromium 浏览器并创建默认页面（和 CDP session）。

        具体流程：
            1. 启动 Playwright 驱动进程
            2. launch Chromium（headless/s headless 取决于构造参数）
            3. 创建默认 BrowserContext（如果配置了 user_data_dir 则用持久化模式）
            4. 创建默认 Page 并注册 popup 事件监听 + 对话框监听
            5. 为 Page 创建 CDP session

        注意：launch 后立即可以调用 goto/click/screenshot 等方法。
        重复调用 launch 会被安全忽略（日志中产生一个 warning）。
        """
        if self._browser is not None:
            logger.warning("浏览器已在运行，忽略重复 launch")
            return

        self._pw = sync_playwright().start()

        # 统一 context 配置（模拟中国用户环境）
        _context_config = dict(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )

        _browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-infobars",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        if not self.headless:
            _browser_args.append("--start-maximized")

        if self.user_data_dir:
            # 持久化模式：launch_persistent_context 自动管理 profile
            profile_path = Path(self.user_data_dir).resolve()
            profile_path.mkdir(parents=True, exist_ok=True)
            self._context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=self.headless,
                args=_browser_args,
                **_context_config,
            )
            # persistent_context 自带 browser 和 pages
            self._browser = self._context.browser
            pages = self._context.pages
            page = pages[0] if pages else self._context.new_page()
            self._pages = [page]
            logger.info(
                "浏览器已启动（持久化模式）headless=%s profile=%s",
                self.headless, profile_path,
            )
        else:
            self._browser = self._pw.chromium.launch(
                headless=self.headless, args=_browser_args,
            )
            self._context = self._browser.new_context(**_context_config)
            page = self._context.new_page()
            self._pages = [page]
            logger.info(
                "浏览器已启动 headless=%s",
                self.headless,
            )

        self._active_index = 0
        self._register_popup_listener(page)
        self._create_cdp_session(page)
        self._register_dialog_handler(page)
        self._apply_stealth()

    def close(self) -> None:
        """关闭浏览器，清理所有资源。

        按顺序：
            1. 分离所有 CDP session
            2. 关闭浏览器实例
            3. 停止 Playwright 驱动
            4. 清空内部状态

        所有异常被吞掉（确保始终能关闭成功）。
        关闭后可以基于同一实例重新 launch。
        """
        for cdp in self._cdp_sessions.values():
            try:
                cdp.detach()
            except Exception:
                pass
        self._cdp_sessions.clear()
        self._pages.clear()

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None

        logger.info("浏览器已关闭")

    def __enter__(self) -> "Browser":
        self.launch()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── 属性 ────────────────────────────────────────────────────────────

    @property
    def current_page(self) -> PW_Page:
        """当前活跃页面（Playwright Page 对象）。

        由 _active_index 决定返回 _pages 中的哪一个。
        调用方在此 Page 上可直接执行 Playwright 原生方法。
        _pages 为空时抛出 BrowserError。
        _active_index 越界时自动重置为 0。
        """
        if not self._pages:
            raise BrowserError("没有打开的页面")
        if self._active_index >= len(self._pages):
            self._active_index = 0
        return self._pages[self._active_index]

    @property
    def tab_count(self) -> int:
        """当前打开的标签页数量（_pages 的长度）。"""
        return len(self._pages)

    @property
    def active_index(self) -> int:
        """当前活跃标签页索引（0-based，指向 _pages 中的元素）。

        在 new_tab 后被更新为新标签页的索引。
        在 close_tab 后自动切换到相邻标签页。
        在 switch_tab(index) 后被更新为指定索引。
        """
        return self._active_index

    @property
    def all_pages(self) -> list[PW_Page]:
        """所有打开的标签页列表（返回副本，外部修改不影响内部 _pages）。"""
        return list(self._pages)

    # ── 新标签页监听（popup 事件）─────────────────────────────────────────

    def _register_popup_listener(self, page: PW_Page) -> None:
        """为页面注册 popup 事件监听，自动跟踪通过 CLICK 打开的新标签页。

        Playwright 的 page.click() 在点击 target="_blank" 链接
        或触发 window.open() 时，会在此 page 上触发 'popup' 事件。
        监听此事件可以自动将新标签页纳入 _pages 管理。
        """
        page.on('popup', lambda popup: self._on_popup(popup))

    def _on_popup(self, popup: PW_Page) -> None:
        """新标签页被打开时的回调：注册 → 添加 → 切换。

        1. 如果该页面尚未在 _pages 中，则添加并创建 CDP session
        2. 自动切换到新标签页
        3. 为新标签页也注册 popup 监听（链式打开）
        4. 注册 CDP 对话框自动接收
        """
        if popup not in self._pages:
            self._register_popup_listener(popup)
            self._pages.append(popup)
            try:
                self._create_cdp_session(popup)
                self._register_dialog_handler(popup)
            except Exception:
                logger.warning("为新标签页创建 CDP session 失败", exc_info=True)
        self._active_index = len(self._pages) - 1
        logger.info(
            "检测到新标签页，已自动切换至 tab_%d（共 %d 个标签页）",
            self._active_index, len(self._pages),
        )

    # ── CDP 对话框自动接收 ───────────────────────────────────────────────

    def _register_dialog_handler(self, page: PW_Page) -> None:
        """注册 CDP Page.javascriptDialogOpening 事件监听，自动接受对话框。

        JS 弹窗（alert/confirm/prompt/beforeunload）会阻塞 CDP 命令，
        注册此监听后自动调用 handleJavaScriptDialog 消除阻塞。
        """
        cdp = self._cdp_sessions.get(id(page))
        if cdp is None:
            return
        try:
            cdp.send("Page.enable")
            cdp.on("Page.javascriptDialogOpening", self._make_dialog_handler(cdp))
            logger.debug("已注册 CDP 对话框自动接收")
        except Exception as e:
            logger.warning("注册 CDP 对话框监听失败: %s", e)

    @staticmethod
    def _make_dialog_handler(cdp: PW_CDPSession):
        """创建对话框处理闭包。"""
        def handler(params: dict) -> None:
            dialog_type = params.get("type", "alert")
            message = params.get("message", "")
            logger.info("[Dialog] 自动接受 %s: %s", dialog_type, message[:100])
            try:
                # alert/confirm/beforeunload → accept；prompt → dismiss
                accept = dialog_type in ("alert", "confirm", "beforeunload")
                cdp.send("Page.handleJavaScriptDialog", {"accept": accept})
            except Exception as e:
                logger.warning("[Dialog] 处理失败: %s", e)
        return handler

    # ── CDP Session ─────────────────────────────────────────────────────

    def _create_cdp_session(self, page: PW_Page) -> PW_CDPSession:
        """为指定页面创建 CDP session。

        通过 Playwright 的 page.context.new_cdp_session(page) 创建，
        并用 id(page) 作为 key 存储在 _cdp_sessions 字典中。
        perception.py 通过 get_cdp_session() 获取此 session 发送 CDP 命令。
        """
        cdp = page.context.new_cdp_session(page)
        self._cdp_sessions[id(page)] = cdp
        return cdp

    def get_cdp_session(self, page: PW_Page | None = None) -> PW_CDPSession:
        """获取页面的 CDP session（默认当前页面）。

        perception.py 通过此方法获取 CDP session 后，自行发送
        DOM.getDocument、Accessibility.getFullAXTree、DOMSnapshot.captureSnapshot
        等协议命令完成三流采集。

        Args:
            page: 目标页面。默认 None 表示当前活跃页面。

        Returns:
            Playwright CDPSession 对象，支持 cdp.send(method, params) 调用。
        """
        target = page or self.current_page
        page_id = id(target)
        cdp = self._cdp_sessions.get(page_id)
        if cdp is None:
            cdp = self._create_cdp_session(target)
        return cdp

    # ── 元素定位（CDP resolveNode）────────────────────────────────────

    def get_element_info(self, backend_node_id: int) -> str:
        """通过 CDP 直接获取元素的 DOM 节点描述信息（tag + id + class + 关键属性 + 文本）。

        与 resolve_node 不同，此方法使用 CDP `Runtime.callFunctionOn` 直接在
        浏览器侧提取信息，无需生成 CSS 选择器或创建 Playwright Locator，开销更小。

        Args:
            backend_node_id: CDP backendNodeId。

        Returns:
            格式化的 DOM 描述字符串，如：
            `<button#search-btn.btn-primary type=submit>"搜索"`。
            解析失败时返回空字符串。
        """
        try:
            cdp = self.get_cdp_session()
            resolved = cdp.send("DOM.resolveNode", {"backendNodeId": backend_node_id})
            object_id = resolved["object"]["objectId"]

            result = cdp.send("Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": """function() {
                    var t = this.tagName.toLowerCase();
                    var a = [];
                    if (this.id) a.push('#' + this.id);
                    if (this.className && typeof this.className === 'string') {
                        var cls = this.className.trim().split(/\\s+/).filter(function(c){return c.length>0;}).join('.');
                        if (cls) a.push('.' + cls);
                    }
                    var extra = '';
                    var href = this.getAttribute('href') || '';
                    var src = this.getAttribute('src') || '';
                    var val = this.getAttribute('value') || '';
                    var ph = this.getAttribute('placeholder') || '';
                    var tp = this.getAttribute('type') || '';
                    var role = this.getAttribute('role') || '';
                    if (tp) extra += ' type=' + tp;
                    if (role) extra += ' role=' + role;
                    if (ph) extra += ' placeholder=' + JSON.stringify(ph);
                    if (href && href[0] !== '#') extra += ' href=' + href.slice(0,80);
                    if (src) extra += ' src=...' + src.slice(-40);
                    if (val && val.length < 30) extra += ' value=' + JSON.stringify(val);
                    var txt = (this.textContent || '').trim().slice(0, 100);
                    var info = '<' + t;
                    if (a.length) info += ' ' + a.join(' ');
                    info += extra;
                    info += '>';
                    if (txt) info += JSON.stringify(txt);
                    return info;
                }""",
                "returnByValue": True,
            })
            return result["result"]["value"]
        except Exception:
            return ""

    def resolve_node(self, backend_node_id: int, page: PW_Page | None = None) -> ElementHandle:
        """通过 backendNodeId 获取 Playwright ElementHandle。

        使用 CDP `Runtime.callFunctionOn` 在目标元素上执行 JS 生成唯一 CSS
        选择器路径，然后通过 Playwright `locator()` API 获取 ElementHandle。

        策略（解决 CDP objectId 无法直接桥接 Playwright ElementHandle 的问题）：
            1. CDP `DOM.resolveNode({backendNodeId})` → RemoteObject(objectId)
            2. CDP `Runtime.callFunctionOn` 执行 JS → 计算唯一 CSS 选择器
            3. Playwright `page.locator(css_selector).element_handle()`

        Args:
            backend_node_id: CDP 协议中的后端节点 ID。
            page: 目标页面（默认当前页面）。

        Returns:
            Playwright ElementHandle，可执行 `click()` / `fill()` / `hover()` 等。

        Raises:
            BrowserError: 节点不存在或无法生成唯一选择器。
        """
        try:
            cdp = self.get_cdp_session(page)
            resolved = cdp.send("DOM.resolveNode", {"backendNodeId": backend_node_id})
            object_id = resolved["object"]["objectId"]

            # 获取元素的唯一 CSS 选择器
            selector_result = cdp.send("Runtime.callFunctionOn", {
                "objectId": object_id,
                "functionDeclaration": """function() {
                    function getUniqueSelector(el) {
                        if (!el || el.nodeType !== 1) return '';
                        // 有 id 直接用
                        if (el.id) return '#' + CSS.escape(el.id);
                        var path = [];
                        var current = el;
                        while (current && current.nodeType === 1) {
                            var sel = current.tagName.toLowerCase();
                            // 有 id 时终止向上查找
                            if (current.id) {
                                path.unshift('#' + CSS.escape(current.id));
                                break;
                            }
                            // 添加类名（最多 2 个，跳过过长或含数字动态类名）
                            if (current.className && typeof current.className === 'string') {
                                var classes = current.className.trim().split(/\\s+/).filter(function(c) {
                                    return c.length > 0 && c.length < 20 && !/^[a-z]+[0-9]+$/.test(c);
                                });
                                if (classes.length > 0 && classes.length <= 2) {
                                    sel += '.' + classes.map(function(c) { return CSS.escape(c); }).join('.');
                                }
                            }
                            // :nth-of-type 消歧义
                            var parent = current.parentElement;
                            if (parent) {
                                var siblings = Array.from(parent.children).filter(function(s) {
                                    return s.tagName === current.tagName;
                                });
                                if (siblings.length > 1) {
                                    var idx = siblings.indexOf(current) + 1;
                                    sel += ':nth-of-type(' + idx + ')';
                                }
                            }
                            path.unshift(sel);
                            current = parent;
                        }
                        return path.join(' > ');
                    }
                    return getUniqueSelector(this);
                }""",
                "returnByValue": True,
            })
        except Exception as e:
            raise BrowserError(
                f"backendNodeId={backend_node_id} 无法解析: {e}"
            ) from e

        selector = selector_result["result"]["value"]
        if not selector:
            raise BrowserError(
                f"backendNodeId={backend_node_id} 无法生成唯一 CSS 选择器"
            )

        target = page or self.current_page
        locator = target.locator(selector)
        count = locator.count()
        if count == 0:
            raise BrowserError(
                f"backendNodeId={backend_node_id} 选择器 '{selector}' 未匹配到元素"
            )
        if count > 1:
            logger.warning(
                "选择器 '%s' 匹配 %d 个元素（backendNodeId=%d），使用第一个",
                selector, count, backend_node_id,
            )
        return locator.first.element_handle()

    # ── 元素交互 ────────────────────────────────────────────────────────

    def click_element(self, handle: ElementHandle, force: bool = False) -> None:
        """点击一个 ElementHandle。

        Args:
            handle: Playwright ElementHandle。
            force: 为 True 时跳过可见性/启用/稳定性检查（用于弹窗覆盖场景）。
        """
        kwargs = {}
        if force:
            kwargs["force"] = True
        handle.click(**kwargs)

    def click(self, backend_node_id: int, force: bool = False) -> None:
        """通过 backendNodeId 点击元素（CLICK 动作）。

        Args:
            backend_node_id: CDP backendNodeId。
            force: 为 True 时跳过可见性/启用/稳定性检查。
        """
        handle = self.resolve_node(backend_node_id)
        self.click_element(handle, force=force)

    def type_text(self, handle: ElementHandle, text: str) -> None:
        """向 ElementHandle 输入文本（自动清除现有内容，TYPE 动作）。"""
        handle.fill(text)

    def type(self, backend_node_id: int, text: str) -> None:
        """通过 backendNodeId 输入文本（TYPE 动作）。"""
        handle = self.resolve_node(backend_node_id)
        self.type_text(handle, text)

    def hover_element(self, handle: ElementHandle) -> None:
        """悬停在 ElementHandle 上（HOVER 动作）。"""
        handle.hover()

    def hover(self, backend_node_id: int) -> None:
        """通过 backendNodeId 悬停（HOVER 动作）。"""
        handle = self.resolve_node(backend_node_id)
        self.hover_element(handle)

    def mouse_click(self, x: int, y: int) -> None:
        """通过坐标点击（MOUSE_CLICK 动作——Canvas / WebGL / iframe fallback）。"""
        self.current_page.mouse.click(x, y)

    # ── 页面操作 ────────────────────────────────────────────────────────

    def scroll(self, direction: str = "down", amount: int | None = None) -> None:
        """滚动页面（SCROLL 动作）。

        Args:
            direction: "up" 或 "down"。
            amount: 像素数，默认一个视口高度。
        """
        viewport = self.current_page.viewport_size
        if viewport is None:
            delta_y = amount or 800
        else:
            height = viewport.get("height", 800) if isinstance(viewport, dict) else (viewport.height or 800)
            delta_y = amount or height
        if direction == "up":
            delta_y = -delta_y
        self.current_page.mouse.wheel(0, delta_y)

    def press_key(self, key: str) -> None:
        """键盘按键（PRESS 动作——与 TYPE 不同，不针对特定元素）。"""
        self.current_page.keyboard.press(key)

    # ── 导航 ────────────────────────────────────────────────────────────

    def goto(self, url: str) -> None:
        """导航到指定 URL（GOTO 动作）。"""
        self.current_page.goto(url)

    def go_back(self) -> None:
        """浏览器后退（GO_BACK 动作）。"""
        self.current_page.go_back()

    def go_forward(self) -> None:
        """浏览器前进（GO_FORWARD 动作）。"""
        self.current_page.go_forward()

    def reload(self) -> None:
        """刷新当前页面（REFRESH 动作）。"""
        self.current_page.reload()

    # ── 标签页管理 ──────────────────────────────────────────────────────

    def new_tab(self, url: str | None = None) -> int:
        """打开新标签页并自动切换至新页（NEW_TAB 动作）。返回新标签页的索引。

        Args:
            url: 可选，在新标签页中打开的 URL。
        """
        page = self._context.new_page()  # type: ignore[union-attr]
        self._register_popup_listener(page)
        self._create_cdp_session(page)
        self._pages.append(page)
        self._active_index = len(self._pages) - 1
        if url:
            page.goto(url)
        return self._active_index

    def close_tab(self) -> None:
        """关闭当前标签页（CLOSE_TAB 动作）。

        关闭后从 Playwright context 同步 _pages 列表（兼容 page.close 可能
        触发自动清理的情况）。自动切换到相邻标签页。
        只剩一个标签页时抛出异常。
        """
        if len(self._pages) <= 1:
            raise BrowserError("只剩一个标签页，无法关闭")
        page = self.current_page

        # 清理 CDP session
        cdp = self._cdp_sessions.pop(id(page), None)
        if cdp:
            try:
                cdp.detach()
            except Exception:
                pass

        # 关闭页面（Playwright 可能自动从 context.pages 移除）
        page.close()

        # 从 Playwright context 重新同步 _pages，保证索引准确
        if self._context:
            self._pages = list(self._context.pages)
        else:
            self._pages = [p for p in self._pages if p is not page]

        self._active_index = min(self._active_index, len(self._pages) - 1) if self._pages else 0

    def switch_tab(self, index: int) -> None:
        """切换到指定索引的标签页（SWITCH_TAB 动作）。

        Args:
            index: 0-based 标签页索引。

        Raises:
            BrowserError: 索引越界。
        """
        if index < 0 or index >= len(self._pages):
            raise BrowserError(
                f"标签页索引 {index} 超出范围 (0-{len(self._pages) - 1})"
            )
        self._active_index = index
        self.current_page.bring_to_front()

    # ── 信息获取 ────────────────────────────────────────────────────────

    def screenshot(self, full_page: bool = False) -> str:
        """截取当前视口，返回 PIL optimize PNG base64 data URI（SCREENSHOT 动作）。

        流程：page.screenshot() → PIL Image → optimize PNG → base64 → data URI
        使用 PIL save(format='PNG', optimize=True) 压缩，实测 ~6.9% 压缩率，
        零质量损失。（详见设计文档 8.1 节）

        Args:
            full_page: 是否截取整个页面。False（默认）仅当前视口；True 截取完整页面。

        Returns:
            data URI 字符串，格式 'data:image/png;base64,...'。
            可直接作为 VLM 的 image_url content part。
        """
        # scale="css" 确保截图尺寸与 CDP 坐标单位一致（CSS 像素）
        # 默认 scale="device" 在高 DPI 屏上会产生产物图像素 > CSS 像素，
        # 导致 SoM 标注的坐标与截图元素实际位置不对齐。
        raw = self.current_page.screenshot(
            type="png", full_page=full_page, scale="css",
        )
        img = Image.open(io.BytesIO(raw))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    def find_elements_by_text(self, text: str, exact: bool = False) -> list[dict]:
        """查找视口内所有包含指定文本的可见元素，返回 DOM 信息 + 坐标。

        使用 page.evaluate() 直接在浏览器侧遍历 DOM，不依赖 CDP snapshot，
        因此能捕获到没有被 SoM 标记的元素（如动态菜单项、Shadow DOM 内容）。

        Args:
            text: 要搜索的文本。
            exact: True 时精确匹配，False 时子串匹配。

        Returns:
            list[dict]，每项包含：
                tag: 标签名（小写）
                id: 元素 id
                classes: 类名列表
                text: 文本内容（前 200 字符）
                x, y, w, h: 视口坐标（CSS 像素）
        """
        import json
        search_text = json.dumps(text, ensure_ascii=False)
        return self.current_page.evaluate(f"""() => {{
            const results = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT, null, false
            );
            while (walker.nextNode()) {{
                const el = walker.currentNode;
                // 跳过隐藏元素
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') continue;

                const textContent = (el.textContent || '').trim();
                if (!textContent) continue;

                // 文本匹配
                const matches = {('textContent === ' + search_text) if exact else ('textContent.includes(' + search_text + ')')};
                if (!matches) continue;

                var cls = [];
                if (el.className && typeof el.className === 'string') {{
                    cls = el.className.trim().split(/\\\s+/).filter(function(c){{return c.length>0;}});
                }}
                results.push({{
                    tag: el.tagName.toLowerCase(),
                    id: el.id || '',
                    classes: cls,
                    text: textContent.slice(0, 200),
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                }});
            }}
            return results;
        }}""")

    def extract_text(self, backend_node_id: int | None = None) -> str:
        """提取文本内容（EXTRACT 动作）。

        Args:
            backend_node_id:
                - None（默认）: 提取页面全文（document.body.innerText），适合总结类任务
                - 有值: 提取指定 SoM 元素的 innerText

        Returns:
            提取的文本内容字符串。
        """
        if backend_node_id is None:
            return self.current_page.evaluate("document.body.innerText")
        handle = self.resolve_node(backend_node_id)
        return handle.inner_text()

    def find_text(self, text: str, exact: bool = False) -> ElementHandle | None:
        """页内文本搜索（FIND 动作）。

        使用 Playwright get_by_text() 在 DOM 层精确定位文本，
        找到后自动 scroll_into_view_if_needed() 滚动到目标位置。
        解决 VLM 视觉感知在长页面中的低效搜索问题。

        Args:
            text: 搜索文本。
            exact: 是否精确匹配。False（默认）执行子串匹配；
                   True 要求完全匹配（大小写不敏感）。

        Returns:
            匹配元素的 ElementHandle。找到后有焦点（已滚动到视口）。
            未找到时返回 None。
        """
        try:
            locator = self.current_page.get_by_text(text, exact=exact)
            if locator.count() == 0:
                return None
            handle = locator.first.element_handle()
            if handle:
                handle.scroll_into_view_if_needed()
            return handle
        except Exception:
            return None

    def js_eval(self, js_code: str) -> Any:
        """执行 JavaScript 代码。

        用于无法通过 Playwright 原生原子操作实现的自定义 DOM 操作。
        应尽量少用，优先使用 Playwright 原生方法。

        Args:
            js_code: 要执行的 JavaScript 代码字符串。

        Returns:
            JavaScript 表达式的返回值（JSON 可序列化的值）。
        """
        return self.current_page.evaluate(js_code)
