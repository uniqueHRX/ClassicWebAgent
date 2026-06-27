# ClassicWebAgent

由自然语言指令驱动的网页多模态 Agent 系统，采用 **LLM + VLM 双层架构**——LLM（大语言模型）负责任务分解与报告生成，VLM（视觉语言模型）作为自治子代理操控浏览器。

---

[![演示视频](https://img.youtube.com/vi/7OmGcWjdJMk/maxresdefault.jpg)](https://youtu.be/7OmGcWjdJMk?si=DN94NTMmYghvoqle)

---

## 目录

- [安装部署](#安装部署)
- [配置文件](#配置文件)
- [登录浏览器](#登录浏览器持久化登录态)
- [运行任务](#运行任务)
  - [运行单个任务](#运行单个任务)
  - [运行批量测试](#运行批量测试)
  - [评测结果](#评测结果)
- [项目结构](#项目结构)
- [架构说明](#架构说明)
- [动作空间](#动作空间)
- [常见问题](#常见问题)

---

## 安装部署

### 前置要求

| 依赖 | 版本要求 |
|------|---------|
| Python | ≥ 3.11 |
| Poetry | ≥ 2.0 |
| Playwright 浏览器 | Chromium |

### 1. 克隆项目

```bash
git clone https://github.com/uniqueHRX/ClassicWebAgent.git
cd ClassicWebAgent
```

### 2. 安装 Python 依赖

```bash
poetry install
```

核心依赖包括：

| 包 | 用途 |
|-----|------|
| `openai` | OpenAI 兼容 API 客户端（LLM/VLM 调用） |
| `playwright` | 浏览器自动化驱动 |
| `pillow` | 截图编码（PNG optimize） |
| `python-dotenv` | 环境变量加载 |
| `pyyaml` | 提示词模板加载 |
| `playwright-stealth` | 反检测补丁（仅 Playwright 引擎） |

### 3. 安装 Playwright 浏览器

```bash
poetry run playwright install chromium
```

### 4. 可选：CloakBrowser 反检测浏览器（替代 Playwright）

如果目标网站有严格的反爬/反机器人检测（如 Cloudflare Turnstile、reCAPTCHA v3），提供 C++ 源码级反检测 Chromium，58 个源码补丁覆盖 WebGL/Canvas/Audio/WebRTC 等指纹：

```bash
poetry install --with cloak
```

首次运行自动下载 CloakBrowser 二进制（~200MB）。配置方式见[配置文件](#配置文件)。

### 5. 配置 API 密钥

```bash
cp .env.example .env
```

编辑 `.env`：

```env
LLM_API_KEY = "your_api_key"
LLM_BASE_URL = "your_openai_compatible_api_base_url"
LLM_MODEL_NAME = "deepseek-v4-flash"

VLM_API_KEY = "your_api_key"
VLM_BASE_URL = "your_openai_compatible_api_base_url"
VLM_MODEL_NAME = "mimo-v2.5"
```

| 变量 | 说明 |
|------|------|
| `LLM_*` | 高层规划、任务分解、报告生成（文本模型） |
| `VLM_*` | 视觉感知、页面理解、动作规划（视觉语言模型） |
| `*_BASE_URL` | 支持任何 OpenAI 兼容 API（OpenAI/Azure/本地 vLLM 等） |

---

## 配置文件

编辑 [`config/config.json`](config/config.json) 调整运行参数：

```json
{
  "agent": {
    "model": "deepseek-v4-flash",
    "temperature": 0.1,
    "timeout": 180
  },
  "subagent": {
    "model": "mimo-v2.5",
    "temperature": 0.1,
    "confidence_threshold": 0.9,
    "timeout": 60,
    "max_steps": 20,
    "max_retries": 3
  },
  "browser_engine": "playwright",
  "playwright": {
    "headless": false,
    "user_data_dir": "./chrome_profile"
  },
  "cloakbrowser": {
    "headless": false,
    "user_data_dir": "./cloak_profile",
    "humanize": false,
    "geoip": false
  },
  "log_trace": true,
  "report_format": "both"
}
```

### 配置项说明

| 配置项 | 说明 |
|--------|------|
| `agent.*` | LLM 模型参数（model / temperature / timeout） |
| `subagent.model` | VLM 模型名称 |
| `subagent.confidence_threshold` | VLM 动作置信度阈值（低于此值触发重试，默认 0.9） |
| `subagent.max_steps` | 每个子任务的最大操作步数（默认 20） |
| `subagent.max_retries` | VLM 低置信度最大重试次数（默认 3，超限自动 FAIL） |
| `subagent.timeout` | VLM API 请求超时秒数（默认 60） |
| `browser_engine` | 浏览器引擎：`"playwright"`（默认）或 `"cloakbrowser"` |
| `playwright.*` | Playwright 引擎配置（headless / user_data_dir） |
| `cloakbrowser.*` | CloakBrowser 引擎配置（headless / user_data_dir / humanize / geoip） |
| `log_trace` | 是否保存每次观察的截图和 DOM 树到 `trace/` |
| `report_format` | 报告格式：`"md"` / `"html"` / `"both"` |

**配置优先级**：代码默认值 < `config.json` < 环境变量（`LLM_*` / `VLM_*`）

---

## 登录浏览器（持久化登录态）

对于需要登录的网站（京东、知乎等），先运行登录初始化脚本。脚本会自动读取配置文件中的 `browser_engine` 和对应的 `user_data_dir`：

```bash
python scripts/init_login.py
```

脚本会打开以下网站（有头模式），在每个标签页中完成手动登录：

- 百度（https://www.baidu.com）
- 京东（https://www.jd.com）
- 知乎（https://www.zhihu.com）
- 豆瓣（https://www.douban.com）

登录完成后关闭浏览器窗口，cookies/localStorage 自动保存到配置的 `user_data_dir` 目录。此后 Agent 运行时自动复用此登录态。

也可手动指定 profile 目录：

```bash
python scripts/init_login.py --profile ./my_profile
```

---

## 运行任务

### 运行单个任务

```bash
# 方式 1：python -m（推荐）
python -m classic_web_agent --task "京东上卖得最好的机械键盘是哪款"

# 方式 2：poetry run
poetry run classic-web-agent --task "今天北京的天气怎么样"

# 方式 3：辅助脚本（自动加载 .env）
python scripts/run.py -t "帮我对比一下 iPhone 16 在京东和天猫的价格"
```

### 运行产出

每次运行在 `log/` 下创建独立目录：

```
log/
└── 2026-06-25-NNNN/
    ├── run.log              # 完整运行日志
    ├── report.md            # Markdown 格式报告
    ├── report.html          # HTML 格式报告（report_format 为 html/both 时）
    ├── sub_tasks.json       # 子任务完成状态
    └── trace/               # 轨迹记录（log_trace=true 时）
        ├── 0001_1_HHMMSSfff.png   # 每次观察的截图
        └── 0001_1_HHMMSSfff.txt   # 同时间戳的 DOM 树
```

### 运行批量测试

批量运行 [`scripts/test-cases.yaml`](scripts/test-cases.yaml) 中定义的所有测例：

```bash
# 运行全部 10 个测例
python scripts/run_test_cases.py

# 运行指定测例（按编号）
python scripts/run_test_cases.py --id 1

# 运行指定测例（按编号，支持多个）
python scripts/run_test_cases.py --id 1,3,5
```

测例覆盖天气查询、票价查询、商品比价、体育赛事调研、热搜获取、商品推荐、技术调研等场景，每个测例包含任务描述和评分标准。

---

## 评测结果

### 评分工具

对运行结果进行自动评分，基于 LLM 评估任务完成度和信息质量：

```bash
# 评估指定日期的指定序号范围
python scripts/evaluate.py --date 2026-06-25 --range 1-10

# 评估单个运行
python scripts/evaluate.py --date 2026-06-25 --id 0015

# 跨日期评估（多个日期的同序号段）
python scripts/evaluate.py --range 1-10

# 全量评估（log/ 下所有运行）
python scripts/evaluate.py

# 仅结构化分析，不调用 LLM 评分
python scripts/evaluate.py --no-llm

# 自定义输出路径
python scripts/evaluate.py --date 2026-06-25 --range 1-10 --output results/my_eval.json
```

### 评分维度

| 维度 | 权重 | 说明 |
|------|------|------|
| 任务完成度 | 50% | LLM 按 `eval_criteria` 逐项评估报告覆盖了多少用户要求 |
| 信息质量 | 30% | 数据准确性(40%) + 信息具体性(30%) + 来源可信度(30%) |
| 子任务完成率 | 20% | `sub_tasks.json` 中 `status=completed` 的比例 |

**总分公式**：`主任务成功(0/1) × (完成度×50% + 信息质量×30% + 子任务完成率×20%)`

### 评估依赖

- 需要 `.env` 中配置 **LLM** API KEY（`LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME`）
- 评估使用 LLM（文本模型），而非 VLM（视觉模型）
- `--no-llm` 模式不需要 API，但返回 0 分

### 输出格式

```json
{
  "test_cases": [
    {
      "id": 1,
      "task": "今天北京天气怎么样",
      "score": 92.8,
      "task_fulfillment": 95.0,
      "info_quality": 84.5,
      "sub_tasks": { "total": 2, "completed": 2, "failed": 0 }
    }
  ],
  "summary": {
    "total": 10,
    "avg_score": 87.7,
    "avg_task_fulfillment": 94.6,
    "avg_info_quality": 86.4
  }
}
```

---

## 项目结构

```
ClassicWebAgent/
├── src/classic_web_agent/
│   ├── __init__.py, __main__.py
│   ├── main.py                    # CLI 入口（argparse）
│   ├── config.py                  # 配置管理（.env + config.json 深度合并）
│   ├── llm.py                     # OpenAI 兼容 API 客户端（LLM/VLM 双模式）
│   ├── logger.py                  # 日志记录 + 报告/截图保存
│   ├── browser.py                 # Playwright/CloakBrowser 驱动 + 原子操作
│   ├── skills.py                  # Skill 注册（预留）
│   │
│   ├── common/
│   │   ├── types.py               # 数据模型：Action/PageState/MemoryEntry/TodoItem...
│   │   ├── memory.py              # 三层记忆管理器（observations + working + knowledge）
│   │   └── action.py              # 23 个动作类型枚举 + ActionSpace 校验
│   │
│   ├── agent/                     # LLM 主代理
│   │   ├── core.py                # Agent 主循环（plan → review → report 三阶段）
│   │   ├── director.py            # LLM 编排器：plan/review/report + prompt 渲染
│   │   └── prompts/
│   │       ├── director.yaml      # LLM 任务分解提示词
│   │       └── reporter.yaml      # LLM 报告生成提示词（支持 MD/HTML 双格式）
│   │
│   └── subagent/                  # VLM 子代理
│       ├── core.py                # SubAgent 子任务自治执行循环
│       ├── planner.py             # VLM 动作规划（看图+DOM → 动作序列）
│       ├── executor.py            # 23 个动作的执行器
│       ├── perception.py          # 页面感知（CDP 三流采集 + SoM 标注）
│       ├── som.py                 # Set-of-Mark 截图标注
│       ├── verifier.py            # 动作效果验证（stub）
│       └── prompts/
│           └── planner.yaml       # VLM 动作规划提示词
│
├── config/
│   └── config.json                # 运行配置
│
├── scripts/
│   ├── run.py                     # 便捷运行（自动加载 .env）
│   ├── run_test_cases.py          # 批量测试运行
│   ├── evaluate.py                # 评测评分工具
│   ├── init_login.py              # 浏览器登录初始化
│   └── test-cases.yaml            # 端到端测例定义
│
├── tests/                         # pytest 单元/集成测试
│   ├── conftest.py
│   ├── test_browser.py            # 浏览器集成测试
│   ├── test_executor.py           # 执行器单元/集成测试
│   ├── test_planner.py            # 规划器单元/集成测试
│   ├── test_perception.py         # 感知模块 + SoM 测试
│   ├── test_director.py           # Director 测试
│   ├── test_llm.py                # LLM 客户端测试
│   └── ...
│
├── plans/                         # 设计方案归档
├── log/                           # 运行日志（自动创建）
└── chrome_profile/                # Playwright 登录态（自动创建）
```

---

## 架构说明

### 双层 Agent 架构

```
用户任务 → LLM (Director) → 子任务清单 → VLM (SubAgent) → 浏览器操作
                            │                              │
                    逐个子任务执行 ← observations 返回参与
                                            │
                                     LLM 汇总生成报告
```

- **LLM 层**（`agent/`）：战略级决策者。将用户任务分解为子任务清单，逐项派发给 VLM，收到结果后汇总生成报告。
- **VLM 层**（`subagent/`）：战术级执行者。自治执行单个子任务（ReAct 循环：观察→规划→执行→验证），返回 observations。

### Agent 三阶段执行流程

```
阶段1: plan()
  LLM 将用户任务分解为子任务清单 + 详细任务计划书
           │
阶段2: review() 循环
  for each 子任务:
    SubAgent.run() → observations  ← VLM 自治执行（最多 max_steps 步）
    LLM 审查结果 → 更新 todo_list → 下一个子任务 / 完成
           │
阶段3: report()
  LLM 对照任务计划书和所有 observations 生成最终报告
  （支持 Markdown / HTML 双格式）
```

### VLM 单步循环（SubAgent ReAct）

```
每步循环（最多 max_steps 步）:
  1. 观察（Perception.observe()）
     ├── 截图（page.screenshot → PNG optimize）
     ├── CDP 三流采集（DOM + AX + Snapshot）
     ├── 构建增强 DOM 树
     ├── 收集 SoM 可交互元素坐标
     ├── 序列化 DOM 树
     └── SoM 标注截图（包围框 + 编号徽章）
  2. 规划（Planner.plan()）
     └── VLM 看图 + DOM 树 → 动作序列（1-4 个动作）
  3. 执行（Executor.execute()）
     └── 逐个执行动作，记录结构化 working memory
  4. 重复直到 DONE/FAIL
```

---

## 动作空间

系统定义了 23 个原子动作（18 个外部 + 5 个内部）：

| 分类 | 动作 | 参数 | 说明 |
|------|------|------|------|
| **元素交互** | `CLICK` | `element_id` | 点击 SoM 编号元素 |
| | `MOUSE_CLICK` | `x`, `y` | 坐标点击（Canvas/SoM 盲区 fallback） |
| | `TYPE` | `element_id`, `text` | 输入文本（自动清空原内容） |
| | `HOVER` | `element_id` | 悬停（展开下拉菜单） |
| **页面操作** | `SCROLL` | `direction` | 滚动（up/down） |
| | `PRESS` | `key` | 按键（Enter/Escape 等） |
| | `WAIT` | `condition` | 显式等待（load/domcontentloaded/networkidle） |
| **导航** | `GOTO` | `url` | 页面跳转 |
| | `GO_BACK` | — | 后退 |
| | `GO_FORWARD` | — | 前进 |
| | `REFRESH` | — | 刷新页面 |
| **标签页** | `NEW_TAB` | `url` | 新建标签页 |
| | `CLOSE_TAB` | — | 关闭当前标签页 |
| | `SWITCH_TAB` | `tab_index` | 切换标签页 |
| **信息获取** | `SCREENSHOT` | — | 主动截图 |
| | `EXTRACT` | `element_id` | 提取文本 |
| | `FIND` | `text` | 页内搜索并滚动定位 |
| | `GET_ELEMENT` | `text` | 查找未标记元素的文本+坐标 |
| **内部动作** | `THINK` | `text` | 记录推理过程 |
| | `REMEMBER` | `key`, `value` | 存储关键信息到记忆 |
| | `RECALL` | `query` | 从记忆检索信息 |
| | `DONE` | `text` | 子任务完成 |
| | `FAIL` | `text` | 子任务失败 |

### 动作设计亮点

- **GET_ELEMENT**：查找 SoM 未标记的交互元素（如动态菜单项），返回 `<tag>"文本" @(x,y,w,h)` 格式的坐标信息，配合 `MOUSE_CLICK` 使用
- **REFRESH**：刷新页面清除弹窗/加载异常，刷新后建议配合 `WAIT`
- 所有动作通过 `Action` dataclass 统一传递参数，新增动作不改变数据结构

---

## 常见问题

### Q: 浏览器启动后提示版本不兼容？

Playwright 引擎和 CloakBrowser 引擎的 Chrome profile **互不兼容**。切换引擎时请使用不同的 `user_data_dir`：

```json
{
  "browser_engine": "playwright",
  "playwright": { "user_data_dir": "./chrome_profile" },
  "cloakbrowser": { "user_data_dir": "./cloak_profile" }
}
```

### Q: VLM 频繁输出低置信度动作？

调整 `subagent.confidence_threshold` 降低阈值，或增加 `subagent.max_retries`：

```json
{
  "subagent": {
    "confidence_threshold": 0.7,
    "max_retries": 5
  }
}
```

### Q: 部分网页出现反爬/机器人检测？

1. 确保 `browser_engine` 为 `"playwright"` 时已安装 playwright-stealth（默认已安装）
2. 切换到 CloakBrowser：安装 `poetry install --with cloak` 后设置 `"browser_engine": "cloakbrowser"`
3. 启用 `humanize: true` 模拟人类操作

### Q: 报告太长导致 LLM 调用超时？

增大 `agent.timeout`：

```json
{
  "agent": { "timeout": 300 }
}
```

### Q: 如何查看感知模块的中间输出？

设置 `log_trace: true`，每次观察的截图和 DOM 树会保存到 `trace/` 目录中，截图文件为 SoM 标注后的版本。
