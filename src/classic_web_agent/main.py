"""CLI 交互界面 —— argparse 命令行入口。

用法：
    python -m classic_web_agent --task "帮我调研AI热门论文"
    python scripts/run.py "帮我调研AI热门论文"

运行目录：
    log/YYYY-MM-DD-NNNN/
    ├── run.log         # 完整运行日志
    ├── report.md       # 最终报告
    └── screenshot/     # 截图（当 log_screenshot=true）
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from classic_web_agent.agent.core import Agent
from classic_web_agent.browser import Browser
from classic_web_agent.config import load_config
from classic_web_agent.common.memory import Memory
from classic_web_agent.llm import LLMClient
from classic_web_agent.logger import Logger

logger = logging.getLogger(__name__)


def _create_run_dir(base_dir: Path) -> Path:
    """创建运行目录 log/YYYY-MM-DD-NNNN/。

    自动递增序号防止覆盖。
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    sequence = 1
    while True:
        dir_name = f"{date_str}-{sequence:04d}"
        run_dir = base_dir / dir_name
        if not run_dir.exists():
            run_dir.mkdir(parents=True, exist_ok=True)
            return run_dir
        sequence += 1


def _setup_file_logging(run_dir: Path, log_level: str = "INFO") -> logging.Handler:
    """设置文件日志处理器，写入 run.log。

    Args:
        run_dir: 运行目录。
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR）。

    Returns:
        文件处理器实例。
    """
    log_path = run_dir / "run.log"
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    # 设置根 logger 级别（默认 WARNING，必须改为 INFO 才能通过）
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    print(f"[Main] 日志级别: {logging.getLevelName(level)}, 日志文件: {log_path}")
    return handler


def create_agent(config: dict[str, Any]) -> Agent:
    """工厂函数：组装 Agent 的所有依赖并注入。

    Args:
        config: 全局配置字典。

    Returns:
        配置完成的 Agent 实例。
    """
    agent = Agent(config)

    # LLM/VLM 客户端
    agent.llm = LLMClient(mode="llm")
    agent.vlm = LLMClient(mode="vlm")

    # 浏览器（支持持久化 user_data_dir）
    user_data_dir = config.get("user_data_dir", "") or None
    agent.browser = Browser(
        headless=config.get("headless", False),
        user_data_dir=user_data_dir,
    )
    agent.browser.launch()

    # 记忆
    agent.memory = Memory()

    # Logger 将在 main() 中注入（需要 run_dir）
    agent.logger = Logger()

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

    # 1. 加载配置
    config = load_config()

    # 2. 创建运行目录
    log_base = Path("log")
    log_base.mkdir(exist_ok=True)
    run_dir = _create_run_dir(log_base)
    print(f"[Main] 运行目录: {run_dir}")

    # 3. 设置文件日志（使用配置的日志级别）
    log_level = config.get("log_level", "INFO")
    file_handler = _setup_file_logging(run_dir, log_level)
    logger.info("=== ClassicWebAgent 运行开始 ===")
    logger.info("任务: %s", args.task)

    # 4. 配置 Logger（注入 run_dir）
    agent_logger = Logger(run_dir=run_dir)

    # 5. 创建 Agent
    agent = create_agent(config)
    agent.logger = agent_logger

    # 6. 执行任务
    try:
        result = agent.run(args.task)
        logger.info("任务状态: %s", "成功" if result.success else "失败")
        logger.info("总子任务数: %d", result.total_steps)

        # 7. 保存报告
        report_format = config.get("report_format", "md")

        if report_format == "both":
            if result.md_report:
                md_path = agent_logger.save_report(result.md_report, args.task, "md")
                if md_path:
                    logger.info("报告已保存 (MD): %s", md_path)
            if result.html_report:
                html_path = agent_logger.save_report(result.html_report, args.task, "html")
                if html_path:
                    logger.info("报告已保存 (HTML): %s", html_path)
        else:
            if result.summary:
                report_path = agent_logger.save_report(result.summary, args.task, report_format)
                if report_path:
                    logger.info("报告已保存: %s", report_path)
    except Exception as e:
        logger.exception("任务执行异常: %s", e)
        result = None
    finally:
        # 8. 清理
        if agent.browser:
            try:
                agent.browser.close()
                logger.info("浏览器已关闭")
            except Exception as e:
                logger.warning("浏览器关闭异常: %s", e)

        # 移除文件 handler 避免日志重复
        root_logger = logging.getLogger()
        root_logger.removeHandler(file_handler)
        file_handler.close()

    # 9. 输出结果摘要
    if result:
        status_icon = "✅" if result.success else "❌"
        report_format = config.get("report_format", "md")
        print(f"\n{status_icon} 任务{'完成' if result.success else '失败'}")
        print(f"   子任务数: {result.total_steps}")
        if report_format == "both":
            print(f"   报告文件 (MD):   {run_dir / 'report.md'}")
            print(f"   报告文件 (HTML): {run_dir / 'report.html'}")
        else:
            report_ext = "html" if report_format == "html" else "md"
            print(f"   报告文件: {run_dir / f'report.{report_ext}'}")
    else:
        print("\n❌ 任务异常终止")
        print(f"   日志文件: {run_dir / 'run.log'}")

    sys.exit(0 if result and result.success else 1)


if __name__ == "__main__":
    main()
