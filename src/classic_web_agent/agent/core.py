"""Agent 主循环 —— ReAct 闭环。

observe → plan → execute → verify
"""

from typing import Any


class Agent:
    """WebAgent 主控制器。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def run(self, task: str) -> None:
        """执行任务主循环。"""
        raise NotImplementedError
