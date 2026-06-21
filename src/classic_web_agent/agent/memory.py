"""记忆层 (CoALA Memory) —— 工作记忆 + 会话记忆 + 上下文窗口管理。"""

from typing import Any

from classic_web_agent.agent.types import MemoryEntry


class Memory:
    """Agent 记忆管理器。"""

    def __init__(self) -> None:
        self.working: list[MemoryEntry] = []   # 工作记忆
        self.session: list[MemoryEntry] = []   # 会话记忆
        self.url_stack: list[str] = []         # URL 导航栈
