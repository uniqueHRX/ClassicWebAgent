"""执行器 —— 将 LLM 输出转化为 Playwright 原子操作。"""

from typing import Any

from classic_web_agent.agent.action import ActionSpace
from classic_web_agent.browser import Browser


class Executor:
    """动作执行器。"""

    def __init__(self, action_space: ActionSpace, browser: Browser) -> None:
        self.action_space = action_space
        self.browser = browser
