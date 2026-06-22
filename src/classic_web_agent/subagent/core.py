"""VLM 子代理核心 —— 子任务自治执行循环。

接收 LLM 派发的子任务，独立完成页面操作并返回 observations。

流程：
  1. 清空 observations
  2. Perception.observe() → PageState
  3. Planner.plan() → Action 列表
  4. Executor.execute() → 逐个执行
  5. 循环直到 DONE / FAIL / 超步数
  6. 返回 observations 给 LLM
"""

import logging
from typing import Any

from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import Action, MemoryEntry, PageState
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)

# VLM 子任务最大步数
_MAX_SUB_STEPS = 50


class SubAgent:
    """VLM 子代理 —— 自治执行单个子任务。"""

    def __init__(
        self,
        perception: Any,   # Perception 实例
        planner: Any,      # subagent.planner.Planner 实例
        executor: Any,     # subagent.executor.Executor 实例
        memory: Memory,
    ) -> None:
        self.perception = perception
        self.planner = planner
        self.executor = executor
        self.memory = memory

    def execute(self, sub_task: str) -> str:
        """执行单个子任务，返回 observations 字符串。

        Args:
            sub_task: LLM 分解的子任务描述。

        Returns:
            observations（VLM 每步 memory 字段的拼接）。
        """
        # 清空当前子任务的 observation 和 working
        self.memory.clear_observations()
        self.memory.clear_working()

        for step in range(1, _MAX_SUB_STEPS + 1):
            # 1. 观察页面
            state = self.perception.observe()
            if not state.url:
                logger.warning("页面状态为空，跳过此步")
                continue

            # 2. VLM 决策
            actions = self.planner.plan(
                state=state,
                sub_task=sub_task,
                last_result=self._last_result_text(),
                step_number=step,
                max_steps=_MAX_SUB_STEPS,
            )

            if not actions:
                logger.warning("VLM 未返回动作，终止子任务")
                break

            # 3. 执行动作序列
            for action in actions:
                if action.action_type in ("DONE", "FAIL"):
                    if action.action_type == "DONE":
                        logger.info("[子任务完成] %s", action.text or "")
                    else:
                        logger.warning("[子任务失败] %s", action.text or "")
                    return self.memory.get_observations()

                result = self.executor.execute(action)
                self.memory.add_working(
                    MemoryEntry(
                        role="assistant",
                        content=f"[{action.action_type}] {result.message}",
                    )
                )

                if not result.success:
                    logger.warning("动作失败: %s", result.message)
                    break

        return self.memory.get_observations()

    def _last_result_text(self) -> str:
        """格式化上一步结果。"""
        recent = self.memory.get_working(limit=1)
        if recent:
            return f"{recent[-1].content}"
        return ""
