"""Agent 数据模型 —— agent 和 subagent 共享的核心数据结构。

包含：PageState, Action, ActionResult, MemoryEntry, KnowledgeItem,
      AgentStep, PlanStep, Plan, TaskResult。
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
        extra: 扩展参数字典。
        confidence: VLM 生成此动作时的置信度（默认 1.0）。
    """

    action_type: str = ""
    element_id: int | None = None
    text: str | None = None
    extra: dict[str, Any] | None = None
    confidence: float = 1.0


@dataclass
class ActionResult:
    """动作执行结果。"""

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
    """结构化的知识条目。LLM 汇总报告用。"""

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
    """粗粒度计划步骤。"""

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
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    @property
    def remaining_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.status not in ("completed", "failed")]


@dataclass
class TaskResult:
    """任务执行最终结果。"""

    success: bool = True
    summary: str = ""
    total_steps: int = 0


# ── Director 相关数据类型 ──────────────────────────────────────


@dataclass
class TodoItem:
    """Director 的子任务条目。"""

    id: int = 0
    goal: str = ""
    status: str = "pending"  # pending | in_progress | completed | failed
    summary: str = ""


@dataclass
class NextAction:
    """Director 的下一步动作。"""

    type: str = "done"       # "sub_task" | "done"
    description: str = ""


@dataclass
class DirectorOutput:
    """Director LLM 调用的结构化输出。"""

    thinking: str = ""
    task_plan: str = ""      # 详实的任务计划书（首次 plan 必填）
    todo_list: list[TodoItem] = field(default_factory=list)
    next: NextAction = field(default_factory=NextAction)
    raw: str = ""            # LLM 原始返回文本（调试用）
