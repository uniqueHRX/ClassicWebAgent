"""配置管理：合并 .env 环境变量与 config/config.json。

优先级：环境变量 > config.json > 默认值。

环境变量前缀：
  LLM_ / VLM_ 系列为传统 API 配置（兼容旧代码）
  AGENT_* / SUBAGENT_* 可用于覆盖子字段
"""

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# 加载 .env
load_dotenv()

# 项目根目录（src/classic_web_agent/config.py → ../../.. → 项目根）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# ── 默认配置 ────────────────────────────────────────────────────

_DEFAULT_CONFIG: dict[str, Any] = {
    "headless": False,
    "log_trace": False,
    "log_level": "INFO",
    "report_format": "md",
    "agent": {
        "model": "deepseek-v4-flash",
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "",
        "temperature": 0.1,
    },
    "subagent": {
        "model": "mimo-v2.5",
        "base_url": "https://opencode.ai/zen/go/v1",
        "api_key": "",
        "temperature": 0.1,
        "confidence_threshold": 0.9,
    },
}


def _load_json_config() -> dict[str, Any]:
    """加载 config/config.json。"""
    config_path = PROJECT_ROOT / "config" / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典，override 覆盖 base。"""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    """用环境变量覆盖配置中对应的字段。

    规则：
      - AGENT_API_KEY → config["agent"]["api_key"]
      - AGENT_BASE_URL → config["agent"]["base_url"]
      - SUBAGENT_MODEL → config["subagent"]["model"]
      - SUBAGENT_CONFIDENCE_THRESHOLD → config["subagent"]["confidence_threshold"]
      - 传统 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL_NAME → agent 字段
      - 传统 VLM_API_KEY / VLM_BASE_URL / VLM_MODEL_NAME → subagent 字段
    """
    # 字段映射: (env_var, config_path)
    mappings = [
        # Agent (LLM)
        ("LLM_API_KEY", ["agent", "api_key"]),
        ("LLM_BASE_URL", ["agent", "base_url"]),
        ("LLM_MODEL_NAME", ["agent", "model"]),
        # SubAgent (VLM)
        ("VLM_API_KEY", ["subagent", "api_key"]),
        ("VLM_BASE_URL", ["subagent", "base_url"]),
        ("VLM_MODEL_NAME", ["subagent", "model"]),
        # 通用
        ("HEADLESS", ["headless"]),
    ]

    for env_var, path_parts in mappings:
        value = os.environ.get(env_var)
        if value is not None and value.strip():
            target = config
            for part in path_parts[:-1]:
                target = target.setdefault(part, {})
            target[path_parts[-1]] = value.strip()

    return config


def load_config() -> dict[str, Any]:
    """加载完整配置。

    优先级（后覆盖前）：
      1. _DEFAULT_CONFIG
      2. config/config.json
      3. 环境变量

    Returns:
        dict: 合并后的配置字典。
    """
    json_cfg = _load_json_config()
    merged = _deep_merge(_DEFAULT_CONFIG, json_cfg)
    merged = _apply_env_overrides(merged)
    return merged
