"""结构化日志与轨迹记录 —— 运行目录管理 + 截图 + 交互元素树保存。

设计详见 docs/design.md §5：
- 控制台输出关键步骤信息
- 运行目录 log/YYYY-MM-DD-NNNN/run.log
- 报告保存为 report.md
- 截图 + DOM 树保存到 trace/ 子目录（同名不同后缀）
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from classic_web_agent.common.types import TaskResult


class Logger:
    """日志与轨迹记录器。"""

    def __init__(self, run_dir: Path | None = None) -> None:
        """初始化 Logger。

        Args:
            run_dir: 当前运行目录（log/YYYY-MM-DD-NNNN/），
                     为 None 时仅控制台输出。
        """
        self.run_dir: Path | None = run_dir
        self._trace_dir: Path | None = None

        if run_dir:
            self._trace_dir = run_dir / "trace"
            self._trace_dir.mkdir(parents=True, exist_ok=True)

    def start_task(self, task: str) -> None:
        """记录任务开始。"""
        print(f"[Agent] 任务开始: {task}")

    def end_task(self, result: TaskResult) -> None:
        """记录任务结束。"""
        status = "完成" if result.success else "失败"
        print(f"[Agent] 任务{status}: {result.summary} (共 {result.total_steps} 步)")

    def save_report(self, report: str, task: str, report_format: str = "md") -> Path | None:
        """将最终报告保存为文件。

        Args:
            report: 报告文本。
            task: 原始任务描述。
            report_format: 报告格式（"md" 或 "html"）。

        Returns:
            报告文件路径，无 run_dir 时返回 None。
        """
        if not self.run_dir:
            return None

        if report_format == "html":
            # HTML 格式：直接写 LLM 输出的完整 HTML 文档
            # 安全网：剥离可能出现的 ```html / ``` 包裹
            content = report.strip()
            if content.startswith("```html"):
                content = content[len("```html"):].strip()
            elif content.startswith("```"):
                first_nl = content.find("\n")
                if first_nl != -1:
                    content = content[first_nl:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()
            ext = "html"
        else:
            # MD 格式：包装标题头
            content = (
                f"# Agent 运行报告\n\n"
                f"- **任务**: {task}\n"
                f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"- **状态**: {'✅ 成功' if report.strip() else '❌ 失败'}\n\n"
                f"---\n\n"
                f"{report}"
            )
            ext = "md"

        report_path = self.run_dir / f"report.{ext}"
        report_path.write_text(content, encoding="utf-8")
        print(f"[Logger] 报告已保存: {report_path}")
        return report_path

    def save_trace(self, data_uri: str, tree_text: str, task_id: str = "") -> tuple[Path | None, Path | None]:
        """保存一次 Perception 的完整轨迹到 trace/ 目录。

        截图和 DOM 树使用同一个时间戳命名，确保文件配对。
        文件命名：{task_id}_{timestamp}.png / .txt

        Args:
            data_uri: base64 data URI 格式的截图。
            tree_text: 可交互元素树文本（PageState.tree_text）。
            task_id: 任务标识（用于文件名，如 "0001_3"）。

        Returns:
            (png_path, txt_path) 元组，失败项为 None。
        """
        png_path: Path | None = None
        txt_path: Path | None = None

        if not self._trace_dir:
            return (None, None)

        # 统一时间戳
        timestamp = datetime.now().strftime("%H%M%S%f")[:-3]
        stem = f"{task_id}_{timestamp}" if task_id else timestamp

        # 保存截图
        if data_uri and "," in data_uri:
            try:
                import base64
                _, encoded = data_uri.split(",", 1)
                decoded = base64.b64decode(encoded)
                png_path = self._trace_dir / f"{stem}.png"
                png_path.write_bytes(decoded)
            except Exception as e:
                print(f"[Logger] 截图保存失败: {e}")

        # 保存 DOM 树
        if tree_text:
            try:
                txt_path = self._trace_dir / f"{stem}.txt"
                txt_path.write_text(tree_text, encoding="utf-8")
            except Exception as e:
                print(f"[Logger] DOM 树保存失败: {e}")

        return (png_path, txt_path)


def fmt_action(action: Any) -> str:
    """将 Action 对象格式化为紧凑字符串，用于日志输出。

    格式示例：
        GOTO(url=https://example.com)
        CLICK(5)
        TYPE(text="搜索词")
        WAIT(networkidle)
        DONE
        SCROLL(direction=down)
    """
    # 兼容没有 action_type 的边界情况
    atype = action.action_type.upper() if getattr(action, "action_type", None) else "?"

    if atype == "GOTO" and action.extra:
        url = action.extra.get("url", "")
        return f"GOTO({url})"
    if atype == "TYPE":
        t = (action.text or "")[:20]
        return f'TYPE(text="{t}")'
    if atype == "CLICK" and action.element_id is not None:
        return f"CLICK({action.element_id})"
    if atype == "WAIT" and action.extra:
        cond = action.extra.get("condition", "load")
        return f"WAIT({cond})"
    if atype == "PRESS" and action.extra:
        key = action.extra.get("key", "")
        return f"PRESS({key})"
    if atype == "SCROLL" and action.extra:
        d = action.extra.get("direction", "")
        return f"SCROLL(direction={d})"
    if atype == "SWITCH_TAB" and action.extra:
        idx = action.extra.get("tab_index", "")
        return f"SWITCH_TAB({idx})"
    if atype == "NEW_TAB":
        url = ""
        if action.extra:
            url = action.extra.get("url", "")
        return f"NEW_TAB({url})" if url else "NEW_TAB()"
    if atype == "MOUSE_CLICK" and action.extra:
        x = action.extra.get("x", "?")
        y = action.extra.get("y", "?")
        return f"MOUSE_CLICK({x},{y})"
    if atype == "EXTRACT" and action.extra:
        eid = action.extra.get("element_id", "")
        return f"EXTRACT(element={eid})" if eid else "EXTRACT()"
    if atype == "FIND":
        t = (action.text or "")[:20]
        return f'FIND(text="{t}")'
    if atype in ("DONE", "FAIL", "THINK", "SCREENSHOT", "GO_BACK", "GO_FORWARD",
                  "HOVER", "CLOSE_TAB", "RECALL", "REMEMBER"):
        return atype
    # fallback：拼接 extra 中非空字段
    parts = []
    if action.element_id is not None:
        parts.append(str(action.element_id))
    if action.text:
        parts.append(f'"{action.text[:15]}"')
    if action.extra:
        for k, v in action.extra.items():
            if v:
                parts.append(f"{k}={v}")
    suffix = f"({', '.join(parts)})" if parts else ""
    return f"{atype}{suffix}"
