"""Agent 主循环 —— ReAct 闭环。

observe → plan → execute → verify

编排流程（详见 docs/design.md §4）：
  1. Logger.start_task(task)
  2. Perception.observe() → PageState
  3. Planner.create_plan(task) → Plan
  4. for each PlanStep:
       a. Perception.observe() → PageState
       b. Planner.plan(state) → Action
       c. Executor.execute(action) → ActionResult
       d. Verifier.verify(action, result, state) → verdict
       e. Logger.log_step(step)
       f. 若 action_type 为 DONE/FAIL → 终止循环
  5. Logger.end_task(result) → TaskResult
"""

from typing import Any

from classic_web_agent.agent.types import (
    Action,
    ActionResult,
    AgentStep,
    MemoryEntry,
    PageState,
    Plan,
    PlanStep,
    TaskResult,
)
from classic_web_agent.logger import Logger
from classic_web_agent.agent.memory import Memory
from classic_web_agent.agent.action import ActionSpace
from classic_web_agent.agent.perception import Perception
from classic_web_agent.agent.planner import Planner
from classic_web_agent.agent.executor import Executor
from classic_web_agent.agent.verifier import Verifier

# 最大步数，防止死循环
MAX_STEPS = 50


class Agent:
    """WebAgent 主控制器 —— 编排 ReAct 闭环。"""

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 Agent，所有子模块由工厂函数注入。

        Args:
            config: 全局配置字典（来自 load_config()）。
        """
        self.config = config

        # 子模块（由 main.py 的 create_agent 注入）
        self.logger: Logger = Logger()
        self.memory: Memory | None = None
        self.action_space: ActionSpace | None = None
        self.perception: Perception | None = None
        self.planner: Planner | None = None
        self.executor: Executor | None = None
        self.verifier: Verifier | None = None

    def run(self, task: str) -> TaskResult:
        """执行任务主循环。

        Args:
            task: 自然语言任务描述。

        Returns:
            TaskResult: 任务执行结果。
        """
        # 防御：子模块未注入时使用默认值
        memory = self.memory or Memory()
        action_space = self.action_space or ActionSpace()
        planner = self.planner or Planner(memory=memory)
        executor = self.executor or Executor(
            action_space=action_space,
            browser=None,
            memory=memory,
        )
        verifier = self.verifier or Verifier()
        perception = self.perception or Perception(vlm=None, browser=None)

        # 1. 任务开始
        self.logger.start_task(task)
        memory.add_working(MemoryEntry(role="system", content=f"任务: {task}"))

        # 2. 初始观察
        state = perception.observe()

        # 3. 创建粗粒度计划
        plan = planner.create_plan(task)
        if not plan.steps:
            result = TaskResult(success=False, summary="计划为空")
            self.logger.end_task(result)
            return result

        # 4. 步骤循环
        step_index = 0
        for plan_step in plan.steps:
            while step_index < MAX_STEPS:
                # a. 观察
                state = perception.observe()

                # b. 规划
                action = planner.plan(state)

                # c. 执行（统一入口：内部+外部动作均由 Executor 处理）
                action_result = executor.execute(action)

                # d. 验证
                verdict = verifier.verify(action, action_result, state)

                # e. 记录
                step = AgentStep(
                    step_index=step_index,
                    action=action,
                    result=action_result,
                    state_before=state,
                    state_after=state,
                )
                self.logger.log_step(step)

                # f. 终止条件：DONE 或 FAIL（由 Executor 返回成功，Agent 控制循环）
                if action.action_type in ("DONE", "FAIL"):
                    break

                step_index += 1

            if step_index >= MAX_STEPS:
                break

        # 5. 任务结束
        final = TaskResult(success=True, summary="测试完成", total_steps=step_index + 1)
        self.logger.end_task(final)
        return final
