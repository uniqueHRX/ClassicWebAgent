"""快速启动脚本 —— 自动加载 .env 并启动 Agent。

用法：
    python scripts/run.py "在百度搜索天气"
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
