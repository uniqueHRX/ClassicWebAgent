"""验证器 —— 动作效果检查 + 错误恢复（自愈机制）。

设计详见 docs/design.md §5 和 docs/model-routing.md §4.2：
- 状态比对：验证动作执行后页面是否符合预期
- 自愈恢复：RETRY（页面未大变）→ ESCALATE（呼叫 LLM）
- 阶段一（stub）：总是返回 success
"""

from typing import Any

from classic_web_agent.common.types import Action, ActionResult, PageState


class Verifier:
    """验证与恢复管理器。"""

    def verify(
        self,
        action: Action,
        result: ActionResult,
        state: PageState,
    ) -> str:
        """验证动作执行效果。

        Args:
            action: 已执行的动作。
            result: 执行结果。
            state: 执行后的页面状态。

        Returns:
            验证结果字符串："success" / "retry" / "fail"。
            阶段一（stub）：总是返回 "success"。
        """
        return "success"
