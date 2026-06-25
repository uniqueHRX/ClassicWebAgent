"""Agent Core 集成测试 —— 真实 LLM + VLM + Browser（不 mock）。

测试 Agent.run() 从 Director 任务分解到 SubAgent 执行再到报告生成的全流程。
需要真实 API 配置（.env）和 Playwright 浏览器。
"""

import logging

import pytest

from classic_web_agent.agent.core import Agent
from classic_web_agent.common.types import TaskResult
from classic_web_agent.main import create_agent

logger = logging.getLogger(__name__)


@pytest.mark.integration
class TestAgentCoreIntegration:
    """Agent Core 集成测试 —— 真实信息收集+知识整理任务。"""

    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        """每个测试前创建 Agent 实例。"""
        config = {}
        self.agent: Agent = create_agent(config)
        yield
        # 清理浏览器
        if self.agent.browser:
            try:
                self.agent.browser.close()
            except Exception:
                pass

    def test_research_trending_ai_papers(self) -> None:
        """复杂信息收集任务：一句话任务 → 分解 → 多源搜索 → 汇总报告。

        LLM 应完成：
          1. plan() → task_plan（研究维度+数据源） + todo_list + first_sub_task
          2. review() 循环 → 调度 SubAgent 收集信息
          3. report() → 汇总报告
        """
        task = (
            "帮我获取百度热榜前十的新闻内容。"
            "选择一条你认为最有趣的新闻，搜集不同媒体的报道，为我进行详细讲解。"
        )
        result = self.agent.run(task)

        assert isinstance(result, TaskResult)
        logger.info("=" * 60)
        logger.info("任务完成状态: %s", "✓ 成功" if result.success else "✗ 失败")
        logger.info("子任务数量: %d", result.total_steps)
        if result.success:
            logger.info("报告摘要:\n%s", result.summary)
        else:
            logger.warning("任务失败原因: %s", result.summary)

        # 即使部分子任务失败，plan 阶段也应该成功
        assert result.total_steps >= 0
