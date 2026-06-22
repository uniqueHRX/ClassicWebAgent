"""结构化日志与轨迹记录 —— JSONL 轨迹 + 分步截图管理。

设计详见 docs/design.md §5：
- 控制台输出关键步骤信息
- 内存记录 AgentStep 轨迹列表
- 阶段二：写入 JSONL 文件 + 管理截图目录
"""

from pathlib import Path
from typing import Any

from classic_web_agent.agent.types import AgentStep, TaskResult


class Logger:
    """日志与轨迹记录器。"""

    def __init__(self) -> None:
        self.steps: list[AgentStep] = []

    def start_task(self, task: str) -> None:
        """记录任务开始。"""
        print(f"[Agent] 任务开始: {task}")

    def log_step(self, step: AgentStep) -> None:
        """记录单步轨迹。"""
        self.steps.append(step)
        action_name = step.action.action_type if step.action else "NONE"
        result_msg = step.result.message if step.result else ""
        print(f"[Agent]  步骤 {step.step_index}: {action_name} → {result_msg}")

    def end_task(self, result: TaskResult) -> None:
        """记录任务结束。"""
        status = "完成" if result.success else "失败"
        print(f"[Agent] 任务{status}: {result.summary} (共 {result.total_steps} 步)")
