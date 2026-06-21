"""LLM 规划器 —— ReAct 风格逐步推理 + 层级规划。

设计详见 docs/model-routing.md：
- create_plan: LLM 一次性生成粗粒度步骤链
- plan: 基于当前状态决策下一步动作
- recover: VLM 求救时恢复
- replan: 重规划剩余步骤
- review_plan: 步间审查

阶段一（stub）：所有方法返回固定值，不调用 LLM。
"""

from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.agent.memory import Memory
from classic_web_agent.agent.types import (
    Action,
    PageState,
    Plan,
    PlanStep,
)


class Planner:
    """LLM 规划器。"""

    def __init__(self, memory: Memory, llm: LLMClient | None = None) -> None:
        self.memory = memory
        self.llm = llm

    def create_plan(self, task: str) -> Plan:
        """创建粗粒度计划。

        阶段一（stub）：返回包含任务的单步计划。
        阶段二：调用 LLM 生成步骤链。
        """
        return Plan(steps=[PlanStep(id=0, goal=task)])

    def plan(self, state: PageState) -> Action:
        """基于当前状态决策下一步动作。

        阶段一（stub）：固定返回 DONE，表示一次执行完成。
        阶段二：调用 VLM/LLM 推理。
        """
        return Action(action_type="DONE", confidence=1.0)

    def recover(
        self,
        observation: str,
        step: PlanStep,
        memory: Memory,
    ) -> Action:
        """VLM 求救时 LLM 恢复（阶段二实现）。"""
        return Action(action_type="FAIL", text="恢复失败 (stub)")

    def replan(self, observation: str, memory: Memory) -> Plan:
        """LLM 重规划剩余步骤（阶段二实现）。"""
        return Plan()

    def review_plan(self, plan: Plan, summary: str, memory: Memory) -> None:
        """步间审查（阶段二实现）。"""
        pass
