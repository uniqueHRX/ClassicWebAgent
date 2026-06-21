"""记忆层 (CoALA Memory) —— 工作记忆 + 会话记忆 + 上下文窗口管理。

设计详见 docs/design.md §1.1：
- 工作记忆（working）：当前任务上下文，AgentStep 轨迹
- 会话记忆（session）：跨任务的持久记忆（阶段二）
- URL 栈（url_stack）：导航历史追踪
"""

from typing import Any

from classic_web_agent.agent.types import MemoryEntry


class Memory:
    """Agent 记忆管理器。"""

    def __init__(self) -> None:
        self.working: list[MemoryEntry] = []      # 工作记忆
        self.session: list[MemoryEntry] = []      # 会话记忆（阶段二扩展）
        self.url_stack: list[str] = []             # URL 导航栈

    # ── 工作记忆 ────────────────────────────────────────────────────────

    def add_working(self, entry: MemoryEntry) -> None:
        """添加条目到工作记忆。"""
        self.working.append(entry)

    def get_working(self, limit: int | None = None) -> list[MemoryEntry]:
        """获取工作记忆条目，可限制返回数量（取最近 N 条）。"""
        if limit is not None:
            return self.working[-limit:]
        return list(self.working)

    def clear_working(self) -> None:
        """清空工作记忆。"""
        self.working.clear()

    # ── 会话记忆 ────────────────────────────────────────────────────────

    def add_session(self, entry: MemoryEntry) -> None:
        """添加条目到会话记忆。"""
        self.session.append(entry)

    def get_session(self) -> list[MemoryEntry]:
        """获取会话记忆。"""
        return list(self.session)

    def clear_session(self) -> None:
        """清空会话记忆。"""
        self.session.clear()

    # ── URL 栈 ──────────────────────────────────────────────────────────

    def push_url(self, url: str) -> None:
        """将 URL 压入导航栈。"""
        self.url_stack.append(url)

    def pop_url(self) -> str | None:
        """弹出栈顶 URL。"""
        return self.url_stack.pop() if self.url_stack else None

    def peek_url(self) -> str | None:
        """查看栈顶 URL（不弹出）。"""
        return self.url_stack[-1] if self.url_stack else None
