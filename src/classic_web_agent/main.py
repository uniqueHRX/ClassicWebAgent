"""CLI 交互界面 —— argparse 命令行入口。

用法：
    python -m classic_web_agent --task "在百度搜索天气"
    python scripts/run.py "在百度搜索天气"
"""

import argparse
import sys

from classic_web_agent.config import load_config
from classic_web_agent.agent.core import Agent


def main() -> None:
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
    agent = Agent(config)
    agent.run(args.task)


if __name__ == "__main__":
    main()
