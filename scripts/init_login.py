#!/usr/bin/env python
"""登录初始化脚本 —— 打开有头浏览器让用户手动登录网站。

自动读取 config/config.json 的 browser_engine 和对应的 user_data_dir，
使用正确的浏览器引擎（Playwright / CloakBrowser）和 profile 目录。

用法：
    python scripts/init_login.py
    python scripts/init_login.py --profile "./chrome_profile"   # 覆盖 profile 目录
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from classic_web_agent.config import load_config

# Agent 已登录（可优先使用）的网站列表
LOGIN_SITES = [
    ("百度", "https://www.baidu.com"),
    ("京东", "https://www.jd.com"),
    ("知乎", "https://www.zhihu.com"),
    ("豆瓣", "https://www.douban.com"),
]


def main() -> None:
    # 读取配置文件，确定浏览器引擎和 profile 目录
    config = load_config()
    engine = config.get("browser_engine", "playwright")
    engine_cfg = config.get(engine, {})
    default_profile = engine_cfg.get("user_data_dir", "") or (
        "./chrome_profile" if engine == "playwright" else "./cloak_profile"
    )

    parser = argparse.ArgumentParser(
        description="登录初始化 —— 手动登录并持久化登录态",
    )
    parser.add_argument(
        "--profile", "-p",
        type=str,
        default=default_profile,
        help=f"用户数据目录（默认根据 browser_engine 自动选择: {default_profile}）",
    )
    args = parser.parse_args()

    profile_path = Path(args.profile).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    print(f"🔧 浏览器引擎: {engine}")
    print(f"🔧 用户数据目录: {profile_path}")

    print("=" * 60)
    print(f"🚀 正在启动 {engine} 浏览器...")
    print("📌 已为您打开以下网站，请在各个网站上完成登录：")
    for name, url in LOGIN_SITES:
        print(f"   • {name}: {url}")
    print("📌 登录完成后，关闭浏览器窗口/标签页，或按 Ctrl+C 退出。")
    print("📌 所有登录状态（cookies/localStorage）将自动保存。")
    print("=" * 60)

    try:
        if engine == "cloakbrowser":
            _launch_cloakbrowser(profile_path)
        else:
            _launch_playwright(profile_path)
    except KeyboardInterrupt:
        print("\n✅ 用户中断，登录态已保存。")
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        sys.exit(1)

    print(f"💾 用户数据目录: {profile_path}")
    print("🎉 完成！运行 Agent 时将自动使用此登录态。")


def _launch_playwright(profile_path: Path) -> None:
    """使用标准 Playwright Chromium 启动。"""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            no_viewport=True,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        _open_sites(ctx)
        _wait_for_close(ctx)
    print("✅ 浏览器已关闭，登录态已保存。")


def _launch_cloakbrowser(profile_path: Path) -> None:
    """使用 CloakBrowser 启动。"""
    from cloakbrowser import launch_persistent_context

    ctx = launch_persistent_context(
        user_data_dir=str(profile_path),
        headless=False,
    )
    _open_sites(ctx)
    _wait_for_close(ctx)
    ctx.close()
    print("✅ CloakBrowser 已关闭，登录态已保存。")


def _open_sites(ctx) -> None:
    """在所有新标签页中打开目标网站。"""
    for name, url in LOGIN_SITES:
        page = ctx.new_page()
        try:
            page.goto(url, timeout=15000)
            print(f"🌐 已打开 {name}: {url}")
        except Exception:
            print(f"⚠️  {name} 打开超时，请手动刷新: {url}")

    print("\n⏳ 等待用户操作...（请在各网站完成登录，然后关闭浏览器）")


def _wait_for_close(ctx) -> None:
    """等待所有页面关闭（用户手动关闭浏览器）。"""
    while ctx.pages:
        try:
            for p in ctx.pages:
                if p.is_closed():
                    continue
                p.wait_for_close(timeout=30000)
        except Exception:
            pass


if __name__ == "__main__":
    main()
