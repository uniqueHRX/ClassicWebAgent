"""Agent 主框架的单元测试 —— 验证数据模型和工厂函数。"""

import logging

from classic_web_agent.main import create_agent
from classic_web_agent.agent.core import Agent
from classic_web_agent.common.action import ActionType
from classic_web_agent.common.types import (
    PageState,
    Action,
    ActionResult,
    MemoryEntry,
    AgentStep,
    Plan,
    PlanStep,
    TaskResult,
)

logger = logging.getLogger(__name__)


class TestAgentFramework:
    """Agent 主框架 —— 工厂函数、数据模型。"""

    def test_create_agent(self):
        """工厂函数应返回正确配置的 Agent 实例。"""
        config = {}
        agent = create_agent(config)
        assert isinstance(agent, Agent)
        assert agent.logger is not None
        assert agent.memory is not None
        assert agent.llm is not None
        assert agent.vlm is not None
        assert agent.browser is not None
        logger.info("Agent 创建成功 ✓")

    def test_action_type_values(self):
        """验证 21 个动作类型枚举。"""
        assert ActionType.CLICK.name == "CLICK"
        assert ActionType.TYPE.name == "TYPE"
        assert ActionType.HOVER.name == "HOVER"
        assert ActionType.MOUSE_CLICK.name == "MOUSE_CLICK"
        assert ActionType.SCROLL.name == "SCROLL"
        assert ActionType.PRESS.name == "PRESS"
        assert ActionType.WAIT.name == "WAIT"
        assert ActionType.GOTO.name == "GOTO"
        assert ActionType.GO_BACK.name == "GO_BACK"
        assert ActionType.GO_FORWARD.name == "GO_FORWARD"
        assert ActionType.NEW_TAB.name == "NEW_TAB"
        assert ActionType.CLOSE_TAB.name == "CLOSE_TAB"
        assert ActionType.SWITCH_TAB.name == "SWITCH_TAB"
        assert ActionType.SCREENSHOT.name == "SCREENSHOT"
        assert ActionType.EXTRACT.name == "EXTRACT"
        assert ActionType.FIND.name == "FIND"
        assert ActionType.THINK.name == "THINK"
        assert ActionType.REMEMBER.name == "REMEMBER"
        assert ActionType.RECALL.name == "RECALL"
        assert ActionType.DONE.name == "DONE"
        assert ActionType.FAIL.name == "FAIL"
        assert len(ActionType) == 21
        logger.info("21 个动作类型验证通过 ✓")

    def test_page_state_defaults(self):
        """PageState 所有字段应有合理的默认值。"""
        state = PageState()
        assert state.screenshot == ""
        assert state.url == ""
        assert state.title == ""
        assert state.tree_text == ""
        logger.info("PageState 默认值验证通过 ✓")

    def test_action_defaults(self):
        """Action 的默认值验证。"""
        action = Action()
        assert action.action_type == ""
        assert action.element_id is None
        assert action.text is None
        assert action.confidence == 1.0
        logger.info("Action 默认值验证通过 ✓")

    def test_plan_defaults(self):
        """Plan 和 PlanStep 的默认值。"""
        plan = Plan()
        assert plan.steps == []
        assert plan.current_step is None

        step = PlanStep(id=0, goal="测试")
        assert step.status == "pending"
        logger.info("Plan/PlanStep 默认值验证通过 ✓")

    def test_task_result(self):
        """TaskResult 包含完整的执行摘要。"""
        result = TaskResult(success=True, summary="完成", total_steps=5)
        assert result.success is True
        assert result.summary == "完成"
        assert result.total_steps == 5
        logger.info("TaskResult 验证通过 ✓")

    def test_memory_working(self):
        """Memory 的工作记忆应正确存取。"""
        from classic_web_agent.common.memory import Memory

        mem = Memory()
        mem.add_working(MemoryEntry(role="user", content="你好"))
        mem.add_working(MemoryEntry(role="assistant", content="世界"))
        assert len(mem.get_working()) == 2
        assert mem.get_working(limit=1)[0].content == "世界"
        logger.info("Memory 工作记忆存取验证通过 ✓")

    def test_action_space_validate(self):
        """ActionSpace.validate 阶段一应放行所有动作。"""
        from classic_web_agent.common.action import ActionSpace

        space = ActionSpace()
        action = Action(action_type="CLICK")
        state = PageState()
        assert space.validate(action, state) is True
        logger.info("ActionSpace.validate 验证通过 ✓")
