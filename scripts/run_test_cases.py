"""批量运行测试用例。

用法：
    python scripts/run_test_cases.py                # 运行所有用例
    python scripts/run_test_cases.py --id 1 3 5     # 只运行指定编号
    python scripts/run_test_cases.py --id 1-5       # 运行范围
"""

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

CASES_FILE = Path(__file__).parent / "test-cases.yaml"


def load_cases() -> list[dict]:
    if not CASES_FILE.exists():
        print(f"[Error] 未找到用例文件: {CASES_FILE}")
        sys.exit(1)
    with open(CASES_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_ids(raw: list[str], total: int) -> list[int]:
    ids: list[int] = []
    for arg in raw:
        if "-" in arg:
            parts = arg.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                ids.extend(range(int(parts[0]), int(parts[1]) + 1))
        elif arg.isdigit():
            ids.append(int(arg))
    return sorted(set(ids))


def main() -> None:
    parser = argparse.ArgumentParser(description="批量运行测试用例")
    parser.add_argument("--id", nargs="+", help="用例编号（如 1 3 5 或 1-5）")
    args = parser.parse_args()

    cases = load_cases()
    total = len(cases)
    print(f"[TestRunner] 共加载 {total} 个用例")

    if args.id:
        ids = parse_ids(args.id, total)
        cases = [cases[i - 1] for i in ids if 1 <= i <= total]
    else:
        ids = list(range(1, total + 1))

    print(f"[TestRunner] 本次运行 {len(cases)} 个用例: {ids}")
    print("=" * 60)

    results: list[dict] = []
    for idx, case in enumerate(cases):
        cid = ids[idx]
        task = case["task"].strip()
        preview = task[:60].replace("\n", " ")

        print(f"\n{'=' * 60}")
        print(f"[TestRunner] #{cid}: {preview}...")
        print(f"{'=' * 60}")

        result = subprocess.run(
            [sys.executable, "-m", "classic_web_agent", "--task", task],
            capture_output=False,
        )
        success = result.returncode == 0
        results.append({"id": cid, "success": success})
        print(f"\n[TestRunner] #{cid}: {'✅' if success else '❌'}")

    passed = sum(1 for r in results if r["success"])
    print(f"\n\n{'=' * 60}")
    print(f"[TestRunner] 汇总: {passed}/{len(results)} 通过")
    for r in results:
        print(f"  #{r['id']}: {'✅' if r['success'] else '❌'}")


if __name__ == "__main__":
    main()
