"""快速启动脚本 —— 自动加载 .env 并启动 Agent。

用法：
    python scripts/run.py -t "帮我调研AI领域最新研究方向"

等价于：
    python -m classic_web_agent --task "帮我调研AI领域最新研究方向"
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# 从主模块启动
if __name__ == "__main__":
    from classic_web_agent.main import main
    main()
