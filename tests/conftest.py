"""pytest 全局配置 —— logger 输出到 log/Tests.log（每次运行插入文件顶端）。"""

import logging
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv


# ── 日志文件配置 ─────────────────────────────────────────────────────────────

_log_handler: logging.Handler | None = None
"""当前 session 的文件 handler，session 结束时清理。"""


def pytest_configure(config: pytest.Config) -> None:
    """将 logger 输出重定向到 log/Tests.tmp。
    
    Session 结束时 prepend 到 log/Tests.log，实现"每次运行插入文件顶端"。
    """
    global _log_handler

    # verbose 但不捕获 stdout（VSCode 测试面板兼容）
    config.option.verbose = 1
    config.option.capture = "no"
    # 关闭 pytest 自身的 CLI 日志输出
    config.option.log_cli = False

    # 日志目录
    log_dir = Path("log")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 临时文件：当前 session 的所有日志先写入这里
    tmp_log = log_dir / "Tests.tmp"

    # 创建 FileHandler（写模式，每次 session 重新创建）
    _log_handler = logging.FileHandler(str(tmp_log), mode="w", encoding="utf-8")
    _log_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    root = logging.getLogger()
    root.addHandler(_log_handler)
    root.setLevel(logging.INFO)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Session 结束时将临时日志 prepend 到 Tests.log。"""
    global _log_handler

    log_dir = Path("log")
    tmp_log = log_dir / "Tests.tmp"

    if not tmp_log.exists():
        return

    # 移除 handler 并关闭文件
    if _log_handler is not None:
        root = logging.getLogger()
        root.removeHandler(_log_handler)
        _log_handler.close()
        _log_handler = None

    # 读取本次 session 的日志
    new_content = tmp_log.read_text(encoding="utf-8")
    if not new_content.strip():
        tmp_log.unlink(missing_ok=True)
        return

    # 添加 session 分隔头
    header = (
        f"\n{'='*60}\n"
        f"  Test Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'='*60}\n\n"
    )

    # 读取已有的 Tests.log 内容
    log_file = log_dir / "Tests.log"
    old_content = log_file.read_text(encoding="utf-8") if log_file.exists() else ""

    # 写入：新内容 + 旧内容（实现"插入文件顶端"）
    log_file.write_text(header + new_content + old_content, encoding="utf-8")

    # 清理临时文件
    tmp_log.unlink(missing_ok=True)


# ── 环境变量加载 ──────────────────────────────────────────────────────────────

_test_env = Path(".env.test")
if _test_env.exists():
    load_dotenv(_test_env, override=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def browser() -> "Browser":
    """创建有头浏览器实例。"""
    from classic_web_agent.browser import Browser
    b = Browser(headless=False)
    b.launch()
    yield b
    b.close()


def _check_playwright_browser() -> bool:
    """检查 Playwright Chromium 是否可用。"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


playwright_available: bool = _check_playwright_browser()
