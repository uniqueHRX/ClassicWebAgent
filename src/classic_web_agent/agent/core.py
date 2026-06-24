"""Agent 主循环 —— Director + SubAgent 双层架构。

流程（详见 docs/design.md §4）：
  1. Agent.run(task)
  2. Director.plan(task) → task_plan + todo_list + first sub_task
  3. for each sub_task:
       a. SubAgent.run(sub_task) → observations
       b. Director.review(observations) → 更新 todo_list + next sub_task
  4. Director.report(task, task_plan, all_results) → 最终报告
"""

import logging
from typing import Any

from classic_web_agent.common.types import (
    DirectorOutput,
    MemoryEntry,
    TaskResult,
    TodoItem,
)
from classic_web_agent.logger import Logger
from classic_web_agent.common.memory import Memory
from classic_web_agent.agent.director import Director
from classic_web_agent.subagent.core import SubAgent

logger = logging.getLogger(__name__)

# 最大子任务轮次，防止无限循环
MAX_ROUNDS = 20


def _fmt_todo(todo_list: list[TodoItem]) -> str:
    """将 todo_list 格式化为可读字符串。"""
    lines = []
    for item in todo_list:
        lines.append(f"  [{item.status:>10}] #{item.id} {item.goal}")
        if item.summary:
            s = item.summary if len(item.summary) <= 80 else item.summary[:77] + "..."
            lines.append(f"               -> {s}")
    return "\n".join(lines)


class Agent:
    """WebAgent 主控制器 —— 编排 Director + SubAgent 双层架构。"""

    def __init__(self, config: dict[str, Any]) -> None:
        """初始化 Agent。

        Args:
            config: 全局配置字典（来自 load_config()）。
        """
        self.config = config

        # 子模块（由 main.py 的 create_agent 注入）
        self.llm: Any = None       # LLMClient（文本模型）
        self.vlm: Any = None       # LLMClient（视觉模型）
        self.browser: Any = None   # Browser 实例
        self.memory: Memory | None = None
        self.logger: Logger = Logger()

    def run(self, task: str) -> TaskResult:
        """执行任务主循环。

        Args:
            task: 自然语言任务描述。

        Returns:
            TaskResult: 任务执行结果（summary 为最终报告）。
        """
        memory = self.memory or Memory()
        director = Director(llm=self.llm, memory=memory)
        subagent_config = self.config.get("subagent", {})

        # 轨迹回调（log_trace 启用时注入到 SubAgent）
        log_trace = self.config.get("log_trace", False)
        save_trace_fn = None
        if log_trace and self.logger:
            save_trace_fn = self.logger.save_trace

        sub = SubAgent(
            vlm=self.vlm,
            browser=self.browser,
            memory=memory,
            subagent_config=subagent_config,
            save_trace_fn=save_trace_fn,
        )

        self.logger.start_task(task)
        memory.add_working(MemoryEntry(role="system", content=f"任务: {task}"))

        # ── 阶段1：任务分解 ────────────────────────────────────────
        logger.info("[Agent] 阶段1: Director.plan() — 任务分解")
        logger.info("[Agent] 用户任务: %s", task)
        output = director.plan(task)

        if output.next.type == "done":
            result = TaskResult(
                success=False,
                summary="任务无法分解为子任务",
            )
            self.logger.end_task(result)
            return result

        # 保存 task_plan（报告阶段使用）
        task_plan = output.task_plan
        logger.info("[Agent] task_plan (%d 字符):\n%s", len(task_plan), task_plan)
        logger.info("[Agent] 初始 todo_list (%d 项):\n%s",
                     len(output.todo_list), _fmt_todo(output.todo_list))
        logger.info("[Agent] 第一个子任务: %s", output.next.description)

        # ── 阶段2：执行调度循环 ────────────────────────────────────
        logger.info("[Agent] 阶段2: 子任务执行调度")
        all_observations: list[str] = []

        for round_num in range(1, MAX_ROUNDS + 1):
            if output.next.type == "done":
                logger.info("[Agent] 所有子任务完成 (第 %d 轮)", round_num - 1)
                break

            sub_task = output.next.description
            completed_goal = _get_current_goal(output.todo_list)
            logger.info("[Agent] 轮次 %d: 「%s」", round_num, completed_goal)

            # 调用 SubAgent（传入轮次编号作为 task_id 用于截图命名）
            observations = sub.run(sub_task, task_id=f"{round_num:04d}")
            all_observations.append(
                f"### 子任务 {round_num}: {completed_goal}\n\n{observations}"
            )
            logger.info("[Agent] SubAgent 返回 (%d 字符):\n%s",
                         len(observations), observations)

            # 标记失败
            if "[FAIL]" in observations:
                logger.warning("[Agent] 子任务可能失败: %s", completed_goal)
                memory.add_working(
                    MemoryEntry(
                        role="system",
                        content=f"子任务可能失败: {completed_goal}",
                    )
                )

            # 审查结果，获取下一个子任务
            output = director.review(completed_goal, observations)
            logger.info("[Agent] review.thinking: %s", output.thinking)

            if output.next.type == "done":
                logger.info("[Agent] Director 标记全部完成")
                break

            # 如果 LLM 更新了 task_plan，同步更新
            if output.task_plan.strip():
                logger.info("[Agent] task_plan 已更新:\n%s", output.task_plan)
                task_plan = output.task_plan

            # 记录更新后的 todo_list
            logger.info("[Agent] 更新后 todo_list:\n%s", _fmt_todo(output.todo_list))
            logger.info("[Agent] 下一个子任务: %s", output.next.description)

            if round_num >= MAX_ROUNDS:
                logger.warning("[Agent] 达到最大轮次 %d，强制结束", MAX_ROUNDS)

        # ── 阶段3：报告生成 ────────────────────────────────────────
        logger.info("[Agent] 阶段3: Director.report() — 报告生成")
        all_results = "\n\n---\n\n".join(all_observations)
        logger.info("[Agent] 汇总 %d 个子任务结果 (%d 字符)",
                      len(all_observations), len(all_results))

        report_format = self.config.get("report_format", "md")

        if report_format == "both":
            md_report = director.report(task, task_plan, all_results, "md")
            html_report = director.report(task, task_plan, all_results, "html")
            logger.info("[Agent] 报告已生成 (both: md=%d 字符, html=%d 字符)",
                         len(md_report), len(html_report))
            result = TaskResult(
                success=True,
                summary=md_report,
                md_report=md_report,
                html_report=html_report,
                total_steps=len(all_observations),
            )
        elif report_format == "html":
            html_report = director.report(task, task_plan, all_results, "html")
            logger.info("[Agent] 报告已生成 (html, %d 字符):\n%s",
                         len(html_report), html_report)
            result = TaskResult(
                success=True,
                summary=html_report,
                html_report=html_report,
                total_steps=len(all_observations),
            )
        else:
            md_report = director.report(task, task_plan, all_results, "md")
            logger.info("[Agent] 报告已生成 (md, %d 字符):\n%s",
                         len(md_report), md_report)
            result = TaskResult(
                success=True,
                summary=md_report,
                md_report=md_report,
                total_steps=len(all_observations),
            )
        logger.info("[Agent] 任务完成，共 %d 个子任务", result.total_steps)
        self.logger.end_task(result)
        return result


def _get_current_goal(todo_list: list[TodoItem]) -> str:
    """从 todo_list 中找到当前 in_progress 的子任务目标。

    Args:
        todo_list: Director 的 todo 列表。

    Returns:
        str: 目标描述，如果找不到则返回"未知子任务"。
    """
    for item in todo_list:
        if item.status == "in_progress":
            return item.goal
    return "未知子任务"
