"""VLM Planner —— 页面感知 + 动作规划。

加载 config/prompts/planner.yaml 渲染 system prompt，
调用 VLM 获取 JSON 输出，解析为 Action 列表。
"""

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from classic_web_agent.agent.action import ActionType
from classic_web_agent.agent.memory import Memory
from classic_web_agent.agent.types import Action, PageState
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path("config/prompts/planner.yaml")

# VLM 返回中必须存在的字段
_REQUIRED_FIELDS = frozenset({
    "thinking", "verification", "memory",
    "goal", "actions", "confidence",
})

# 合法动作名集合（用于校验 VLM 输出）
_VALID_ACTION_NAMES = {e.name for e in ActionType}


class Planner:
    """VLM 动作规划器。

    职责：
    - 加载 planner.yaml → 渲染 system prompt
    - 构建 user 消息（含截图和 DOM 树）
    - 调用 VLM → 解析 JSON → 校验 → 转为 Action 列表
    - 处理 confidence 机制（重试 / 失败）
    """

    def __init__(
        self,
        vlm: LLMClient | None,
        memory: Memory | None = None,
    ) -> None:
        self.vlm = vlm
        self.memory = memory

        # 加载 prompt 模板
        self._data: dict[str, Any] = {}
        self._user_template: str = ""
        self._load_prompt()

        # confidence 机制
        self.confidence_threshold: float = 0.9
        self._retry_count: int = 0
        self._max_retries: int = 3

    # ═══════════════════════════════════════════════════════════════════
    # 公开方法
    # ═══════════════════════════════════════════════════════════════════

    def plan(
        self,
        state: PageState,
        sub_task: str = "",
        last_result: str = "",
        step_number: int = 1,
        max_steps: int = 50,
    ) -> list[Action]:
        """VLM 单步规划。

        输入当前页面状态和子任务描述，返回要执行的动作序列。

        Args:
            state: 当前页面状态（截图 + URL + DOM 树）。
            sub_task: 当前正在执行的子任务描述。
            last_result: 上一步执行结果（字符串）。
            step_number: 当前步骤编号（1-based）。
            max_steps: 最大步数限制。

        Returns:
            Action 列表。VLM 未初始化时返回 [DONE] 保证向后兼容。
        """
        if not self.vlm:
            return [Action(action_type="DONE", confidence=1.0)]

        # 1. 构建消息
        messages = self._build_messages(state, sub_task, last_result,
                                         step_number, max_steps,
                                         state.current_tab_id, state.tabs_list)

        # 2. 调用 VLM（最多 3 次重试）
        parsed = self._call_vlm(messages)
        if parsed is None:
            return []

        # 3. 提取字段
        thinking = parsed.get("thinking", "")
        verification = parsed.get("verification", "")
        memory_text = parsed.get("memory", "")
        goal = parsed.get("goal", "")
        raw_actions = parsed.get("actions", [])
        confidence = float(parsed.get("confidence", 0.0))

        logger.info(
            "[VLM] conf=%.2f goal=%s verify=%s",
            confidence, goal[:60], verification[:60],
        )

        # 4. 记录 memory 到 observations
        if memory_text and self.memory:
            self.memory.add_observation(memory_text)

        # 5. confidence 机制
        if confidence < self.confidence_threshold:
            self._retry_count += 1
            if self._retry_count >= self._max_retries:
                self._retry_count = 0
                return [
                    Action(
                        action_type="FAIL",
                        text=f"连续{self._max_retries}次低置信度",
                    )
                ]
            return self.plan(state, sub_task, last_result,
                             step_number, max_steps)

        self._retry_count = 0
        return self._to_actions(raw_actions)

    # ═══════════════════════════════════════════════════════════════════
    # Prompt 加载与渲染
    # ═══════════════════════════════════════════════════════════════════

    def _load_prompt(self) -> None:
        """从 planner.yaml 加载原始数据。"""
        if not _PROMPT_PATH.exists():
            logger.warning("prompt 不存在: %s", _PROMPT_PATH)
            return
        with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
            self._data = yaml.safe_load(f)
        self._user_template = self._data.get("user", "")

    def _render_system(self) -> str:
        """从缓存数据渲染 system prompt。"""
        t = self._data.get("system", {})
        if not t:
            return ""

        parts: list[str] = []
        for key in ("role", "input", "output", "rules"):
            val = t.get(key, "")
            if val:
                parts.append(val.strip())

        actions_text = self._format_actions(t.get("actions", []))
        if actions_text:
            parts.append(actions_text)

        return "\n\n".join(parts)

    @staticmethod
    def _format_actions(groups: list[dict]) -> str:
        """把结构化 actions 渲染为文本。"""
        if not groups:
            return ""
        lines: list[str] = []
        for g in groups:
            cat = g.get("category", "")
            risk = g.get("page_change_risk", "")
            tag = f" [风险: {risk}]" if risk else ""
            lines.append(f"\n{cat}{tag}")
            for item in g.get("items", []):
                name = item.get("name", "")
                desc = item.get("desc", "")
                params = item.get("params", {})
                param_str = (
                    ", ".join(f"{k}={v}" for k, v in params.items())
                    if params else "(无参数)"
                )
                lines.append(f"  {name:>12}  {desc}")
                if params:
                    lines.append(f"          参数: {param_str}")
            lines.append("")
        return "\n".join(lines)

    def _render_user(
        self,
        sub_task: str,
        step_number: int,
        max_steps: int,
        url: str,
        tree_text: str,
        last_result: str,
        observations: str,
        recent_actions: str,
        current_tab_id: str = "",
        tabs_list: str = "",
    ) -> str:
        """填充 user 模板。截图以 image 形式单独传入。"""
        return (
            self._user_template
            .replace("{sub_task}", sub_task)
            .replace("{step_number}", str(step_number))
            .replace("{max_steps}", str(max_steps))
            .replace("{url}", url)
            .replace("{current_tab_id}", current_tab_id)
            .replace("{tabs_list}", tabs_list)
            .replace("{tree_text}", tree_text)
            .replace("{last_result}", last_result)
            .replace("{observations}", observations)
            .replace("{recent_actions}", recent_actions)
        )

    def _recent_text(self) -> str:
        """从 memory.working 取最近 5 步。"""
        if not self.memory:
            return ""
        recent = self.memory.get_working(limit=5)
        return "\n".join(
            f"  [{i}] {e.content[:100]}" for i, e in enumerate(recent)
        )

    # ═══════════════════════════════════════════════════════════════════
    # VLM 调用
    # ═══════════════════════════════════════════════════════════════════

    def _build_messages(
        self,
        state: PageState,
        sub_task: str,
        last_result: str,
        step_number: int,
        max_steps: int,
        current_tab_id: str = "0",
        tabs_list: str = "",
    ) -> list[dict[str, Any]]:
        """构建 OpenAI 消息格式。"""
        user_text = self._render_user(
            sub_task=sub_task,
            step_number=step_number,
            max_steps=max_steps,
            url=state.url,
            tree_text=state.tree_text,
            last_result=last_result,
            observations=self.memory.get_observations() if self.memory else "",
            recent_actions=self._recent_text(),
            current_tab_id=state.current_tab_id or current_tab_id,
            tabs_list=state.tabs_list or tabs_list,
        )
        return [
            {"role": "system", "content": self._render_system()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": state.screenshot}},
                ],
            },
        ]

    def _call_vlm(
        self, messages: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """调用 VLM 并解析返回，最多 3 次重试。"""
        for attempt in range(3):
            try:
                resp = self.vlm.chat(
                    messages,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                )
                parsed = self._parse(resp.content)
                if parsed is not None:
                    return parsed
            except Exception as e:
                logger.warning("VLM 异常（%d/3）: %s", attempt + 1, e)
        return None

    # ═══════════════════════════════════════════════════════════════════
    # 响应解析
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _parse(raw: str) -> dict[str, Any] | None:
        """解析 JSON 并校验字段完整性。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None

        missing = _REQUIRED_FIELDS - set(data.keys())
        if missing:
            logger.warning("VLM 缺字段: %s", missing)
            return None

        actions = data.get("actions", [])
        if not isinstance(actions, list):
            return None

        for i, a in enumerate(actions):
            if not isinstance(a, dict) or a.get("type") not in _VALID_ACTION_NAMES:
                logger.warning("actions[%d] 非法: %s", i, a.get("type"))
                return None

        return data

    @staticmethod
    def _to_actions(raw: list[dict[str, Any]]) -> list[Action]:
        """JSON 动作 → Action 对象。"""
        result: list[Action] = []
        for a in raw:
            atype = a.pop("type", "")
            kw: dict[str, Any] = {"action_type": atype}

            if atype in ("CLICK", "HOVER", "TYPE"):
                kw["element_id"] = a.pop("element_id", None)
            if atype == "TYPE":
                kw["text"] = a.pop("text", None)
            if atype in ("THINK", "DONE", "FAIL"):
                kw["text"] = a.pop("text", None)

            extra = {k: v for k, v in a.items() if v is not None}
            if extra:
                kw["extra"] = extra

            result.append(Action(**kw))

        return result
