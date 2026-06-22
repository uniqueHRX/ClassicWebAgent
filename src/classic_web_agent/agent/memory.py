"""记忆层 —— 双层 Agent 的内存管理器。

参考 browser-use 的 AgentOutput.memory 模式，VLM 生成自然语言摘要记录观察。

三类记忆：
1. Observations（observations）— VLM 维护，子任务内自然语言摘要
2. Working（working）— VLM/Executor 维护，操作步骤记录
3. Knowledge（knowledge）— 预留，暂不使用（LLM 持久上下文自明）
"""

from typing import Any

from classic_web_agent.agent.types import KnowledgeItem, MemoryEntry


class Memory:
    """双层 Agent 的三类记忆管理器。"""

    def __init__(self) -> None:
        # 预留，暂不使用：结构化知识库
        # （LLM 有持久上下文，observations 在消息历史中自明）
        self.knowledge: dict[str, list[KnowledgeItem]] = {}

        # VLM 维护：子任务内的观察摘要（每次调用清空）
        self.observations: list[str] = []

        # VLM 维护：操作步骤记录
        self.working: list[MemoryEntry] = []

        # 导航栈
        self.url_stack: list[str] = []

        # 步骤计数
        self.step_index: int = 0

    # ── Knowledge（LLM 使用）──────────────────────────────────────────

    def add_knowledge(
        self,
        category: str,
        key: str,
        value: str,
        source_url: str = "",
        sub_task_id: int = 0,
    ) -> None:
        """添加一条结构化知识。

        LLM 在收到 VLM 返回的 observations 后，将摘要加工为结构化知识存入。
        """
        item = KnowledgeItem(
            category=category,
            key=key,
            value=value,
            source_url=source_url,
            sub_task_id=sub_task_id,
        )
        if category not in self.knowledge:
            self.knowledge[category] = []
        self.knowledge[category].append(item)

    def get_knowledge(
        self,
        category: str | None = None,
        key: str | None = None,
    ) -> list[KnowledgeItem]:
        """按类别/标识检索知识库。

        Args:
            category: 类别筛选（None 表示全部）。
            key: 标识筛选（None 表示全部）。

        Returns:
            匹配的 KnowledgeItem 列表。
        """
        if category and key:
            return [
                item
                for item in self.knowledge.get(category, [])
                if item.key == key
            ]
        if category:
            return list(self.knowledge.get(category, []))
        # 返回全部
        result: list[KnowledgeItem] = []
        for items in self.knowledge.values():
            result.extend(items)
        return result

    def format_knowledge_summary(self) -> str:
        """将知识库格式化为文本摘要，供 LLM 生成最终报告。

        示例输出:
            ── 价格信息 ──
              京东: 5999元 (来源: jd.com)
              淘宝: 5799元 (来源: taobao.com)
            ── 评价信息 ──
              京东: 4.5星
        """
        lines: list[str] = []
        for category, items in self.knowledge.items():
            lines.append(f"── {category} ──")
            for item in items:
                src = f" ({item.source_url})" if item.source_url else ""
                lines.append(f"  {item.key}: {item.value}{src}")
            lines.append("")
        return "\n".join(lines).strip()

    def clear_knowledge(self) -> None:
        """清空知识库（新任务开始）。"""
        self.knowledge.clear()

    # ── Observations（VLM 使用）────────────────────────────────────────

    def add_observation(self, text: str) -> None:
        """追加一条观察摘要。

        由 VLM 的 REMEMBER 动作触发。内容是 VLM 生成的自然语言摘要，
        不是原始 EXTRACT 输出。
        """
        self.observations.append(text)

    def get_observations(self) -> str:
        """获取所有观察摘要的拼接文本。

        VLM 子任务结束时返回给 LLM。
        """
        return "\n".join(self.observations)

    def clear_observations(self) -> None:
        """清空观察日志。每次子任务开始前调用。"""
        self.observations.clear()

    # ── Working ──────────────────────────────────────────────────────

    def add_working(self, entry: MemoryEntry) -> None:
        """添加条目到操作记录。"""
        self.working.append(entry)

    def get_working(self, limit: int | None = None) -> list[MemoryEntry]:
        """获取操作记录，可限制返回数量（取最近 N 条）。"""
        if limit is not None:
            return self.working[-limit:]
        return list(self.working)

    def clear_working(self) -> None:
        """清空操作记录（子任务开始）。"""
        self.working.clear()

    # ── URL 栈 ────────────────────────────────────────────────────────

    def push_url(self, url: str) -> None:
        """将 URL 压入导航栈。"""
        self.url_stack.append(url)

    def pop_url(self) -> str | None:
        """弹出栈顶 URL。"""
        return self.url_stack.pop() if self.url_stack else None

    def peek_url(self) -> str | None:
        """查看栈顶 URL（不弹出）。"""
        return self.url_stack[-1] if self.url_stack else None
