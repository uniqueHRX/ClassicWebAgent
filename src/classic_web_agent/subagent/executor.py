"""执行器 —— 将 Action 转化为 Playwright 原子操作。

设计详见 docs/action-space.md：
- 注入 Browser 和 Memory，统一调度所有 21 个动作
- 16 个外部动作 → browser.py 原子方法
- 5 个内部动作 → memory.py 或直接返回
- 所有异常被捕获并转为 ActionResult(success=False)，不抛出

用法:
    executor = Executor(action_space, browser, memory)
    result = executor.execute(Action(action_type="CLICK", element_id=1548))
"""

import logging
from typing import Any

from classic_web_agent.common.action import ActionSpace
from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import Action, ActionResult, MemoryEntry
from classic_web_agent.browser import Browser, BrowserError

logger = logging.getLogger(__name__)

# Wait 动作支持的 condition 值（Playwright 规范：无下划线）
_VALID_WAIT_CONDITIONS = frozenset({"load", "domcontentloaded", "networkidle", "commit"})

# WAIT 动作的超时（毫秒）。Playwright 默认 30s 过长，
# 持续网络活动（长轮询/SSE）可能导致 networkidle 永不触发。
# 10s 足够大多数页面完成 domcontentloaded + load，
# 超时后返回 success（页面已处于当前 load state），不阻塞流程。
_WAIT_TIMEOUT_MS = 10_000


class Executor:
    """动作执行器 —— Action → Playwright 原子操作 + 内部动作。"""

    def __init__(
        self,
        action_space: ActionSpace,
        browser: Browser | None = None,
        memory: Memory | None = None,
    ) -> None:
        """初始化执行器。

        Args:
            action_space: 动作空间管理器，用于合法性校验和去重检测。
            browser: 浏览器驱动。外部动作需要；内部动作可省略。
            memory: 记忆管理器。内部动作（THINK/REMEMBER/RECALL）需要。
        """
        self.action_space = action_space
        self.browser = browser
        self.memory = memory
        self._consecutive_goto_failures: int = 0
        self._max_goto_retries: int = 3

    # ── 公开入口 ────────────────────────────────────────────────────────

    def execute(self, action: Action) -> ActionResult:
        """执行单个动作（外部 + 内部统一入口）。

        路由逻辑：
            - THINK / REMEMBER / RECALL → memory 操作
            - DONE / FAIL → 终端动作，直接返回
            - 16 个外部动作 → browser.py 对应方法
            - 所有异常捕获为 ActionResult(success=False)

        Args:
            action: 待执行的动作。

        Returns:
            ActionResult，包含执行状态和结果数据。
        """
        atype = action.action_type.upper() if action.action_type else ""

        # ── 内部动作 ─────────────────────────────────────────────────
        if atype == "THINK":
            return self._execute_THINK(action)
        if atype == "REMEMBER":
            return self._execute_REMEMBER(action)
        if atype == "RECALL":
            return self._execute_RECALL(action)
        if atype == "DONE":
            return self._execute_DONE(action)
        if atype == "FAIL":
            return self._execute_FAIL(action)

        # ── 外部动作 ─────────────────────────────────────────────────
        if not self._check_browser_ready():
            return ActionResult(
                success=False,
                message=f"浏览器未启动，无法执行 {atype}",
            )

        handler = self._get_handler(atype)
        if handler is None:
            return ActionResult(
                success=False,
                message=f"未知动作类型: {action.action_type}",
            )

        try:
            return handler(action)
        except BrowserError as e:
            logger.warning("BrowserError 在 %s: %s", atype, e)
            return ActionResult(success=False, message=f"浏览器操作失败: {e}")
        except Exception as e:
            logger.error("执行 %s 时异常: %s", atype, e, exc_info=True)
            return ActionResult(success=False, message=f"执行异常: {e}")

    # ── 内部动作处理器 ───────────────────────────────────────────────

    def _execute_THINK(self, action: Action) -> ActionResult:
        """记录推理过程到工作记忆。"""
        thought = action.text or ""
        if self.memory:
            self.memory.add_working(
                MemoryEntry(role="assistant", content=f"[THINK] {thought}")
            )
        logger.info("[THINK] %s", thought)
        return ActionResult(success=True, message=f"THINK: {thought}")

    def _execute_REMEMBER(self, action: Action) -> ActionResult:
        """将关键信息存入工作记忆。"""
        extra = action.extra or {}
        key = extra.get("key", "")
        value = extra.get("value", "")
        if not key:
            return ActionResult(success=False, message="REMEMBER 缺少 key")
        entry = MemoryEntry(
            role="assistant",
            content=f"REMEMBER({key}): {value}",
            metadata={"key": key, "value": value},
        )
        if self.memory:
            self.memory.add_working(entry)
        logger.info("[REMEMBER] %s = %s", key, value)
        return ActionResult(success=True, message=f"记忆: {key} = {value}")

    def _execute_RECALL(self, action: Action) -> ActionResult:
        """从工作记忆中检索之前存储的信息。"""
        extra = action.extra or {}
        query = extra.get("query", "")
        if not query:
            return ActionResult(success=False, message="RECALL 缺少 query")
        found: list[MemoryEntry] = []
        if self.memory:
            for entry in self.memory.get_working():
                if query.lower() in entry.content.lower():
                    found.append(entry)
        result_text = "\n".join(e.content for e in found) if found else "(无匹配)"
        logger.info("[RECALL] '%s' → %d 条", query, len(found))
        return ActionResult(
            success=bool(found),
            message=f"检索 '{query}': {len(found)} 条",
            data=result_text,
        )

    def _execute_DONE(self, action: Action) -> ActionResult:
        """任务完成。"""
        msg = action.text or "任务完成"
        logger.info("[DONE] %s", msg)
        return ActionResult(success=True, message=msg)

    def _execute_FAIL(self, action: Action) -> ActionResult:
        """任务失败。"""
        msg = action.text or "任务失败"
        logger.info("[FAIL] %s", msg)
        return ActionResult(success=True, message=msg)

    # ── 外部动作处理器 ───────────────────────────────────────────────

    def _execute_CLICK(self, action: Action) -> ActionResult:
        if action.element_id is None:
            return ActionResult(success=False, message="CLICK 缺少 element_id")

        tab_count_before = self.browser.tab_count
        tab_index_before = self.browser.active_index

        self.browser.click(action.element_id)

        # 检测是否打开了新标签页（popup 监听器已自动切换到新页）
        tab_count_after = self.browser.tab_count
        if tab_count_after > tab_count_before:
            new_index = tab_count_after - 1
            return ActionResult(
                success=True,
                message=(
                    f"点击元素 {action.element_id}（链接在新标签页打开，"
                    f"已自动切换到 tab_{new_index}）"
                ),
            )
        # 检测是否在当前标签页内发生了导航（URL 可能在下一步变化）
        tab_index_after = self.browser.active_index
        if tab_index_after != tab_index_before:
            return ActionResult(
                success=True,
                message=(
                    f"点击元素 {action.element_id}（系统自动切换到 "
                    f"tab_{tab_index_after}）"
                ),
            )

        return ActionResult(success=True, message=f"点击元素 {action.element_id}")

    def _execute_TYPE(self, action: Action) -> ActionResult:
        if action.element_id is None:
            return ActionResult(success=False, message="TYPE 缺少 element_id")
        text = action.text or ""
        if not text:
            return ActionResult(success=False, message="TYPE 缺少输入文本")
        self.browser.type(action.element_id, text)
        return ActionResult(
            success=True,
            message=f"向元素 {action.element_id} 输入文本 ({len(text)} 字符)",
        )

    def _execute_HOVER(self, action: Action) -> ActionResult:
        if action.element_id is None:
            return ActionResult(success=False, message="HOVER 缺少 element_id")
        self.browser.hover(action.element_id)
        return ActionResult(success=True, message=f"悬停元素 {action.element_id}")

    def _execute_MOUSE_CLICK(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        x = extra.get("x")
        y = extra.get("y")
        if x is None or y is None:
            return ActionResult(success=False, message="MOUSE_CLICK 缺少坐标 (x, y)")
        self.browser.mouse_click(int(x), int(y))
        return ActionResult(success=True, message=f"坐标点击 ({x}, {y})")

    def _execute_SCROLL(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        direction = extra.get("direction", "down")
        if direction not in ("up", "down"):
            return ActionResult(
                success=False,
                message=f"SCROLL direction 必须为 up/down，收到 '{direction}'",
            )
        self.browser.scroll(direction)
        return ActionResult(success=True, message=f"滚动 {direction}")

    def _execute_PRESS(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        key = extra.get("key", "")
        if not key:
            return ActionResult(success=False, message="PRESS 缺少 key")
        self.browser.press_key(key)
        return ActionResult(success=True, message=f"按键 {key}")

    def _execute_WAIT(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        condition = extra.get("condition", "load")
        if condition not in _VALID_WAIT_CONDITIONS:
            return ActionResult(
                success=False,
                message=f"WAIT condition 无效: '{condition}'，"
                f"可选: {', '.join(sorted(_VALID_WAIT_CONDITIONS))}",
            )
        page = self.browser.current_page
        try:
            page.wait_for_load_state(condition, timeout=_WAIT_TIMEOUT_MS)
            return ActionResult(success=True, message=f"等待 {condition} 完成")
        except Exception as e:
            # 超时不等同于失败——页面可能已有部分内容（load/domcontentloaded 已触发），
            # 只是 networkidle 因持续网络活动（长轮询/SSE/广告）未达成。
            # 返回 success 让 VLM 用下一步的截图+DOM树判断页面是否可用。
            logger.warning(
                "WAIT(%s) 超时 (%dms): %s，页面可能仍有内容，继续执行",
                condition, _WAIT_TIMEOUT_MS, e,
            )
            return ActionResult(
                success=True,
                message=f"等待 {condition}（超时 {_WAIT_TIMEOUT_MS // 1000}s，已按当前状态继续）",
            )

    def _execute_GOTO(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        url = extra.get("url", "")
        if not url:
            return ActionResult(success=False, message="GOTO 缺少 url")

        # 连续 GOTO 失败检测，防止无限重试不可达的 URL
        if self._consecutive_goto_failures >= self._max_goto_retries:
            self._consecutive_goto_failures = 0
            logger.warning("连续 %d 次 GOTO 失败，跳过: %s", self._max_goto_retries, url)
            return ActionResult(
                success=False,
                message=f"连续{self._max_goto_retries}次导航失败，跳过: {url}",
            )

        try:
            self.browser.goto(url)
            self._consecutive_goto_failures = 0
            return ActionResult(success=True, message=f"导航到 {url}")
        except Exception as e:
            self._consecutive_goto_failures += 1
            logger.warning("GOTO 失败 (第%d次): %s — %s",
                           self._consecutive_goto_failures, url, e)
            return ActionResult(
                success=False,
                message=f"导航失败 ({self._consecutive_goto_failures}/{self._max_goto_retries}): {e}",
            )

    def _execute_GO_BACK(self, action: Action) -> ActionResult:
        self.browser.go_back()
        return ActionResult(success=True, message="后退")

    def _execute_GO_FORWARD(self, action: Action) -> ActionResult:
        self.browser.go_forward()
        return ActionResult(success=True, message="前进")

    def _execute_NEW_TAB(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        url = extra.get("url")
        idx = self.browser.new_tab(url)
        msg = f"新建标签页 [{idx}]"
        if url:
            msg += f" → {url}"
        return ActionResult(success=True, message=msg, data=idx)

    def _execute_CLOSE_TAB(self, action: Action) -> ActionResult:
        self.browser.close_tab()
        return ActionResult(success=True, message="关闭当前标签页")

    def _execute_SWITCH_TAB(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        index = extra.get("tab_index")
        if index is None:
            return ActionResult(success=False, message="SWITCH_TAB 缺少 tab_index")
        self.browser.switch_tab(int(index))
        return ActionResult(success=True, message=f"切换到标签页 [{index}]")

    def _execute_SCREENSHOT(self, action: Action) -> ActionResult:
        data_uri = self.browser.screenshot()
        return ActionResult(
            success=True,
            message=f"截图完成 ({len(data_uri)} 字符)",
            data=data_uri,
        )

    def _execute_EXTRACT(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        element_id = extra.get("element_id", action.element_id)
        text = self.browser.extract_text(element_id)
        return ActionResult(
            success=True,
            message=f"提取文本 ({len(text)} 字符)",
            data=text,
        )

    def _execute_FIND(self, action: Action) -> ActionResult:
        extra = action.extra or {}
        text = extra.get("text", "")
        if not text:
            return ActionResult(success=False, message="FIND 缺少 text")
        exact = bool(extra.get("exact", False))
        handle = self.browser.find_text(text, exact=exact)
        if handle is not None:
            return ActionResult(
                success=True,
                message=f"找到文本 '{text}'",
                data={"found": True},
            )
        return ActionResult(
            success=False,
            message=f"未找到文本 '{text}'",
            data={"found": False},
        )

    # ── 辅助方法 ─────────────────────────────────────────────────────

    def _get_handler(self, atype: str):
        """按动作类型名查找对应的 _execute_* 方法。"""
        method_name = f"_execute_{atype}"
        return getattr(self, method_name, None)

    def _check_browser_ready(self) -> bool:
        """检查浏览器是否已就绪。"""
        return self.browser is not None and self.browser._browser is not None
