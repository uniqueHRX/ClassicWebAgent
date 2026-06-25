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
from classic_web_agent.logger import fmt_action

logger = logging.getLogger(__name__)


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

        # 当前步骤的动作执行结果（仅本次序列，不含历史）
        self._last_step_results: str = ""

        # 当前子任务的完成状态（供 Agent 保存到 sub_tasks.json）
        self.current_status: dict | None = None

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

        # 从配置读取最大步数和重试次数，未设置时使用默认值
        max_steps = self.subagent_config.get("max_steps", 20)

        for step in range(1, max_steps + 1):
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
                max_steps=max_steps,
            )

            if not actions:
                logger.warning("VLM 未返回动作，终止子任务")
                break

            # 记录 VLM 输出的动作序列（紧凑格式，便于阅读日志）
            action_desc = " → ".join(fmt_action(a) for a in actions)
            confidence = actions[0].confidence if actions else 0.0
            logger.info(
                "[SubAgent] 步骤 %d 动作序列: %s | conf=%.2f",
                step, action_desc, confidence,
            )

            # 3. 执行动作序列（收集全部结果，供 VLM 下一轮决策参考）
            step_results: list[str] = []
            log_lines: list[str] = []
            for action in actions:
                if action.action_type in ("DONE", "FAIL"):
                    summary = action.text or ""
                    if summary:
                        self.memory.add_observation(summary)
                    if action.action_type == "DONE":
                        logger.info("[子任务完成] %s", summary)
                        self.current_status = {"status": "completed", "summary": summary}
                    else:
                        logger.warning("[子任务失败] %s", summary)
                        self.current_status = {"status": "failed", "summary": summary}
                    return self.memory.get_observations()

                # 记录执行前的标签页数量，用于检测 popup 新标签页
                tabs_before = self.browser.tab_count

                result = executor.execute(action)
                # 完整消息（含 data）→ _last_step_results → VLM {last_result}
                if result.data is not None and isinstance(result.data, str) and len(result.data) > 0:
                    msg = f"[{action.action_type}] {result.message} | data={result.data}"
                else:
                    msg = f"[{action.action_type}] {result.message}"
                step_results.append(msg)

                # 精简日志（仅 type + message，不含 data）
                log_msg = f"[{action.action_type}] {result.message}"
                log_lines.append(log_msg)

                # 获取目标元素的 DOM 节点信息（从 handle 提取，用于结构化记忆）
                element_info = ""
                if action.element_id is not None:
                    try:
                        element_info = self.browser.get_element_info(action.element_id)
                    except Exception:
                        pass

                self.memory.add_working(
                    MemoryEntry(
                        role="assistant",
                        url=state.url,
                        action_type=action.action_type,
                        element_id=action.element_id,
                        element_info=element_info,
                        result_message=result.message,
                    )
                )

                if not result.success:
                    logger.warning("动作失败: %s", result.message)
                    break

                # 检测 popup 新标签页：标签页数增加说明 CLICK 打开了新标签页，
                # _on_popup 已自动切换 active_index 到新标签页。
                # 后继动作的 element_id 来自旧标签页的 DOM 树，在新页面上无效，
                # 应跳过它们，下一轮观察新标签页后由 VLM 重新决策。
                if self.browser.tab_count > tabs_before:
                    remaining = len(actions) - actions.index(action) - 1
                    logger.info(
                        "%s 打开了新标签页(tab_%d)，跳过后继 %d 个动作",
                        action.action_type, self.browser.active_index, remaining,
                    )
                    break

            # 保存本次序列的完整结果供 VLM 下一轮使用
            self._last_step_results = "\n".join(step_results)
            logger.info(
                "[SubAgent] 步骤 %d 执行结果: %s", step, " | ".join(log_lines)
            )

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
            max_retries = self.subagent_config.get("max_retries", 3)
            self._planner = Planner(
                vlm=self.vlm,
                memory=self.memory,
                confidence_threshold=confidence,
                max_retries=max_retries,
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
        """返回上一步动作序列的完整执行结果（仅本次序列，不含历史）。

        VLM 输出的是动作序列（如 CLICK → WAIT → EXTRACT），
        所有动作的执行结果都应可见，而不仅仅是最后一个。
        """
        return self._last_step_results
