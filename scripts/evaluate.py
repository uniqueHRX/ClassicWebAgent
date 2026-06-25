"""测试评估与评分脚本。

评估两个独立维度：
1. 任务完成度 — LLM 按 eval_criteria 评报告覆盖了多少用户要求
2. 信息质量 — 报告中的数据准确性、信息具体性、来源可信度

总分 = 完成(0/1) × (任务完成度×0.6 + 信息质量×0.4)

用法：
    python scripts/evaluate.py --range 18-27
    python scripts/evaluate.py --id 0020
    python scripts/evaluate.py --range 18-27 --no-llm
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from classic_web_agent.llm import LLMClient

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("evaluate")

LOG_BASE = Path("log")
CASES_FILE = Path("scripts/test-cases.yaml")

W_TASK = 0.5   # 任务完成度权重
W_INFO = 0.3   # 信息质量权重
W_SUB = 0.2    # 子任务完成率权重

# 信息质量子维度权重
W_ACCURACY = 0.4
W_SPECIFICITY = 0.3
W_SOURCE = 0.3

# ── 加载测例 ────────────────────────────────────────────────────────────


def load_cases() -> list[dict]:
    if not CASES_FILE.exists():
        logger.warning(f"未找到: {CASES_FILE}")
        return []
    with open(CASES_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_CASES: list[dict] | None = None


def get_cases() -> list[dict]:
    global _CASES
    if _CASES is None:
        _CASES = load_cases()
    return _CASES


def get_eval_criteria(task_prefix: str) -> str:
    for c in get_cases():
        t = c.get("task", "").strip()[:40]
        if t in task_prefix or task_prefix in t:
            return c.get("eval_criteria", "")
    return ""


# ── 日志解析 ────────────────────────────────────────────────────────────


def parse_run_log(run_dir: Path) -> dict[str, Any]:
    log_path = run_dir / "run.log"
    report_path = run_dir / "report.md"
    if not log_path.exists():
        raise FileNotFoundError(f"日志不存在: {log_path}")

    text = log_path.read_text(encoding="utf-8")

    task_m = re.search(r"用户任务:\s*(.+)", text)
    task = task_m.group(1).strip() if task_m else ""

    plan_m = re.search(
        r"task_plan[^)]*\):\s*\n(.*?)(?=\n\d{4}-\d{2}-\d{2} |\Z)",
        text, re.DOTALL,
    )
    task_plan = plan_m.group(1).strip() if plan_m else ""

    status_m = re.search(r"任务状态:\s*(成功|失败)", text)
    main_success = status_m is not None and status_m.group(1) == "成功"

    report = ""
    if report_path.exists():
        report = report_path.read_text(encoding="utf-8").strip()

    sub_tasks = _parse_sub_tasks(run_dir)
    return {"task": task, "task_plan": task_plan, "main_success": main_success,
            "report": report, "sub_tasks": sub_tasks}


def _parse_sub_tasks(run_dir: Path) -> list[dict]:
    """从 sub_tasks.json 读取子任务完成状态（运行时结构化输出）。"""
    p = run_dir / "sub_tasks.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取 sub_tasks.json 失败: %s", e)
        return []


# ── LLM 评分 ────────────────────────────────────────────────────────────


_SCORE_PROMPT = """你是一个任务完成质量评估专家。请根据以下信息对报告进行评分。

## 用户原始指令
{task}

## 任务计划书
{task_plan}

## 最终报告
{report}

## 评分标准
{eval_criteria}

请从两个独立维度评分，每个 0-100：

1. 任务完成度：按评分标准逐项打分，报告覆盖了多少用户要求的内容
2. 信息质量（与任务无关的通用质量）：
   - 数据准确性（权重40%）：报告中的数字、事实是否准确
   - 信息具体性（权重30%）：是否给出具体数值而非笼统描述
   - 来源可信度（权重30%）：是否标注了信息来源

输出 JSON：
{{"task_fulfillment": 85, "info_accuracy": 80, "info_specificity": 70, "info_source": 60, "reason": "扣分说明"}}"""


def score_report(task: str, task_plan: str, report: str,
                 eval_criteria: str, llm: LLMClient) -> dict:
    prompt = _SCORE_PROMPT.format(
        task=task, task_plan=task_plan, report=report,
        eval_criteria=eval_criteria or "无具体标准，请自行判断完成度",
    )
    try:
        resp = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.content)
    except Exception as e:
        logger.warning(f"LLM 评分失败: {e}")
        return {"task_fulfillment": 0, "info_accuracy": 0,
                "info_specificity": 0, "info_source": 0, "reason": f"异常: {e}"}

    return {
        "task_fulfillment": max(0, min(100, int(data.get("task_fulfillment", 0)))),
        "info_accuracy": max(0, min(100, int(data.get("info_accuracy", 0)))),
        "info_specificity": max(0, min(100, int(data.get("info_specificity", 0)))),
        "info_source": max(0, min(100, int(data.get("info_source", 0)))),
        "reason": data.get("reason", ""),
    }


def calc_info_quality(d: dict) -> float:
    return d["info_accuracy"] * W_ACCURACY + d["info_specificity"] * W_SPECIFICITY + d["info_source"] * W_SOURCE


def calc_overall(main_ok: bool, task_f: float, info_q: float, sub_rate: float) -> float:
    """总分 = 完成(0/1) × (任务完成度×0.5 + 信息质量×0.3 + 子任务完成率×0.2)"""
    if not main_ok:
        return 0.0
    return task_f * W_TASK + info_q * W_INFO + sub_rate * W_SUB


# ── 评估入口 ────────────────────────────────────────────────────────────


def evaluate_run(run_dir: Path, llm: LLMClient | None, idx: int) -> dict[str, Any]:
    data = parse_run_log(run_dir)
    sub_tasks = data["sub_tasks"]
    main_ok = data["main_success"]

    ec = get_eval_criteria(data["task"][:40])

    detail = {"task_fulfillment": 0, "info_accuracy": 0,
              "info_specificity": 0, "info_source": 0, "reason": ""}
    if main_ok and llm and data["report"]:
        detail = score_report(data["task"], data["task_plan"], data["report"], ec, llm)

    task_f = float(detail["task_fulfillment"])
    info_q = calc_info_quality(detail)

    sub_done = sum(1 for s in sub_tasks if s["status"] == "completed")
    sub_fail = sum(1 for s in sub_tasks if s["status"] == "failed")
    sub_total = len(sub_tasks)
    sub_rate = (sub_done / sub_total * 100) if sub_total > 0 else 0.0

    overall = calc_overall(main_ok, task_f, info_q, sub_rate)

    return {
        "id": idx,
        "task": data["task"][:80],
        "run_dir": str(run_dir.name),
        "score": round(overall, 1),
        "task_fulfillment": round(task_f, 1),
        "info_quality": round(info_q, 1),
        "detail": detail,
        "sub_tasks": {
            "total": len(sub_tasks),
            "completed": sub_done,
            "failed": sub_fail,
            "details": sub_tasks,
        },
    }


# ── CLI ─────────────────────────────────────────────────────────────────


def resolve_dirs(range_str: str | None, single_id: str | None,
                 date_str: str | None) -> list[Path]:
    """解析运行目录列表。

    Args:
        range_str: 序号范围，如 "18-27"。
        single_id: 单个序号，如 "0020"。
        date_str: 日期前缀，如 "2026-06-25"；None 时扫描 log/ 下全部目录。

    Returns:
        匹配的运行目录列表（按名称排序）。
    """
    dirs: list[Path] = []

    if single_id and date_str:
        d = LOG_BASE / f"{date_str}-{single_id}"
        if d.exists():
            dirs.append(d)
        return dirs
    if single_id:
        # 无日期时扫描所有日期中的匹配序号
        for d in sorted(LOG_BASE.iterdir()):
            if d.is_dir() and d.name.endswith(f"-{single_id}") and (d / "run.log").exists():
                dirs.append(d)
        return dirs

    if range_str:
        a, b = range_str.split("-")
        if date_str:
            for i in range(int(a), int(b) + 1):
                d = LOG_BASE / f"{date_str}-{i:04d}"
                if d.exists() and (d / "run.log").exists():
                    dirs.append(d)
        else:
            # 无日期时扫描所有日期
            for d in sorted(LOG_BASE.iterdir()):
                if not d.is_dir():
                    continue
                parts = d.name.rsplit("-", 1)
                if len(parts) != 2:
                    continue
                try:
                    seq = int(parts[1])
                    if a <= seq <= b and (d / "run.log").exists():
                        dirs.append(d)
                except ValueError:
                    continue
        return dirs

    # 无参数 → 全量扫描
    for d in sorted(LOG_BASE.iterdir()):
        if d.is_dir() and (d / "run.log").exists():
            dirs.append(d)
    return dirs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--range", help="序号范围，如 18-27")
    parser.add_argument("--id", help="序号，如 0020")
    parser.add_argument("--date", help="日期前缀，如 2026-06-25（默认全量扫描）")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--output", default="log/results.json")
    args = parser.parse_args()

    llm = None
    if not args.no_llm:
        try:
            llm = LLMClient(mode="llm")
        except Exception as e:
            logger.warning(f"LLM 初始化失败: {e}")

    dirs = resolve_dirs(args.range, args.id, args.date)
    if not dirs:
        logger.error("未找到运行日志"); sys.exit(1)

    logger.info(f"找到 {len(dirs)} 个运行日志")
    results = []
    for i, d in enumerate(dirs, 1):
        logger.info(f"[{i}/{len(dirs)}] {d.name}")
        try:
            results.append(evaluate_run(d, llm, i))
        except Exception as e:
            logger.warning(f"{d.name} 失败: {e}")

    n = len(results)
    avg_task = sum(r["task_fulfillment"] for r in results) / n if n else 0
    avg_info = sum(r["info_quality"] for r in results) / n if n else 0
    avg_score = sum(r["score"] for r in results) / n if n else 0
    main_ok = sum(1 for r in results if r["detail"]["task_fulfillment"] > 0 or True)

    summary = {
        "total": n,
        "avg_task_fulfillment": round(avg_task, 1),
        "avg_info_quality": round(avg_info, 1),
        "avg_score": round(avg_score, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    output = {"test_cases": results, "summary": summary}

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"\n结果: {out}")
    logger.info(f"\n汇总 ({n} 个):")
    logger.info(f"  平均任务完成度: {avg_task:.1f}")
    logger.info(f"  平均信息质量:   {avg_info:.1f}")
    logger.info(f"  平均总分:       {avg_score:.1f}")
    logger.info(f"\n各测例:")
    for r in results:
        sub = r["sub_tasks"]
        logger.info(
            f"  #{r['id']}: {r['score']:5.1f}  "
            f"完成={r['task_fulfillment']:.0f}  "
            f"质量={r['info_quality']:.0f}  "
            f"子任务={sub['completed']}/{sub['total']}  "
            f"{r['task'][:35]}"
        )


if __name__ == "__main__":
    main()
