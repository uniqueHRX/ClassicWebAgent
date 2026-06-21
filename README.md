# ClassicWebAgent

由自然语言指令驱动的网页多模态 Agent 系统，基于 **CoALA 认知架构**与 **ReAct 闭环决策**范式。接收用户的自然语言任务描述，自主操控浏览器完成网页操作。

---

## 前置要求

| 依赖 | 版本要求 |
|------|---------|
| Python | ≥ 3.11 |
| Poetry | ≥ 2.0 |
| Playwright 浏览器 | Chromium |

---

## 安装

### 1. 克隆项目

```bash
git clone <repository-url>
cd ClassicWebAgent
```

### 2. 安装 Python 依赖

```bash
poetry install
```

此命令会安装 [`pyproject.toml`](pyproject.toml) 中声明的所有依赖：

- `openai` — OpenAI 兼容 API 客户端（LLM/VLM 调用）
- `playwright` — 浏览器自动化驱动
- `pillow` — 截图编码（PNG optimize）
- `python-dotenv` — 环境变量加载
- `requests` — HTTP 请求

### 3. 安装 Playwright 浏览器

```bash
poetry run playwright install chromium
```


---

## 配置

### 1. 创建环境变量文件

```bash
cp .env.example .env
```

### 2. 编辑 `.env` 填入 API 密钥

```env
LLM_API_KEY = "your_api_key_here"
LLM_BASE_URL = "your_openai_compatible_api_base_url_here"
LLM_MODEL_NAME = "your_model_name_here"

VLM_API_KEY = "your_api_key_here"
VLM_BASE_URL = "your_openai_compatible_api_base_url_here"
VLM_MODEL_NAME = "your_vision_model_name_here"
```

- **LLM**：用于高层规划、任务分解、异常恢复（文本模型）
- **VLM**：用于视觉感知、页面理解、元素定位（视觉语言模型）
- `*_BASE_URL` 支持任何 OpenAI 兼容 API（如 OpenAI、Azure、本地 vLLM 等）

### 3. 可选：编辑 Agent 配置

编辑 [`config/config.json`](config/config.json) 调整运行参数：

```json
{
  "agent": {
    "mode": "auto",
    "confidence_threshold": 0.9,
    "max_retry_per_step": 2,
    "planning": {
      "review_after_each_step": true
    }
  }
}
```

| 配置项 | 说明 |
|--------|------|
| `agent.mode` | 运行模式：`auto`（推荐）/ `vlm_only` / `dual_model` |
| `agent.confidence_threshold` | VLM 动作自明阈值（0.0~1.0） |
| `agent.max_retry_per_step` | 单步最大重试次数 |
| `agent.planning.review_after_each_step` | 每步完成后是否调用 LLM 审查 |

---


## 项目结构

```
ClassicWebAgent/
├── src/classic_web_agent/   # 主包
│   ├── agent/               # Agent 核心
│   │   ├── core.py          # ReAct 主循环
│   │   ├── perception.py    # VLM 感知 + DOM 解析
│   │   ├── planner.py       # LLM 规划器
│   │   ├── executor.py      # 动作执行器
│   │   ├── verifier.py      # 验证与自愈
│   │   ├── memory.py        # 工作记忆 + 会话记忆
│   │   ├── action.py        # 动作空间定义
│   │   └── types.py         # 数据模型
│   ├── browser.py           # Playwright 浏览器驱动
│   ├── llm.py               # LLM/VLM API 客户端
│   ├── logger.py            # 结构化日志
│   ├── config.py            # 配置管理
│   └── main.py              # CLI 入口
├── config/                  # 配置文件与提示词模板
│   ├── config.json
│   └── prompts/
├── scripts/                 # 辅助脚本
├── docs/                    # 设计文档
├── tests/                   # 测试
├── pyproject.toml
└── README.md
```

---

## 运行模式

| 模式 | 说明 | LLM 调用 |
|------|------|---------|
| `auto` | 完整的层级规划（推荐） | 低频（规划/求救/审查时） |
| `vlm_only` | 纯 VLM 驱动，零 LLM 调用 | 无 |
| `dual_model` | 每步 VLM 感知 + LLM 规划（对照基线） | 每步 1 次 |

详见 [模型调度方案](docs/model-routing.md)。

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python ≥ 3.11 |
| 浏览器驱动 | Playwright (Chromium) |
| 模型接口 | OpenAI 兼容 API |
| 构建系统 | Poetry |
| 架构范式 | CoALA + ReAct |

---

## 文档

| 文档 | 说明 |
|------|------|
| [设计方案](docs/design.md) | 项目主设计文档 |
| [架构概览](docs/architecture.md) | 用户向快速入门 |
| [模型调度方案](docs/model-routing.md) | LLM/VLM 协作细节 |
| [感知模块设计](docs/perception-design.md) | CDP 增强 DOM + 元素定位 |
| [动作空间设计](docs/action-space.md) | 21 动作类型定义 |

---

## 日志

运行日志输出到 `log/` 目录：

```
log/
├── trajectories/       # JSONL 轨迹记录
└── screenshots/        # 分步截图序列
```

---

## 开发阶段

| 阶段 | 目标 |
|------|------|
| **阶段一** | 最小可行系统：`vlm_only` 端到端闭环 |
| **阶段二** | 功能完善：`auto` 模式、自愈机制、Skill 库 |
| **阶段三** | 实验评测：批量基准测试 |
