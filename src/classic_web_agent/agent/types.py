"""Agent 数据模型 —— 集中定义核心数据结构。

包含：PageState, Action, ActionResult, MemoryEntry, AgentStep。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PageState:
    """页面状态（感知模块输出）。"""


@dataclass
class Action:
    """动作定义。"""


@dataclass
class ActionResult:
    """动作执行结果。"""


@dataclass
class MemoryEntry:
    """记忆条目。"""


@dataclass
class AgentStep:
    """单步轨迹记录。"""
