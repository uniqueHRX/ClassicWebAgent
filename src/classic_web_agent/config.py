"""配置管理：加载 .env 环境变量与 config/config.json。"""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def load_config() -> dict[str, Any]:
    """加载全局配置，config.json 为空时使用默认值。"""
    config_path = PROJECT_ROOT / "config" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
