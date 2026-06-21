"""感知模块 —— VLM 视觉分析 + DOM 解析 + 多模态融合 + 元素定位。

整合：视觉感知、DOM 结构提取、Set-of-Marks 标注（可选）、
多模态信息融合、目标元素精确定位。
"""

from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.browser import Browser
from classic_web_agent.agent.types import PageState


class Perception:
    """多模态感知器。"""

    def __init__(self, vlm: LLMClient, browser: Browser) -> None:
        self.vlm = vlm
        self.browser = browser
