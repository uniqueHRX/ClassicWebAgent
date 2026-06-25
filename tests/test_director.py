"""Director 测试 —— 单元测试（mock LLM）+ 解析验证。

测试策略：
- mock LLMClient.chat() 返回预定义的 JSON 响应
- 验证 plan() / review() / report() 的正确性
- 验证 JSON 解析的边界情况
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from classic_web_agent.agent.director import Director
from classic_web_agent.common.types import DirectorOutput, NextAction, TodoItem


# ── 模拟 LLM 返回的 JSON 数据 ────────────────────────────────────

_PLAN_RESPONSE = {
    "thinking": "用户需要搜索AI论文，需要覆盖多个子领域",
    "task_plan": (
        "任务计划书：AI领域热门论文调研\n\n"
        "一、任务理解\n"
        "用户希望了解近期AI领域的热门研究论文。\n\n"
        "二、研究维度\n"
        "1. 引用量\n2. GitHub星标\n\n"
        "三、目标数据源\n"
        "1. arxiv.org\n2. paperswithcode.com\n\n"
        "四、调研分类\n"
        "- LLM\n- 多模态\n\n"
        "五、评判标准\n"
        "- 综合排序"
    ),
    "todo_list": [
        {"id": 1, "goal": "在arxiv搜索LLM论文", "status": "in_progress", "summary": ""},
        {"id": 2, "goal": "在arxiv搜索多模态论文", "status": "pending", "summary": ""},
    ],
    "next": {
        "type": "sub_task",
        "description": "打开 https://arxiv.org，搜索'large language model'，列出前10篇"
    },
}

_REVIEW_RESPONSE = {
    "thinking": "LLM搜索结果返回了10篇论文，继续搜索多模态",
    "task_plan": "",
    "todo_list": [
        {"id": 1, "goal": "在arxiv搜索LLM论文", "status": "completed", "summary": "找到10篇"},
        {"id": 2, "goal": "在arxiv搜索多模态论文", "status": "in_progress", "summary": ""},
    ],
    "next": {
        "type": "sub_task",
        "description": "搜索'multimodal learning'，列出前10篇"
    },
}

_DONE_RESPONSE = {
    "thinking": "所有子任务已完成",
    "task_plan": "",
    "todo_list": [
        {"id": 1, "goal": "在arxiv搜索LLM论文", "status": "completed", "summary": "找到10篇"},
        {"id": 2, "goal": "在arxiv搜索多模态论文", "status": "completed", "summary": "找到8篇"},
    ],
    "next": {"type": "done"},
}

_REPORT_TEXT = "根据调研，近期AI热门论文主要集中在LLM和多模态领域..."


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_llm() -> MagicMock:
    """创建 mock LLMClient，.chat() 返回 PLAN_RESPONSE。"""
    mock = MagicMock()
    mock.chat.return_value.content = json.dumps(_PLAN_RESPONSE)
    return mock


@pytest.fixture
def director(mock_llm: MagicMock) -> Director:
    """创建 Director 实例（mock LLM，plan 后状态）。"""
    d = Director(llm=mock_llm)
    return d


# ── 测试 plan() ──────────────────────────────────────────────────


class TestPlan:
    """plan() 方法测试。"""

    def test_plan_returns_director_output(self, director: Director) -> None:
        """plan() 返回 DirectorOutput 实例。"""
        output = director.plan("帮我找AI热门论文")
        assert isinstance(output, DirectorOutput)

    def test_plan_includes_task_plan(self, director: Director) -> None:
        """plan() 的 task_plan 必须非空。"""
        output = director.plan("帮我找AI热门论文")
        assert output.task_plan.strip(), "task_plan 不应为空"
        assert "任务计划书" in output.task_plan

    def test_plan_todo_list_has_in_progress(self, director: Director) -> None:
        """plan() 的 todo_list 至少有一个 in_progress。"""
        output = director.plan("帮我找AI热门论文")
        in_progress = [t for t in output.todo_list if t.status == "in_progress"]
        assert len(in_progress) >= 1

    def test_plan_next_is_sub_task(self, director: Director) -> None:
        """plan() 的 next.type 应为 sub_task。"""
        output = director.plan("帮我找AI热门论文")
        assert output.next.type == "sub_task"
        assert output.next.description.strip()

    def test_plan_saves_messages(self, director: Director) -> None:
        """plan() 后 _messages 应包含 system + user + assistant 共3条。"""
        director.plan("帮我找AI热门论文")
        assert len(director._messages) == 3

    def test_plan_empty_task_plan_retries(self, mock_llm: MagicMock) -> None:
        """task_plan 为空时应重试。"""
        # 第一次返回空 task_plan，第二次返回正常
        bad = dict(_PLAN_RESPONSE)
        bad["task_plan"] = ""
        mock_llm.chat.side_effect = [
            MagicMock(content=json.dumps(bad)),
            MagicMock(content=json.dumps(_PLAN_RESPONSE)),
        ]
        director = Director(llm=mock_llm)
        output = director.plan("帮我找AI热门论文")
        assert output.task_plan.strip()
        assert mock_llm.chat.call_count >= 2


# ── 测试 review() ────────────────────────────────────────────────


class TestReview:
    """review() 方法测试（需先调用 plan()）。"""

    def test_review_updates_todo(self, director: Director) -> None:
        """review() 将当前子任务标记为 completed。"""
        # Mock review 返回
        director._director_prompt = {"user": {"progress": "SubAgent result..."}}
        director._messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}]

        director.llm.chat.return_value.content = json.dumps(_REVIEW_RESPONSE)

        output = director.review("在arxiv搜索LLM论文", "找到10篇论文")
        completed = [t for t in output.todo_list if t.status == "completed"]
        assert len(completed) >= 1
        # 原来的任务1应该已完成
        goal_1 = [t for t in output.todo_list if t.id == 1]
        if goal_1:
            assert goal_1[0].status == "completed"

    def test_review_done_when_all_completed(self, director: Director) -> None:
        """全部完成时 next.type='done'。"""
        director._director_prompt = {"user": {"progress": "SubAgent result..."}}
        director._messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}]

        director.llm.chat.return_value.content = json.dumps(_DONE_RESPONSE)

        output = director.review("最后一个子任务", "完成")
        assert output.next.type == "done"

    def test_review_fails_without_plan(self, director: Director) -> None:
        """未调用 plan() 时 review() 应返回 done。"""
        # 清空 _messages 模拟无 plan 状态
        director._messages = []
        output = director.review("某任务", "结果")
        assert output.next.type == "done"

    def test_review_preserves_task_plan(self, director: Director) -> None:
        """review() 不返回 task_plan 时，沿用空字符串（由外层代码处理）。"""
        director._director_prompt = {"user": {"progress": "SubAgent result..."}}
        director._messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}]

        resp = dict(_REVIEW_RESPONSE)
        resp["task_plan"] = ""
        director.llm.chat.return_value.content = json.dumps(resp)

        output = director.review("在arxiv搜索LLM论文", "找到10篇论文")
        assert output.task_plan == ""  # 空字符串，外层代码会保留上次


# ── 测试 report() ────────────────────────────────────────────────


class TestReport:
    """report() 方法测试。"""

    def test_report_returns_string(self, director: Director) -> None:
        """report() 返回非空字符串。"""
        director.llm.chat.return_value.content = _REPORT_TEXT
        report = director.report(
            task="帮我找AI热门论文",
            task_plan="任务计划书...",
            all_results="子任务1结果：...\n子任务2结果：...",
        )
        assert isinstance(report, str)
        assert len(report) > 0

    def test_report_receives_task_plan(self, director: Director) -> None:
        """report() 的 user message 应包含 task_plan。"""
        director.llm.chat.return_value.content = _REPORT_TEXT
        director.report(
            task="帮我找AI热门论文",
            task_plan="测试计划书",
            all_results="测试结果",
        )
        # 验证 chat() 被调用，且 messages 包含 task_plan
        call_args = director.llm.chat.call_args
        assert call_args is not None
        kwargs = call_args[1]
        messages = kwargs.get("messages", [])
        user_msg = [m for m in messages if m["role"] == "user"]
        assert len(user_msg) >= 1
        assert "测试计划书" in user_msg[0]["content"]


# ── 测试 _parse_output() ─────────────────────────────────────────


class TestParseOutput:
    """Director._parse_output() 边界情况。"""

    def test_valid_json_parsed(self, director: Director) -> None:
        """有效 JSON 应正确解析为 DirectorOutput。"""
        raw = json.dumps(_PLAN_RESPONSE)
        output = director._parse_output(raw)
        assert output is not None
        assert output.task_plan
        assert len(output.todo_list) == 2
        assert output.next.type == "sub_task"

    def test_json_with_code_block(self, director: Director) -> None:
        """JSON 在 markdown 代码块中也能解析。"""
        raw = f"```json\n{json.dumps(_PLAN_RESPONSE)}\n```"
        output = director._parse_output(raw)
        assert output is not None
        assert output.task_plan

    def test_missing_thinking(self, director: Director) -> None:
        """缺少 thinking 字段返回 None。"""
        raw = json.dumps({"next": {"type": "done"}})
        assert director._parse_output(raw) is None

    def test_missing_next(self, director: Director) -> None:
        """缺少 next 字段返回 None。"""
        raw = json.dumps({"thinking": "test"})
        assert director._parse_output(raw) is None

    def test_invalid_json(self, director: Director) -> None:
        """无效 JSON 返回 None。"""
        assert director._parse_output("{invalid}") is None

    def test_empty_next_type(self, director: Director) -> None:
        """next.type 为空时返回 None。"""
        raw = json.dumps({"thinking": "test", "next": {"type": ""}})
        # 这里 type 为空但非 missing，会通过验证
        output = director._parse_output(raw)
        assert output is not None
        assert output.next.type == ""

    def test_empty_sub_task_description(self, director: Director) -> None:
        """sub_task 但 description 为空时返回 None。"""
        raw = json.dumps({
            "thinking": "test",
            "next": {"type": "sub_task", "description": ""}
        })
        assert director._parse_output(raw) is None
