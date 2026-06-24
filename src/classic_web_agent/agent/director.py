"""Agent Director —— LLM 编排器。

负责：
1. 任务分解（plan）—— 生成 task_plan + todo_list + 第一个子任务
2. 子任务审查（review）—— 更新 todo_list + 决定下一个子任务
3. 报告生成（report）—— 汇总所有 observations 生成最终报告

用法：
    from classic_web_agent.agent.director import Director

    director = Director(llm=llm_client)
    output = director.plan("帮我在京东找一款8000元的笔记本")
    # 循环: output.next.type == "sub_task" → SubAgent.run → director.review()
    report = director.report(task, task_plan, all_results)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import (
    DirectorOutput,
    NextAction,
    TodoItem,
)
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)

# 加载 prompt 文件的路径
_PROMPT_DIR = Path(__file__).parent / "prompts"
_DIRECTOR_YAML = _PROMPT_DIR / "director.yaml"
_REPORTER_YAML = _PROMPT_DIR / "reporter.yaml"

_MAX_RETRIES = 3          # LLM JSON 解析失败时的最大重试次数


class Director:
    """LLM 编排器 —— 任务分解 + 子任务调度 + 报告生成。"""

    def __init__(
        self,
        llm: LLMClient,
        memory: Memory | None = None,
    ) -> None:
        """初始化 Director。

        Args:
            llm: LLM 客户端（文本模型，非 VLM）。
            memory: 可选记忆实例（用于日志记录）。
        """
        self.llm = llm
        self.memory = memory or Memory()

        # 缓存的 prompt 数据
        self._director_prompt: dict[str, Any] = {}
        self._reporter_prompt: dict[str, Any] = {}

        # LLM 对话历史（plan() 开始累积，贯穿整个任务）
        self._messages: list[dict[str, str]] = []

    # ── 公开方法 ─────────────────────────────────────────────────

    def plan(self, task: str) -> DirectorOutput:
        """阶段1：收到用户任务 → 返回初始计划。

        Args:
            task: 用户原始任务描述。

        Returns:
            DirectorOutput: 包含 task_plan、todo_list 和第一个 sub_task。
        """
        self._load_prompts()

        # 构建 system prompt
        system = self._render_director_system()

        # 构建 user message（注入当前日期时间）
        now_str = datetime.now().strftime("%Y-%m-%d %A %H:%M")
        user = self._render_user_template(
            template_key="initial",
            prompt_data=self._director_prompt,
            task=task,
            current_date=now_str,
        )

        # 调用 LLM（要求 JSON 输出）
        raw = self._call_llm(system=system, user=user, response_format={"type": "json_object"})

        output = self._parse_output(raw)
        if output is None:
            return DirectorOutput(
                thinking="LLM 返回解析失败",
                task_plan="",
                next=NextAction(type="done"),
                raw=raw,
            )

        # 验证 task_plan 非空
        if not output.task_plan.strip():
            logger.warning("task_plan 为空，重试 plan()")
            for _ in range(_MAX_RETRIES - 1):
                raw = self._call_llm(
                    system=system, user=user, response_format={"type": "json_object"}
                )
                output = self._parse_output(raw)
                if output and output.task_plan.strip():
                    break

        output.raw = raw

        # 保存对话历史
        self._messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": raw},
        ]

        return output

    def review(self, completed_goal: str, observations: str) -> DirectorOutput:
        """阶段2：审查 SubAgent 结果 → 更新 todo_list + 下一个子任务。

        Args:
            completed_goal: 刚完成的子任务目标。
            observations: SubAgent 返回的观察结果文本。

        Returns:
            DirectorOutput: 更新后的 todo_list 和下一个动作。
        """
        if not self._messages:
            logger.error("review() 在 plan() 之前被调用")
            return DirectorOutput(
                thinking="内部错误：review 在 plan 之前调用",
                next=NextAction(type="done"),
            )

        # 追加 SubAgent 结果作为新的 user message
        now_str = datetime.now().strftime("%Y-%m-%d %A %H:%M")
        progress_template = self._director_prompt.get("user", {}).get("progress", "")
        user = (
            progress_template.replace("{completed_goal}", completed_goal)
            .replace("{observations}", observations)
            .replace("{current_date}", now_str)
        )
        self._messages.append({"role": "user", "content": user})

        # 调用 LLM
        raw = self._call_llm(
            system="",
            user="",
            response_format={"type": "json_object"},
            messages=self._messages,
        )

        output = self._parse_output(raw)
        if output is None:
            logger.warning("review() 解析 LLM 返回失败，重试")
            for _ in range(_MAX_RETRIES - 1):
                raw = self._call_llm(
                    system="",
                    user="",
                    response_format={"type": "json_object"},
                    messages=self._messages,
                )
                output = self._parse_output(raw)
                if output is not None:
                    break

        if output is None:
            output = DirectorOutput(
                thinking="review 解析失败",
                todo_list=[],
                next=NextAction(type="done"),
                raw=raw,
            )

        output.raw = raw
        self._messages.append({"role": "assistant", "content": raw})

        return output

    def report(
        self,
        task: str,
        task_plan: str,
        all_results: str,
        report_format: str = "md",
    ) -> str:
        """阶段3：生成最终报告。

        Args:
            task: 用户原始任务描述。
            task_plan: 任务计划书（plan 阶段生成）。
            all_results: 所有 SubAgent 观察结果的汇总文本。
            report_format: 报告格式，"md"（Markdown 文档）或 "html"（网页报告）。

        Returns:
            str: 最终报告文本（MD 或 HTML）。
        """
        fmt = report_format if report_format in ("md", "html") else "md"

        if not self._reporter_prompt:
            self._load_prompts()

        system = self._render_reporter_system(fmt)
        user = self._render_user_template(
            template_key="default",
            prompt_data=self._reporter_prompt,
            task=task,
            task_plan=task_plan,
            all_results=all_results,
        )

        # 构建完整上下文：reporter system + 历史对话（Director 分解/审查全过程）+ 报告指令
        # 这样 LLM 能看到任务的完整上下文，而不仅仅是最终的 all_results 文本
        msgs: list[dict[str, str]] = [{"role": "system", "content": system}]
        if self._messages:
            # 跳过 self._messages[0]（旧的 director system），保留 plan/review 对话历史
            msgs.extend(self._messages[1:])
        msgs.append({"role": "user", "content": user})

        raw = self._call_llm(system="", user="", response_format=None, messages=msgs)
        return raw.strip()

    # ── 内部方法 ─────────────────────────────────────────────────

    def _load_prompts(self) -> None:
        """加载 YAML prompt 文件（仅加载一次）。"""
        if not self._director_prompt:
            for yaml_path, attr_name in [
                (_DIRECTOR_YAML, "_director_prompt"),
                (_REPORTER_YAML, "_reporter_prompt"),
            ]:
                if not yaml_path.exists():
                    logger.error("Prompt 文件不存在: %s", yaml_path)
                    continue
                with open(yaml_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    setattr(self, attr_name, data)

    def _render_director_system(self) -> str:
        """将 director.yaml 的 system 节渲染为纯文本。"""
        system_data = self._director_prompt.get("system", {})
        return self._render_system_block(system_data)

    def _render_reporter_system(self, fmt: str = "md") -> str:
        """将 reporter.yaml 的 system 节渲染为纯文本。

        Args:
            fmt: 报告格式，"md" 或 "html"。
        """
        system_data = self._reporter_prompt.get("system", {})
        if isinstance(system_data, dict) and fmt in system_data:
            system_data = system_data[fmt]
        return self._render_system_block(system_data)

    def _render_system_block(self, system_data: dict[str, Any]) -> str:
        """将一个 system 字典渲染为纯文本字符串。

        按顺序拼接所有非 None 的 key 和对应的 value。
        """
        parts: list[str] = []
        for key, value in system_data.items():
            if value is None:
                continue
            if isinstance(value, str):
                parts.append(value.strip())
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, str):
                        parts.append(item.strip())
        return "\n\n".join(parts)

    def _render_user_template(
        self,
        template_key: str,
        prompt_data: dict[str, Any],
        **kwargs: str,
    ) -> str:
        """填充 user 模板中的 {placeholder}。

        Args:
            template_key: user 字典中的 key（如 "initial"、"progress"、"default"）。
            prompt_data: 加载的 YAML 数据（dict）。
            **kwargs: 占位符值。

        Returns:
            str: 填充后的 user 消息。
        """
        template = prompt_data.get("user", {}).get(template_key, "")
        # 替换所有 {key} 占位符
        for key, value in kwargs.items():
            template = template.replace(f"{{{key}}}", value)
        return template

    def _call_llm(
        self,
        system: str,
        user: str,
        response_format: dict[str, str] | None = None,
        messages: list[dict[str, str]] | None = None,
    ) -> str:
        """调用 LLM，处理重试。

        Args:
            system: system prompt（为空则使用 messages 参数）。
            user: user message（为空则使用 messages 参数）。
            response_format: "json_object" | None。
            messages: 直接传入的消息列表（替代 system+user）。

        Returns:
            str: LLM 的原始返回文本。
        """
        if messages:
            # 使用预先构建的消息列表（review 阶段）
            msgs = messages
        else:
            msgs = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self.llm.chat(
                    messages=msgs,
                    response_format=response_format,
                )
                content = response.content or ""
                if content.strip():
                    return content
            except Exception as e:
                logger.warning("LLM 调用失败 (第%d次): %s", attempt, e)

            if attempt < _MAX_RETRIES:
                logger.info("重试 LLM 调用 (第%d次)", attempt + 1)

        error_msg = f'{{"thinking": "LLM调用失败，重试{_MAX_RETRIES}次", "next": {{"type": "done"}}}}'
        logger.error("LLM 调用全部失败，返回默认错误")
        return error_msg

    def _parse_output(self, raw: str) -> DirectorOutput | None:
        """解析 LLM 返回的 JSON，验证字段完整性。

        Args:
            raw: LLM 原始返回文本。

        Returns:
            DirectorOutput 或 None（解析失败）。
        """
        cleaned = raw.strip()
        # 尝试移除代码块标记
        if cleaned.startswith("```"):
            # 去掉开头的 ```json 或 ```
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline:]
            # 去掉结尾的 ```
            last_marker = cleaned.rfind("```")
            if last_marker != -1:
                cleaned = cleaned[:last_marker]
            cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning("JSON 解析失败: %s", e)
            return None

        # 验证必填字段
        if "thinking" not in data:
            logger.warning("缺少 thinking 字段")
            return None
        if "next" not in data:
            logger.warning("缺少 next 字段")
            return None

        next_data = data["next"]
        if not isinstance(next_data, dict) or "type" not in next_data:
            logger.warning("next 字段格式错误")
            return None

        # 解析 todo_list
        todo_list_raw = data.get("todo_list", [])
        todo_list: list[TodoItem] = []
        for item in todo_list_raw:
            if isinstance(item, dict):
                todo_list.append(
                    TodoItem(
                        id=item.get("id", 0),
                        goal=item.get("goal", ""),
                        status=item.get("status", "pending"),
                        summary=item.get("summary", ""),
                    )
                )

        # 解析 next
        next_action = NextAction(
            type=next_data.get("type", "done"),
            description=next_data.get("description", ""),
        )

        # 如果是 sub_task 但 description 为空，视为无效
        if next_action.type == "sub_task" and not next_action.description.strip():
            logger.warning("next.type=sub_task 但 description 为空")
            return None

        return DirectorOutput(
            thinking=data.get("thinking", ""),
            task_plan=data.get("task_plan", ""),
            todo_list=todo_list,
            next=next_action,
        )
