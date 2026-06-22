"""Agent 数据模型 —— 集中定义核心数据结构。

包含：PageState, Action, ActionResult, MemoryEntry, AgentStep, PlanStep, Plan, TaskResult。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PageState:
    """页面状态（感知模块输出）。"""

    screenshot: str = ""        # base64 data URI，VLM 输入
    url: str = ""               # 当前页面 URL
    title: str = ""             # 页面标题
    tree_text: str = ""         # 可交互元素树文本（含 backendNodeId）
    current_tab_id: str = ""    # 当前标签页标识（如 "tab_0"）
    tabs_list: str = ""         # 所有标签页的文本描述


@dataclass
class Action:
    """动作定义 —— 统一结构，不拆分外部/内部子类。

    Fields:
        action_type: 动作类型名称（如 "CLICK"、"TYPE"、"DONE"）。
        element_id: SoM 元素引用（外部动作），CDP backendNodeId。
        text: 文本参数（TYPE / THINK / DONE / FAIL / FIND）。
        extra: 扩展参数字典，承载类型相关数据：
            - MOUSE_CLICK: {"x": int, "y": int}
            - SCROLL: {"direction": "up" | "down"}
            - WAIT: {"condition": "load" | "network_idle" | "selector"}
            - GOTO: {"url": str}
            - PRESS: {"key": str}
            - NEW_TAB: {"url": str | None}
            - SWITCH_TAB: {"tab_index": int}
            - EXTRACT: {"element_id": int | None}
            - FIND: {"text": str, "exact": bool}
            - REMEMBER: {"key": str, "value": str}
            - RECALL: {"query": str}
        confidence: VLM 生成此动作时的置信度（默认 1.0）。
    """

    action_type: str = ""
    element_id: int | None = None
    text: str | None = None
    extra: dict[str, Any] | None = None
    confidence: float = 1.0


@dataclass
class ActionResult:
    """动作执行结果。

    Fields:
        success: 执行是否成功。
        message: 状态描述信息。
        data: 结果负载数据，按动作类型约定：
            - SCREENSHOT → str (data URI)
            - EXTRACT → str (提取的文本)
            - FIND → dict (匹配结果，含 found/selector 键)
            - NEW_TAB → int (新标签页索引)
            - 其他动作 → None
    """

    success: bool = True
    message: str = ""
    data: Any = None


@dataclass
class MemoryEntry:
    """记忆条目。"""

    role: str = ""          # "user" / "assistant" / "system" / "observation"
    content: str = ""
    metadata: dict[str, Any] | None = None


@dataclass
class KnowledgeItem:
    """一条结构化的知识条目。

    LLM 在收到 VLM 的 observations 后加工存入 knowledge，
    用于最终汇总报告生成。

    Fields:
        category: 类别（如 "论文摘要"、"价格信息"、"评价"）。
        key: 标识（如 "论文A"、"京东_价格"）。
        value: 值（自然语言文本）。
        source_url: 来源页面 URL。
        sub_task_id: 所属子任务 ID。
    """

    category: str = ""
    key: str = ""
    value: str = ""
    source_url: str = ""
    sub_task_id: int = 0


@dataclass
class AgentStep:
    """单步 ReAct 轨迹记录。"""

    step_index: int = 0
    action: Action | None = None
    result: ActionResult | None = None
    state_before: PageState | None = None
    state_after: PageState | None = None


@dataclass
class PlanStep:
    """粗粒度计划步骤。

    Fields:
        id: 步骤序号。
        goal: 本步骤目标（自然语言描述）。
        fallback: 自救提示 —— VLM 执行失败时先尝试此策略。
        status: pending / active / completed / failed。
    """

    id: int = 0
    goal: str = ""
    fallback: str = ""
    status: str = "pending"  # pending | active | completed | failed


@dataclass
class Plan:
    """粗粒度计划 —— PlanStep 的容器。"""

    steps: list[PlanStep] = field(default_factory=list)

    @property
    def current_step(self) -> PlanStep | None:
        """返回第一个 pending 的步骤。"""
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    @property
    def remaining_steps(self) -> list[PlanStep]:
        """返回所有未完成的步骤。"""
        return [s for s in self.steps if s.status != "completed" and s.status != "failed"]


@dataclass
class TaskResult:
    """任务执行最终结果。"""

    success: bool = True
    summary: str = ""
    total_steps: int = 0
