"""Planner 测试 —— 单元测试 + 集成测试（真实 VLM API）。"""

import json
import logging
import base64
import io
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from classic_web_agent.common.action import ActionType
from classic_web_agent.subagent.planner import Planner
from classic_web_agent.common.memory import Memory
from classic_web_agent.common.types import Action, PageState
from classic_web_agent.llm import LLMClient

logger = logging.getLogger(__name__)

# ── 辅助 ────────────────────────────────────────────────────────────────


def _dummy_screenshot() -> str:
    """生成 1x1 红色 PNG 的 data URI（用于 VLM 测试）。"""
    from PIL import Image
    img = Image.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _dummy_page_state(
    url: str = "https://example.com",
    tree: str = "\t [3]<a href=https://example.com />\n\t\tExample Domain",
) -> PageState:
    """创建简化的 PageState 用于测试。"""
    return PageState(
        screenshot=_dummy_screenshot(),
        url=url,
        title="Example Page",
        tree_text=tree,
        current_tab_id="tab_0",
        tabs_list="  tab_0: https://example.com - Example Page ← 当前",
    )


# ══════════════════════════════════════════════════════════════════════════
# 单元测试
# ══════════════════════════════════════════════════════════════════════════


class TestPlannerUnit:
    """Planner 单元测试 —— Mock VLM，测试 prompt 加载/解析/校验。"""

    def test_load_prompt(self):
        """planner.yaml 应被正确加载。"""
        planner = Planner(vlm=None)
        assert planner._data is not None
        assert "system" in planner._data
        assert "user" in planner._data
        logger.info("YAML 加载 ✓")

    def test_render_system(self):
        """system prompt 应包含所有关键段落。"""
        planner = Planner(vlm=None)
        text = planner._render_system()
        assert "网页操作助手" in text
        assert "任务目标" in text
        assert "元素交互" in text
        assert "CLICK" in text
        assert "confidence" in text
        assert "DONE" in text
        logger.info("system prompt 渲染 ✓ (%d 字符)", len(text))

    def test_render_user(self):
        """user 模板的占位符应被正确替换。"""
        planner = Planner(vlm=None)
        # 模拟 conftest.py 加载了 .env.test
        from dotenv import load_dotenv
        env_path = Path(".env.test")
        if env_path.exists():
            load_dotenv(env_path, override=True)

        text = planner._render_user(
            sub_task="测试搜索",
            step_number=1,
            max_steps=50,
            url="https://example.com",
            tree_text="\t [3]<a href=... />",
            last_result="上一步成功",
            observations="【价格】京东: 5999元",
            recent_actions="  [0] GOTO → 导航到 example.com",
            current_tab_id="tab_0",
            tabs_list="  tab_0: https://example.com - Example ← 当前",
        )
        assert "测试搜索" in text
        assert "1/50" in text
        assert "tab_0" in text
        assert "上一步成功" in text
        assert "京东: 5999元" in text
        assert "data:image" not in text  # 截图应该通过 image_url 单独传入
        logger.info("user prompt 渲染 ✓")

    def test_parse_valid_response(self):
        """VLM 的完整 JSON 返回应正确解析。"""
        raw = json.dumps({
            "thinking": "页面是搜索结果页，找到搜索框。",
            "verification": "上一步 WAIT 后页面加载完成。Verdict: Success",
            "memory": "搜索到结果，第一条链接标题包含'目标信息'",
            "goal": "点击第一个搜索结果链接",
            "actions": [{"type": "CLICK", "element_id": 3}],
            "confidence": 0.95,
        })
        result = Planner._parse(raw)
        assert result is not None
        assert result["thinking"] == "页面是搜索结果页，找到搜索框。"
        assert result["actions"][0]["type"] == "CLICK"
        logger.info("JSON 解析 ✓")

    def test_parse_missing_field(self):
        """VLM 返回缺少必要字段时应返回 None。"""
        raw = json.dumps({"thinking": "test"})  # 缺少其他字段
        result = Planner._parse(raw)
        assert result is None
        logger.info("缺字段检测 ✓")

    def test_parse_invalid_actions(self):
        """VLM 返回非法动作类型时应返回 None。"""
        raw = json.dumps({
            "thinking": "test",
            "verification": "Success",
            "memory": "",
            "goal": "test",
            "actions": [{"type": "INVALID_ACTION"}],
            "confidence": 0.9,
        })
        result = Planner._parse(raw)
        assert result is None
        logger.info("非法动作检测 ✓")

    def test_to_actions_click(self):
        """CLICK 动作转换为 Action 对象。"""
        actions = Planner._to_actions([
            {"type": "CLICK", "element_id": 1548},
        ])
        assert len(actions) == 1
        assert actions[0].action_type == "CLICK"
        assert actions[0].element_id == 1548
        logger.info("CLICK → Action ✓")

    def test_to_actions_type(self):
        """TYPE 动作包含元素 ID 和文本。"""
        actions = Planner._to_actions([
            {"type": "TYPE", "element_id": 10, "text": "笔记本电脑"},
        ])
        assert actions[0].action_type == "TYPE"
        assert actions[0].element_id == 10
        assert actions[0].text == "笔记本电脑"
        logger.info("TYPE → Action ✓")

    def test_to_actions_sequence(self):
        """短序列动作应全部转换为 Action 对象。"""
        actions = Planner._to_actions([
            {"type": "TYPE", "element_id": 10, "text": "笔记本电脑"},
            {"type": "CLICK", "element_id": 12},
        ])
        assert len(actions) == 2
        assert actions[0].action_type == "TYPE"
        assert actions[1].action_type == "CLICK"
        logger.info("动作序列转换 ✓")

    def test_to_actions_scroll(self):
        """SCROLL 动作的 direction 应放入 extra。"""
        actions = Planner._to_actions([
            {"type": "SCROLL", "direction": "down"},
        ])
        assert actions[0].action_type == "SCROLL"
        assert actions[0].extra == {"direction": "down"}
        logger.info("SCROLL → Action ✓")

    def test_plan_no_vlm_returns_done(self):
        """VLM 未初始化时 plan() 返回 [DONE]。"""
        planner = Planner(vlm=None, memory=Memory())
        actions = planner.plan(state=_dummy_page_state(), sub_task="测试")
        assert len(actions) == 1
        assert actions[0].action_type == "DONE"
        logger.info("无 VLM → [DONE] ✓")


# ══════════════════════════════════════════════════════════════════════════
# 集成测试
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestPlannerIntegration:
    """集成测试 —— 需要真实 VLM API（.env.test），默认跳过。"""

    @pytest.fixture(autouse=True)
    def check_vlm(self) -> None:
        """检查 VLM API 是否可用。"""
        if not os.getenv("VLM_API_KEY"):
            pytest.skip("VLM_API_KEY 未设置，跳过 VLM 集成测试")

    def test_planner_calls_vlm(self) -> None:
        """Planner.plan() 调用真实 VLM，应返回合法动作序列。"""
        vlm = LLMClient(mode="vlm")
        memory = Memory()
        state = _dummy_page_state()

        planner = Planner(vlm=vlm, memory=memory)
        actions = planner.plan(
            state=state,
            sub_task="查看当前页面内容，确认页面标题",
            step_number=1,
            max_steps=50,
        )

        # VLM 返回的动作必须通过校验（合法动作类型）
        assert len(actions) > 0, "VLM 应返回至少一个动作"
        valid_types = {e.name for e in ActionType}
        for a in actions:
            assert a.action_type in valid_types, (
                f"非法动作类型: {a.action_type}"
            )
            logger.info("  → %s (element_id=%s, text=%s, extra=%s)",
                         a.action_type, a.element_id, a.text, a.extra)

        # memory 字段应被自动记录到 observations
        obs = memory.get_observations()
        if obs:
            logger.info("VLM 自动记录了 observations:\n%s", obs)
        else:
            logger.info("VLM 本次未记录 observations（正常，空页面）")

        logger.info("Planner API 集成测试通过 ✓ (%d 个动作)", len(actions))
