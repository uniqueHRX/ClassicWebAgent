"""VLM 子代理核心 —— 唯一公开接口 SubAgent。

用法:
    from classic_web_agent.subagent import SubAgent

    sub = SubAgent(vlm=vlm_client, browser=browser, memory=memory)
    observations = sub.execute(sub_task="搜索论文A的摘要")
    print(observations)
"""

import logging
from typing import Any

from classic_web_agent.common.action import ActionSpace
from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import Action, MemoryEntry, PageState
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)

_MAX_SUB_STEPS = 50


class SubAgent:
    """VLM 子代理 —— 自治执行单个子任务。

    对外唯一接口：execute(sub_task) → observations。
    内部自动创建 Perception / Planner / Executor。
    """

    def __init__(
        self,
        vlm: LLMClient | None = None,
        browser: Any | None = None,
        memory: Memory | None = None,
        subagent_config: dict[str, Any] | None = None,
        save_trace_fn: Any = None,
    ) -> None:
        """初始化子代理。

        Args:
            vlm: VLM 客户端（视觉模型）。
            browser: 浏览器驱动。
            memory: 共享记忆（必须传入，由 Agent 创建后注入）。
            subagent_config: subagent 配置字典，包含 confidence_threshold 等。
            save_trace_fn: 轨迹保存回调，签名 fn(data_uri, tree_text, task_id="")。
        """
        self.vlm = vlm
        self.browser = browser
        self.memory = memory or Memory()
        self.subagent_config = subagent_config or {}
        self.save_trace_fn = save_trace_fn

        # 内部组件（懒加载）
        self._planner: Any = None
        self._perception: Any = None
        self._executor: Any = None

    # ── 唯一公开方法 ─────────────────────────────────────────────

    def run(self, sub_task: str, task_id: str = "") -> str:
        """执行单个子任务。

        输入子任务描述 → 内部 ReAct 循环 → 输出 observations。

        Args:
            sub_task: LLM 分解的子任务描述（自然语言）。
            task_id: 子任务编号（用于截图命名，如 "001"）。

        Returns:
            observations 字符串（VLM 每步 memory 字段的拼接）。
        """
        # 清空上一个子任务的记录
        self.memory.clear_observations()
        self.memory.clear_working()

        # 初始化内部组件
        perception = self._get_perception()
        planner = self._get_planner()
        executor = self._get_executor()

        for step in range(1, _MAX_SUB_STEPS + 1):
            # 1. 观察
            state = perception.observe()
            if not state.url:
                logger.warning("页面状态为空，跳过此步")
                continue

            # 保存 Perception 返回的完整轨迹（截图 + DOM 树，同时间戳）
            # 命名格式: task_id_step_timestamp.png / .txt
            if self.save_trace_fn and state.screenshot:
                try:
                    trace_id = f"{task_id}_{step}"
                    self.save_trace_fn(state.screenshot, state.tree_text, task_id=trace_id)
                except Exception as e:
                    logger.warning("[SubAgent] 轨迹保存失败: %s", e)

            # 2. VLM 决策
            actions = planner.plan(
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
                    summary = action.text or ""
                    if summary:
                        self.memory.add_observation(summary)
                    if action.action_type == "DONE":
                        logger.info("[子任务完成] %s", summary)
                    else:
                        logger.warning("[子任务失败] %s", summary)
                    return self.memory.get_observations()

                result = executor.execute(action)
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

    # ── 内部组件管理 ────────────────────────────────────────────

    def _get_perception(self) -> Any:
        if self._perception is None:
            from classic_web_agent.subagent.perception import Perception
            self._perception = Perception(vlm=self.vlm, browser=self.browser)
        return self._perception

    def _get_planner(self) -> Any:
        if self._planner is None:
            from classic_web_agent.subagent.planner import Planner
            confidence = self.subagent_config.get("confidence_threshold", 0.9)
            self._planner = Planner(
                vlm=self.vlm,
                memory=self.memory,
                confidence_threshold=confidence,
            )
        return self._planner

    def _get_executor(self) -> Any:
        if self._executor is None:
            from classic_web_agent.subagent.executor import Executor
            self._executor = Executor(
                action_space=ActionSpace(),
                browser=self.browser,
                memory=self.memory,
            )
        return self._executor

    # ── 辅助 ────────────────────────────────────────────────────

    def _last_result_text(self) -> str:
        recent = self.memory.get_working(limit=1)
        if recent:
            return recent[-1].content
        return ""
