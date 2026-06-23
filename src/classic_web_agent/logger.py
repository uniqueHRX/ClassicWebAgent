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

from classic_web_agent.common.types import AgentStep, TaskResult


class Logger:
    """日志与轨迹记录器。"""

    def __init__(self, run_dir: Path | None = None) -> None:
        """初始化 Logger。

        Args:
            run_dir: 当前运行目录（log/YYYY-MM-DD-NNNN/），
                     为 None 时仅控制台输出。
        """
        self.steps: list[AgentStep] = []
        self.run_dir: Path | None = run_dir
        self._trace_dir: Path | None = None

        if run_dir:
            self._trace_dir = run_dir / "trace"
            self._trace_dir.mkdir(parents=True, exist_ok=True)

    def start_task(self, task: str) -> None:
        """记录任务开始。"""
        print(f"[Agent] 任务开始: {task}")

    def log_step(self, step: AgentStep) -> None:
        """记录单步轨迹。"""
        self.steps.append(step)
        action_name = step.action.action_type if step.action else "NONE"
        result_msg = step.result.message if step.result else ""
        print(f"[Agent]  步骤 {step.step_index}: {action_name} → {result_msg}")

    def end_task(self, result: TaskResult) -> None:
        """记录任务结束。"""
        status = "完成" if result.success else "失败"
        print(f"[Agent] 任务{status}: {result.summary} (共 {result.total_steps} 步)")

    def save_report(self, report: str, task: str) -> Path | None:
        """将最终报告保存为 report.md。

        Args:
            report: 报告文本。
            task: 原始任务描述。

        Returns:
            report.md 的路径，无 run_dir 时返回 None。
        """
        if not self.run_dir:
            return None

        content = (
            f"# Agent 运行报告\n\n"
            f"- **任务**: {task}\n"
            f"- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"- **状态**: {'✅ 成功' if report.strip() else '❌ 失败'}\n"
            f"- **步骤数**: {len(self.steps)}\n\n"
            f"---\n\n"
            f"{report}"
        )
        report_path = self.run_dir / "report.md"
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
