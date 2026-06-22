"""动作空间 (CoALA Action Space) —— 外部动作 + 内部动作 + 合法性校验。

设计详见 docs/action-space.md：
- 16 个外部动作（浏览器操作）+ 5 个内部动作（推理/记忆）= 21 个动作
"""

from enum import Enum, auto
from typing import Any

from classic_web_agent.agent.types import Action, PageState


class ActionType(Enum):
    """动作类型枚举 —— 21 个动作（16 外部 + 5 内部）。"""

    # 元素交互
    CLICK = auto()
    TYPE = auto()
    HOVER = auto()
    MOUSE_CLICK = auto()
    # 页面操作
    SCROLL = auto()
    PRESS = auto()
    WAIT = auto()
    # 导航
    GOTO = auto()
    GO_BACK = auto()
    GO_FORWARD = auto()
    # 标签页管理
    NEW_TAB = auto()
    CLOSE_TAB = auto()
    SWITCH_TAB = auto()
    # 信息获取
    SCREENSHOT = auto()
    EXTRACT = auto()
    FIND = auto()
    # 内部动作
    THINK = auto()
    REMEMBER = auto()
    RECALL = auto()
    DONE = auto()
    FAIL = auto()


class ActionSpace:
    """动作空间管理器 —— 合法性校验 + 去重检测。"""

    def __init__(self) -> None:
        self._last_action: Action | None = None
        self._repeated_count: int = 0

    def validate(self, action: Action, state: PageState) -> bool:
        """校验动作的合法性（阶段一：放行所有动作，返回 True）。"""
        return True

    def detect_repetition(self, action: Action) -> bool:
        """检测连续重复动作（≥3 次相同类型 → 标记为异常）。"""
        if (
            self._last_action is not None
            and self._last_action.action_type == action.action_type
        ):
            self._repeated_count += 1
        else:
            self._repeated_count = 0
        self._last_action = action
        return self._repeated_count >= 3
