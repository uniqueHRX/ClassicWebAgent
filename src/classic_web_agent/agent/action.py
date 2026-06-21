"""动作空间 (CoALA Action Space) —— 外部动作 + 内部动作 + 合法性校验。"""

from enum import Enum, auto
from typing import Any

from classic_web_agent.agent.types import Action


class ActionType(Enum):
    """动作类型枚举。"""


class ActionSpace:
    """动作空间管理器。"""
