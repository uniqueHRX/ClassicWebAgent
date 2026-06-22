"""Memory 单元测试 —— knowledge + observations + working + url_stack。"""

import logging

from classic_web_agent.agent.memory import Memory
from classic_web_agent.agent.types import KnowledgeItem, MemoryEntry

logger = logging.getLogger(__name__)


class TestMemoryKnowledge:
    """知识库（LLM 维护）测试。"""

    def test_add_and_get_knowledge(self) -> None:
        """按 category/key 存取知识。"""
        mem = Memory()
        mem.add_knowledge(category="价格", key="京东", value="5999元")
        mem.add_knowledge(category="价格", key="淘宝", value="5799元")
        mem.add_knowledge(category="评价", key="京东", value="4.5星")

        # 按 category + key 检索
        items = mem.get_knowledge(category="价格", key="京东")
        assert len(items) == 1
        assert items[0].value == "5999元"

        # 按 category 检索
        items = mem.get_knowledge(category="价格")
        assert len(items) == 2

        # 全部检索
        all_items = mem.get_knowledge()
        assert len(all_items) == 3
        logger.info("knowledge 存取 ✓")

    def test_add_knowledge_with_metadata(self) -> None:
        """知识条目携带来源和子任务 ID。"""
        mem = Memory()
        mem.add_knowledge(
            category="论文摘要",
            key="论文A",
            value="A Novel Approach...",
            source_url="https://arxiv.org/abs/1234",
            sub_task_id=1,
        )
        items = mem.get_knowledge(category="论文摘要")
        assert items[0].source_url == "https://arxiv.org/abs/1234"
        assert items[0].sub_task_id == 1
        logger.info("knowledge 元数据 ✓")

    def test_get_knowledge_no_match(self) -> None:
        """检索不存在的 key 返回空列表。"""
        mem = Memory()
        assert mem.get_knowledge(category="不存在") == []
        logger.info("knowledge 无匹配 → 空列表 ✓")

    def test_format_knowledge_summary(self) -> None:
        """格式化输出知识摘要。"""
        mem = Memory()
        mem.add_knowledge(category="价格", key="京东", value="5999元")
        mem.add_knowledge(category="价格", key="淘宝", value="5799元")
        summary = mem.format_knowledge_summary()
        assert "价格" in summary
        assert "京东" in summary
        assert "5999元" in summary
        assert "淘宝" in summary
        assert "5799元" in summary
        logger.info("format_knowledge_summary ✓")

    def test_format_knowledge_summary_empty(self) -> None:
        """空知识库返回空字符串。"""
        mem = Memory()
        assert mem.format_knowledge_summary() == ""
        logger.info("空知识库 format → '' ✓")

    def test_clear_knowledge(self) -> None:
        """清空知识库。"""
        mem = Memory()
        mem.add_knowledge(category="价格", key="京东", value="5999元")
        assert len(mem.get_knowledge()) == 1
        mem.clear_knowledge()
        assert len(mem.get_knowledge()) == 0
        logger.info("clear_knowledge ✓")


class TestMemoryObservations:
    """观察日志（VLM 维护）测试。"""

    def test_add_and_get_observations(self) -> None:
        """追加观察日志并拼接返回。"""
        mem = Memory()
        mem.add_observation("找到论文A: A Novel Approach")
        mem.add_observation("摘要: This paper explores...")
        result = mem.get_observations()
        assert "找到论文A" in result
        assert "摘要" in result
        logger.info("observations 追加 ✓")

    def test_clear_observations(self) -> None:
        """清空观察日志（子任务开始前）。"""
        mem = Memory()
        mem.add_observation("test")
        assert len(mem.observations) == 1
        mem.clear_observations()
        assert len(mem.observations) == 0
        logger.info("clear_observations ✓")

    def test_get_observations_empty(self) -> None:
        """空观察日志返回空字符串。"""
        mem = Memory()
        assert mem.get_observations() == ""
        logger.info("空 observations → '' ✓")


class TestMemoryWorking:
    """操作记录（VLM/Executor 维护）测试。"""

    def test_add_and_get_working(self) -> None:
        """按顺序记录操作步骤。"""
        mem = Memory()
        mem.add_working(MemoryEntry(role="assistant", content="Step 1"))
        mem.add_working(MemoryEntry(role="assistant", content="Step 2"))
        assert len(mem.get_working()) == 2
        logger.info("working 存取 ✓")

    def test_get_working_limit(self) -> None:
        """限制返回最近 N 条。"""
        mem = Memory()
        for i in range(10):
            mem.add_working(MemoryEntry(role="assistant", content=f"Step {i}"))
        recent = mem.get_working(limit=3)
        assert len(recent) == 3
        assert recent[-1].content == "Step 9"
        logger.info("working limit ✓")

    def test_clear_working(self) -> None:
        """清空操作记录。"""
        mem = Memory()
        mem.add_working(MemoryEntry(role="assistant", content="Step 1"))
        mem.clear_working()
        assert len(mem.get_working()) == 0
        logger.info("clear_working ✓")


class TestMemoryURLStack:
    """URL 导航栈测试。"""

    def test_push_pop_peek(self) -> None:
        mem = Memory()
        mem.push_url("https://example.com")
        mem.push_url("https://example.com/page2")
        assert mem.peek_url() == "https://example.com/page2"
        assert mem.pop_url() == "https://example.com/page2"
        assert mem.peek_url() == "https://example.com"
        logger.info("URL 栈 push/pop/peek ✓")

    def test_pop_empty(self) -> None:
        mem = Memory()
        assert mem.pop_url() is None
        logger.info("空 URL 栈 pop → None ✓")

    def test_peek_empty(self) -> None:
        mem = Memory()
        assert mem.peek_url() is None
        logger.info("空 URL 栈 peek → None ✓")


class TestMemoryStepIndex:
    """步骤计数测试。"""

    def test_step_index_default(self) -> None:
        mem = Memory()
        assert mem.step_index == 0
        logger.info("step_index 默认值 ✓")

    def test_step_index_increment(self) -> None:
        mem = Memory()
        mem.step_index = 1
        assert mem.step_index == 1
        logger.info("step_index 递增 ✓")
