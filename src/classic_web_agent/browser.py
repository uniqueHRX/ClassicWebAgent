"""Playwright 浏览器驱动 —— 启动管理 + 原子操作封装。

原子操作：click, type, scroll, navigate, screenshot, js_eval 等。
"""

from typing import Any


class Browser:
    """Playwright 浏览器管理器。"""
