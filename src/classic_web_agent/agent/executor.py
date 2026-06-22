"""执行器 —— 将 Action 转化为 Playwright 原子操作。

设计详见 docs/action-space.md：
- 遍历 ActionType → 调用 browser.py 相应原子方法
- 执行前后绑定：校验 → 执行 → 结果封装

阶段一（stub）：不调用 Playwright，直接返回 ActionResult(success=True)。
"""

from typing import Any

from classic_web_agent.agent.action import ActionSpace
from classic_web_agent.agent.types import Action, ActionResult
from classic_web_agent.browser import Browser


class Executor:
    """动作执行器 —— Action → Playwright 原子操作。"""

    def __init__(
        self,
        action_space: ActionSpace,
        browser: Browser | None = None,
    ) -> None:
        self.action_space = action_space
        self.browser = browser

    def execute(self, action: Action) -> ActionResult:
        """执行动作。

        阶段一（stub）：不调用 Playwright，直接返回成功。
        阶段二：按 action_type 路由到 browser.py 对应方法。
        """
        return ActionResult(
            success=True,
            message=f"[stub] 执行 {action.action_type}",
        )
