"""
Perception 模块百度首页诊断脚本。
直接运行即可看到 tree_text 输出。

用法：
    python scripts/test_perception_baidu.py
"""

from classic_web_agent.browser import Browser
from classic_web_agent.agent.perception import Perception


def main():
    print("正在启动浏览器并打开百度首页...")
    with Browser(headless=True) as browser:
        browser.goto("https://www.baidu.com")
        print(f"页面标题: {browser.current_page.title()}")
        print(f"页面 URL: {browser.current_page.url}")

        perception = Perception(vlm=None, browser=browser)
        state = perception.observe()

        print(f"\n=== PageState ===")
        print(f"截图 data URI 长度: {len(state.screenshot)} 字符")
        print(f"URL: {state.url}")
        print(f"Title: {state.title}")
        print(f"tree_text 行数: {len(state.tree_text.split(chr(10)))}")
        print(f"tree_text 字符数: {len(state.tree_text)}")

        # 写入文件避免终端编码问题
        output_path = "log/baidu_tree_text.txt"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(state.tree_text)
        print(f"\n已将 tree_text 写入 {output_path} ({len(state.tree_text)} 字符)")


if __name__ == "__main__":
    main()
