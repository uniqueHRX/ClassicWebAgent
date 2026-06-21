"""LLM 规划器 —— ReAct 风格逐步推理。

构建上下文，调用 LLM 生成 Thought + Action。
"""

from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.agent.memory import Memory


class Planner:
    """LLM 规划器。"""

    def __init__(self, memory: Memory, llm: LLMClient) -> None:
        self.memory = memory
        self.llm = llm
