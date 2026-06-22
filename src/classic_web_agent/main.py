"""CLI 交互界面 —— argparse 命令行入口。

用法：
    python -m classic_web_agent --task "在百度搜索天气"
    python scripts/run.py "在百度搜索天气"

设计：
    main()       — CLI 入口，解析参数 → 创建 Agent → 执行任务
    create_agent — 工厂函数，组装 Agent 的所有依赖

    阶段一：所有子模块为 stub（不调用外部 API/Browser）
    阶段二：逐步替换为真实实现
"""

import argparse
import sys
from typing import Any

from classic_web_agent.config import load_config
from classic_web_agent.agent.core import Agent
from classic_web_agent.agent.action import ActionSpace
from classic_web_agent.agent.memory import Memory
from classic_web_agent.agent.perception import Perception
from classic_web_agent.agent.planner import Planner
from classic_web_agent.agent.executor import Executor
from classic_web_agent.agent.verifier import Verifier
from classic_web_agent.logger import Logger


def create_agent(config: dict[str, Any]) -> Agent:
    """工厂函数：组装 Agent 的所有依赖并注入。

    Args:
        config: 全局配置字典。

    Returns:
        配置完成的 Agent 实例。
    """
    logger = Logger()
    memory = Memory()
    action_space = ActionSpace()

    perception = Perception(vlm=None, browser=None)
    planner = Planner(vlm=None, memory=memory)
    executor = Executor(
        action_space=action_space,
        browser=None,
        memory=memory,
    )
    verifier = Verifier()

    agent = Agent(config)
    agent.logger = logger
    agent.memory = memory
    agent.action_space = action_space
    agent.perception = perception
    agent.planner = planner
    agent.executor = executor
    agent.verifier = verifier

    return agent


def main() -> None:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        prog="classic-web-agent",
        description="网页多模态 Agent - 自然语言指令驱动的网页自动化",
    )
    parser.add_argument(
        "--task", "-t",
        type=str,
        required=True,
        help="要执行的自然语言任务描述",
    )
    args = parser.parse_args()

    config = load_config()
    agent = create_agent(config)
    agent.run(args.task)


if __name__ == "__main__":
    main()
