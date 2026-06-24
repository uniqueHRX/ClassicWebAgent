#!/usr/bin/env python
"""登录初始化脚本 —— 打开有头浏览器让用户手动登录网站。

用法：
    python scripts/init_login.py
    python scripts/init_login.py --profile "./chrome_profile"

功能：
    1. 启动 Playwright Chromium（有头模式）
    2. 使用 user_data_dir 持久化登录态
    3. 自动打开百度、淘宝、京东、知乎、豆瓣主页面，方便用户登录
    4. 登录完成后关闭浏览器标签页或按 Ctrl+C 退出
    5. 所有 cookies/localStorage 自动保存到 user_data_dir
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Agent 已登录（可优先使用）的网站列表
LOGIN_SITES = [
    ("百度", "https://www.baidu.com"),
    ("淘宝", "https://www.taobao.com"),
    ("京东", "https://www.jd.com"),
    ("知乎", "https://www.zhihu.com"),
    ("豆瓣", "https://www.douban.com"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Playwright 登录初始化 —— 手动登录并持久化登录态",
    )
    parser.add_argument(
        "--profile", "-p",
        type=str,
        default="./chrome_profile",
        help="Chrome user data 目录（默认 ./chrome_profile）",
    )
    args = parser.parse_args()

    profile_path = Path(args.profile).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    print(f"🔧 用户数据目录: {profile_path}")

    print("=" * 60)
    print("🚀 正在启动浏览器...")
    print("📌 已为您打开以下网站，请在各个网站上完成登录：")
    for name, url in LOGIN_SITES:
        print(f"   • {name}: {url}")
    print("📌 登录完成后，关闭浏览器窗口/标签页，或按 Ctrl+C 退出。")
    print("📌 所有登录状态（cookies/localStorage）将自动保存。")
    print("=" * 60)

    try:
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

            # 在每个新标签页中打开目标网站
            for name, url in LOGIN_SITES:
                page = ctx.new_page()
                try:
                    page.goto(url, timeout=15000)
                    print(f"🌐 已打开 {name}: {url}")
                except Exception:
                    print(f"⚠️  {name} 打开超时，请手动刷新: {url}")

            print("\n⏳ 等待用户操作...（请在各网站完成登录，然后关闭浏览器）")

            # 等待所有页面关闭（用户手动关闭浏览器）
            while ctx.pages:
                try:
                    for p in ctx.pages:
                        if p.is_closed():
                            continue
                        p.wait_for_close(timeout=30000)
                except Exception:
                    pass

            print("✅ 浏览器已关闭，登录态已保存。")
    except KeyboardInterrupt:
        print("\n✅ 用户中断，登录态已保存。")
    except Exception as e:
        print(f"\n❌ 异常: {e}")
        sys.exit(1)

    print(f"💾 用户数据目录: {profile_path}")
    print("🎉 完成！运行 Agent 时将自动使用此登录态。")


if __name__ == "__main__":
    main()
