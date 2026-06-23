"""记忆层 —— agent 和 subagent 共享的内存管理器。

observations — VLM 维护，子任务内自然语言摘要
working — VLM/Executor 维护，操作步骤记录
knowledge — 预留，暂不使用
"""

from typing import Any

from classic_web_agent.common.types import KnowledgeItem, MemoryEntry


class Memory:
    """三层记忆管理器。"""

    def __init__(self) -> None:
        self.knowledge: dict[str, list[KnowledgeItem]] = {}
        self.observations: list[str] = []
        self.working: list[MemoryEntry] = []
        self.url_stack: list[str] = []
        self.step_index: int = 0

    # ── Knowledge ─────────────────────────────────────────────────

    def add_knowledge(self, category: str, key: str, value: str,
                      source_url: str = "", sub_task_id: int = 0) -> None:
        item = KnowledgeItem(category=category, key=key, value=value,
                             source_url=source_url, sub_task_id=sub_task_id)
        if category not in self.knowledge:
            self.knowledge[category] = []
        self.knowledge[category].append(item)

    def get_knowledge(self, category: str | None = None,
                      key: str | None = None) -> list[KnowledgeItem]:
        if category and key:
            return [i for i in self.knowledge.get(category, []) if i.key == key]
        if category:
            return list(self.knowledge.get(category, []))
        result: list[KnowledgeItem] = []
        for items in self.knowledge.values():
            result.extend(items)
        return result

    def format_knowledge_summary(self) -> str:
        lines: list[str] = []
        for category, items in self.knowledge.items():
            lines.append(f"── {category} ──")
            for item in items:
                src = f" ({item.source_url})" if item.source_url else ""
                lines.append(f"  {item.key}: {item.value}{src}")
            lines.append("")
        return "\n".join(lines).strip()

    def clear_knowledge(self) -> None:
        self.knowledge.clear()

    # ── Observations ─────────────────────────────────────────────

    def add_observation(self, text: str) -> None:
        self.observations.append(text)

    def get_observations(self) -> str:
        return "\n".join(self.observations)

    def clear_observations(self) -> None:
        self.observations.clear()

    # ── Working ─────────────────────────────────────────────────

    def add_working(self, entry: MemoryEntry) -> None:
        self.working.append(entry)

    def get_working(self, limit: int | None = None) -> list[MemoryEntry]:
        if limit is not None:
            return self.working[-limit:]
        return list(self.working)

    def clear_working(self) -> None:
        self.working.clear()

    # ── URL 栈 ──────────────────────────────────────────────────

    def push_url(self, url: str) -> None:
        self.url_stack.append(url)

    def pop_url(self) -> str | None:
        return self.url_stack.pop() if self.url_stack else None

    def peek_url(self) -> str | None:
        return self.url_stack[-1] if self.url_stack else None
