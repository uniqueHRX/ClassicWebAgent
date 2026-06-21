"""感知模块 —— VLM 视觉分析 + DOM 解析 + 多模态融合 + 元素定位。

设计详见 docs/perception-design.md：
- CDP 三流采集：DOM 骨架 + AX 语义 + 布局数据
- 构建 Enhanced DOM Tree → 序列化 → PageState
- 阶段一：返回空 PageState（stub）
"""

from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.browser import Browser
from classic_web_agent.agent.types import PageState


class Perception:
    """多模态感知器 —— 将页面截图与 DOM 信息整合为结构化输入。"""

    def __init__(self, vlm: LLMClient | None, browser: Browser | None) -> None:
        self.vlm = vlm
        self.browser = browser

    def observe(self) -> PageState:
        """观察当前页面状态，返回 PageState。

        阶段一（stub）：不调用 VLM/Browser，返回空 PageState。
        阶段二：实现 CDP 三流采集 + VLM 视觉分析。
        """
        # stub：返回空状态
        return PageState()
