# ClassicWebAgent

由自然语言指令驱动的网页多模态 Agent 系统，采用 **LLM + VLM 双层架构**——LLM（大语言模型）负责任务分解与报告生成，VLM（视觉语言模型）作为自治子代理操控浏览器。

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
- `pyyaml` — 提示词模板加载

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
LLM_MODEL_NAME = "deepseek-v4-flash"

VLM_API_KEY = "your_api_key_here"
VLM_BASE_URL = "your_openai_compatible_api_base_url_here"
VLM_MODEL_NAME = "mimo-v2.5"
```

- **LLM**：用于高层规划、任务分解、报告生成（文本模型）
- **VLM**：用于视觉感知、页面理解、动作规划（视觉语言模型）
- `*_BASE_URL` 支持任何 OpenAI 兼容 API（如 OpenAI、Azure、本地 vLLM 等）

### 3. 可选：编辑 Agent 配置

编辑 [`config/config.json`](config/config.json) 调整运行参数：

```json
{
  "log_trace": true,
  "log_level": "INFO",
  "headless": false,
  "agent": {
    "model": "deepseek-v4-flash",
    "temperature": 0.1
  },
  "subagent": {
    "model": "mimo-v2.5",
    "temperature": 0.1,
    "confidence_threshold": 0.9
  }
}
```

| 配置项 | 说明 |
|--------|------|
| `log_trace` | 是否保存每次观察的截图和 DOM 树到 `trace/` |
| `log_level` | 日志级别（DEBUG / INFO / WARNING / ERROR） |
| `headless` | 浏览器是否无头模式 |
| `agent.*` | LLM 模型参数 |
| `subagent.*` | VLM 模型参数 |
| `subagent.confidence_threshold` | VLM 动作置信度阈值（低于此值重试） |

**配置优先级**：`config.json` 中的值会覆盖代码默认值，环境变量（`LLM_*` / `VLM_*`）会覆盖 `config.json`。

---

## 运行

### 方式 1：python -m（推荐）

```bash
python -m classic_web_agent --task "帮我调研AI领域热门研究方向"
```

### 方式 2：poetry run

```bash
poetry run classic-web-agent --task "收集广州未来15天天气预报"
```

### 方式 3：辅助脚本

```bash
python scripts/run.py -t "搜索网络新闻，为我详细梳理一下世界杯小组赛挪威对阵塞内加尔的赛况，并给出赛后分析"
```

### 运行产出

每次运行会在 `log/` 下创建独立目录：

```
log/
└── 2026-06-23-0001/
    ├── run.log         # 完整运行日志
    ├── report.md       # 最终报告（LLM 生成的总结）
    └── trace/          # 轨迹记录（当 log_trace=true）
        ├── 0001_1_HHMMSSfff.png   # 每次观察的截图
        └── 0001_1_HHMMSSfff.txt   # 同时间戳的 DOM 树
```

---

## 项目结构

```
ClassicWebAgent/
├── src/classic_web_agent/
│   ├── agent/                     # LLM 主代理
│   │   ├── core.py                # Agent 主循环（Director + SubAgent 编排）
│   │   ├── director.py            # Director：plan/review/report 三阶段
│   │   └── prompts/
│   │       ├── director.yaml       # LLM 任务分解提示词
│   │       └── reporter.yaml       # LLM 报告生成提示词
│   ├── subagent/                  # VLM 子代理
│   │   ├── core.py                # SubAgent 自治执行循环
│   │   ├── planner.py             # VLM 动作规划（看图+DOM→动作序列）
│   │   ├── executor.py            # 21 个动作 → Playwright 操作
│   │   ├── perception.py          # CDP 页面感知 + 增强 DOM 树
│   │   ├── verifier.py            # 动作效果验证（stub）
│   │   └── prompts/
│   │       └── planner.yaml        # VLM 动作规划提示词
│   ├── common/                    # 共享模块
│   │   ├── types.py               # 所有数据模型
│   │   ├── memory.py              # 三层记忆管理器
│   │   └── action.py              # ActionType 枚举 + ActionSpace
│   ├── browser.py                 # Playwright 浏览器驱动
│   ├── llm.py                     # LLM/VLM API 客户端
│   ├── logger.py                  # 日志 + 报告 + 轨迹保存
│   ├── config.py                  # 配置加载（.env + config.json）
│   └── main.py                    # CLI 入口 + 运行目录管理
├── config/
│   └── config.json                # 运行时配置
├── scripts/
│   └── run.py                     # 开发辅助脚本
├── tests/                         # 测试
├── docs/                          # 设计文档
├── log/                           # 运行产出
├── pyproject.toml
└── README.md
```

---

## 架构概览

```
用户任务（一句话）
  │
  ▼
Agent.run(task)                     ← agent/core.py
  │
  ├── Director.plan(task)           ← LLM 调用1: 基于世界知识生成任务计划书
  │     → task_plan + todo_list + first_sub_task
  │
  ├── for each sub_task:
  │     ├── SubAgent.run(sub_task)  ← VLM 自治执行
  │     │     ├── Perception.observe()
  │     │     ├── Planner.plan()
  │     │     └── Executor.execute()
  │     │     → observations
  │     │
  │     └── Director.review(obs)    ← LLM 调用2..N: 审查进展
  │           → 更新 todo_list + next_sub_task
  │
  └── Director.report()             ← LLM 调用N+1: 对照计划书生成报告
        → TaskResult(summary=报告)
```

---

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python ≥ 3.11 |
| 浏览器驱动 | Playwright (Chromium) |
| 模型接口 | OpenAI 兼容 API（LLM + VLM 双模型） |
| 页面感知 | CDP (Chrome DevTools Protocol) 三流采集 |
| 构建系统 | Poetry |

---

## 开发阶段

| 阶段 | 状态 | 内容 |
|------|------|------|
| **阶段一** | ✅ | Infrastructure：Browser、LLMClient、Perception、Executor、Memory、ActionSpace |
| **阶段二** | ✅ | VLM SubAgent：Planner（planner.yaml 提示词 + confidence 机制） |
| **阶段三** | ✅ | LLM Director：任务分解 + 子任务调度 + 报告生成（director.yaml + reporter.yaml） |
| **阶段四** | 🏗️ 进行中 | 完整双层架构：运行目录系统、配置管理、trace 记录 |
| **阶段五** | ⏳ 远期 | 多 VLM 并行、Skill 库、自愈机制 |

---

## 文档

| 文档 | 说明 |
|------|------|
| [设计方案](docs/design.md) | 项目主设计文档（数据流、模块依赖、配置说明） |
| [架构概览](docs/architecture.md) | 用户向快速入门 |
| [模型调度方案](docs/model-routing.md) | LLM/VLM 双层协作细节 |
| [感知模块设计](docs/perception-design.md) | CDP 增强 DOM + 元素定位 |
| [动作空间设计](docs/action-space.md) | 21 动作类型定义 |
