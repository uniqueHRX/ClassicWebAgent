"""SubAgent 集成测试 —— 真实 VLM + 浏览器，模拟 LLM 派发子任务。"""

import logging
import os
from pathlib import Path

import pytest

from classic_web_agent.common.memory import Memory
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)


@pytest.mark.skipif(
    not __import__("tests.conftest", fromlist=["playwright_available"]).playwright_available,
    reason="需要 Playwright 浏览器（安装: playwright install chromium）",
)
@pytest.mark.integration
class TestSubAgentIntegration:
    """SubAgent 集成测试 —— 模拟 LLM 派发详细子任务。"""

    @pytest.fixture(autouse=True)
    def check_vlm(self) -> None:
        """检查 VLM API 和 .env.test 是否就绪。"""
        if not os.getenv("VLM_API_KEY"):
            pytest.skip("VLM_API_KEY 未设置，跳过集成测试")

    def test_subagent_complete_task(self) -> None:
        """模拟 LLM 派发一个详细的搜索任务，验证 SubAgent 完整流程。"""
        from classic_web_agent.browser import Browser
        from classic_web_agent.subagent import SubAgent

        # ── 模拟 LLM 生成的详细子任务描述 ──
        sub_task = (
            "访问 example.com 页面，确认页面标题是否为 'Example Domain'，"
            "并在页面上找到 'More information' 链接的 URL。"
            "完成后用中文总结页面内容。"
        )

        vlm = LLMClient(mode="vlm")
        memory = Memory()

        with Browser(headless=False) as browser:
            sub = SubAgent(vlm=vlm, browser=browser, memory=memory)
            observations = sub.run(sub_task=sub_task)

        # ── 验证 ──
        assert observations is not None
        logger.info("SubAgent 返回的 observations (%d 字符):\n%s",
                     len(observations), observations)

        # observations 不应为空（VLM 至少记录了某些内容）
        assert len(observations) > 0, (
            "SubAgent 未返回任何 observations"
        )

        logger.info("SubAgent 集成测试通过 ✓")

    def test_subagent_navigate_and_extract(self) -> None:
        """多步任务：导航 → 等待 → 提取信息。"""
        from classic_web_agent.browser import Browser
        from classic_web_agent.subagent import SubAgent

        sub_task = (
            "打开 https://example.com，等待页面完全加载，"
            "然后提取页面中的链接列表。"
            "提取元数据中的 content-type 信息。"
        )

        vlm = LLMClient(mode="vlm")
        memory = Memory()

        with Browser(headless=False) as browser:
            sub = SubAgent(vlm=vlm, browser=browser, memory=memory)
            observations = sub.run(sub_task=sub_task)

        logger.info("多步任务 observations (%d 字符):\n%s",
                     len(observations), observations)
        assert len(observations) > 0
        logger.info("多步导航提取测试通过 ✓")

    def test_subagent_search_like(self) -> None:
        """模拟类似搜索的任务：使用浏览器访问一个页面并收集结构化信息。"""
        from classic_web_agent.browser import Browser
        from classic_web_agent.subagent import SubAgent

        sub_task = (
            # "访问 Github Trending 页面 https://github.com/trending，"
            # "查看当前有哪些热门仓库。"
            # "提取前三个仓库的名称和描述。"
            "访问 https://arxiv.org/list/cs.AI/recent，查看最近提交的论文列表。"
            "提取前三篇论文的标题和摘要。"
            "并找到这三篇论文的 PDF 链接。"
        )

        vlm = LLMClient(mode="vlm")
        memory = Memory()

        with Browser(headless=False) as browser:
            sub = SubAgent(vlm=vlm, browser=browser, memory=memory)
            observations = sub.run(sub_task=sub_task)

        logger.info("搜索任务 observations (%d 字符):\n%s",
                     len(observations), observations)
        assert len(observations) > 0
        logger.info("搜索型子任务测试通过 ✓")
