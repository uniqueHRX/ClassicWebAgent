# ClassicWebAgent 项目设计方案

> 基于 `.agent/main.pdf` 项目开题报告，参考 browser-harness 轻量设计理念
> 设计日期：2026-06-10 | 修订：2026-06-13
> 关联细节文档：[模型调度方案](model-routing.md) | [感知模块设计](perception-design.md) | [审查报告](../.agent/review_report.md)

---

## 1. 设计原则

### 1.1 架构依据（项目规划书 §2.2）

本项目采用 **CoALA（Cognitive Architectures for Language Agents）** 作为总体架构组织方式：

| CoALA 层 | 职责 | 对应文件 |
|----------|------|---------|
| **记忆层 (Memory)** | 工作记忆、会话记忆 | [`common/memory.py`](../src/classic_web_agent/common/memory.py) |
| **动作空间 (Action Space)** | 外部动作（浏览器操作）、内部动作（检索/推理） | [`common/action.py`](../src/classic_web_agent/common/action.py) |
| **决策层 (Decision Cycle)** | LLM 调度 → SubAgent 自治执行 | [`agent/core.py`](../src/classic_web_agent/agent/core.py) + [`subagent/`](../src/classic_web_agent/subagent/) |

执行流程采用 **ReAct 闭环**：观察 → 规划 → 执行 → 验证。ReAct 的此流程是 CoALA 决策循环（Observation → Proposal/Evaluation → Selection/Execution → Observation）的一种特化实现。

### 1.2 Python 项目规范

- **标准 src layout**：`src/classic_web_agent/` 包（PEP 517/518）
- **导入路径**：`from classic_web_agent.agent.core import Agent`
- **Python 版本**：`>=3.11`（与 browser-harness 等参考项目基线一致）

### 1.3 简化原则

- 目录深度 ≤ 3 层
- 每个模块优先单文件，仅在必要时拆分
- 不用 LangChain 等重型框架，Python + Playwright 直连
- 感知/浏览器/日志均合为单文件

### 1.4 双模型协作

LLM（大语言模型）与 VLM（视觉语言模型）分工协作——LLM 负责战略级粗粒度规划，VLM 负责战术级感知与执行。详细设计见 [模型调度方案](model-routing.md)。

---

## 2. 目录结构总览

```
ClassicWebAgent/
│
├── src/
│   └── classic_web_agent/
│       ├── __init__.py, __main__.py
│       ├── main.py, config.py, llm.py, logger.py, browser.py, skills.py
│       │
│       ├── common/                           # 共享数据模型与逻辑
│       │   ├── types.py                      # 所有数据模型（Action/PageState/MemoryEntry/TodoItem...）
│       │   ├── memory.py                     # 三层记忆管理器
│       │   └── action.py                     # 动作类型枚举 + ActionSpace
│       │
│       ├── agent/                            # LLM 主代理
│       │   ├── core.py                       # Agent.run() 主循环（Director + SubAgent 双层架构）
│       │   ├── director.py                   # 编排器：plan() → review() → report()
│       │   ├── __init__.py
│       │   └── prompts/
│       │       ├── director.yaml              # LLM 任务分解 + 调度提示词
│       │       └── reporter.yaml              # LLM 报告生成提示词
│       │
│       └── subagent/                         # VLM 子代理
│           ├── core.py                       # SubAgent：子任务自治执行循环
│           ├── planner.py                    # VLM 动作规划（看图+DOM→动作序列）
│           ├── executor.py                   # 动作执行器（Action→Playwright）
│           ├── perception.py                 # 页面感知（CDP 采集+DOM 解析）
│           ├── verifier.py                   # 动作效果验证
│           ├── __init__.py
│           └── prompts/
│               └── planner.yaml              # VLM 动作规划提示词
│
├── config/
│   ├── config.json
│   └── prompts/                              # 预留提示词模板
│
├── tests/
├── docs/
├── scripts/
├── logs/
└── ...
```

---

## 3. 模块依赖关系

```mermaid
graph TD
    MAIN[main.py]
    CFG[config.py]
    LOG[logger.py]
    BR[browser.py]
    LLM[llm.py]

    subgraph agent [LLM Agent]
        AGENT["core.py"]
        DIR["director.py"]
        DPR["prompts/director.yaml"]
    end

    subgraph subagent [VLM SubAgent]
        SUB["core.py"]
        SPL["planner.py"]
        SEX["executor.py"]
        SPE["perception.py"]
        SVER["verifier.py"]
        SPR["prompts/planner.yaml"]
    end

    subgraph common [共享模块]
        TYP["types.py"]
        MEM["memory.py"]
        ACT["action.py"]
    end

    MAIN --> AGENT
    MAIN --> CFG
    AGENT --> DIR
    AGENT --> SUB

    DIR --> LLM
    DIR --> DPR
    DIR --> MEM

    SUB --> SPL
    SUB --> SEX
    SUB --> SPE

    SPL --> LLM
    SPL --> SPR
    SPL --> MEM

    SEX --> ACT
    SEX --> BR
    SEX --> MEM

    SPE --> BR

    MEM --> TYP
```

LLM 和 VLM 通过 `SubAgent.run(sub_task) → observations` 接口通信。`common/` 中的 types/memory/action 被双方共享。

---

## 4. 数据流（三阶段架构）

```
用户任务（一句话）
  │  "帮我调研AI领域热门研究方向，包括LLM和多模态"
  ▼
┌──────────────────────────────────────────────────────────┐
│ Agent.run(task)                                          │
│                                                          │
│  ┌─ 阶段1: 任务分解 ──────────────────────────────────┐  │
│  │ Director.plan(task)  → task_plan + todo_list       │  │
│  │   ← LLM 调用1: 基于世界知识拓展为任务计划书          │  │
│  │     task_plan: 研究维度/数据源/子领域/评判标准       │  │
│  │     todo_list: [子任务1, 子任务2, ..., 子任务N]      │  │
│  └────────────────────────────────────────────────────┘  │
│                           │                               │
│  ┌─ 阶段2: 执行调度循环 ──────────────────────────────┐  │
│  │ for each 子任务:                                   │  │
│  │   SubAgent.run(sub_task) → observations            │  │
│  │     ├── VLM 自治执行（Perception→Planner→Executor） │  │
│  │     └── observations 返回给 LLM                    │  │
│  │                                                    │  │
│  │   Director.review(observations) → 更新 todo_list    │  │
│  │     ← LLM 调用2..N: 审查 + 更新 + 下一个子任务      │  │
│  └────────────────────────────────────────────────────┘  │
│                           │                               │
│  ┌─ 阶段3: 报告生成 ──────────────────────────────────┐  │
│  │ Director.report(task_plan, all_observations)       │  │
│  │   ← LLM 调用N+1: 对照计划书生成最终报告            │  │
│  └────────────────────────────────────────────────────┘  │
│                           │                               │
└───────────────────────────┼──────────────────────────────┘
                            ▼
                     TaskResult(summary=报告)
```

LLM 通过持久对话上下文维护状态。每次 `SubAgent.run()` 返回的 observations
以 UserMessage 形式追加到 Director._messages 中，因此 LLM 能看到所有历史。
`knowledge` 暂不使用。

---

## 5. 文件职责摘要

| 文件 | 核心职责 | 阶段 |
|------|---------|------|
| [`common/types.py`](../src/classic_web_agent/common/types.py) | 数据模型：PageState/Action/ActionResult/MemoryEntry/TodoItem/DirectorOutput... | 一 |
| [`common/memory.py`](../src/classic_web_agent/common/memory.py) | 三层记忆：observations + working + knowledge(预留) | 一 |
| [`common/action.py`](../src/classic_web_agent/common/action.py) | ActionType 枚举（21 个动作）+ ActionSpace 校验/去重 | 一 |
| [`agent/core.py`](../src/classic_web_agent/agent/core.py) | Agent 主循环：plan() → review() 循环 → report() | 三 |
| [`agent/director.py`](../src/classic_web_agent/agent/director.py) | LLM 编排器：加载 prompt → 调用 LLM → 解析 JSON | 三 |
| [`agent/prompts/director.yaml`](../src/classic_web_agent/agent/prompts/director.yaml) | LLM 系统提示词：任务分解 + 子任务调度 | 三 |
| [`agent/prompts/reporter.yaml`](../src/classic_web_agent/agent/prompts/reporter.yaml) | LLM 系统提示词：最终报告生成 | 三 |
| [`subagent/core.py`](../src/classic_web_agent/subagent/core.py) | SubAgent：VLM 子任务自治执行循环 | 二 |
| [`subagent/planner.py`](../src/classic_web_agent/subagent/planner.py) | VLM 动作规划：加载 planner.yaml → 看图+DOM → Action 列表 | 二 |
| [`subagent/executor.py`](../src/classic_web_agent/subagent/executor.py) | Action → Playwright 原子操作（21 个动作路由） | 一 |
| [`subagent/perception.py`](../src/classic_web_agent/subagent/perception.py) | CDP 三流采集 + EnhancedDOMTree + 序列化 → PageState | 一/二 |
| [`subagent/verifier.py`](../src/classic_web_agent/subagent/verifier.py) | 动作效果验证（stub，待实现） | 二 |
| [`subagent/prompts/planner.yaml`](../src/classic_web_agent/subagent/prompts/planner.yaml) | VLM 系统提示词：动作规划 | 二 |
| [`browser.py`](../src/classic_web_agent/browser.py) | Playwright 驱动 + 原子操作 | 一 |
| [`llm.py`](../src/classic_web_agent/llm.py) | OpenAI 兼容 API，LLM/VLM 双模式，统一重试/超时 | 一 |
| [`logger.py`](../src/classic_web_agent/logger.py) | 日志记录 + 报告保存 + 截图保存 | 一/三 |
| [`config.py`](../src/classic_web_agent/config.py) | 配置管理：合并 .env + config.json 的深度合并器 | 一 |
| [`main.py`](../src/classic_web_agent/main.py) | CLI 入口 + 运行目录创建 + 文件日志 + 报告持久化 | 一 |
| [`skills.py`](../src/classic_web_agent/skills.py) | Skill 注册（预留） | 二 |
| [`scripts/run.py`](../scripts/run.py) | 开发辅助：自动加载 `.env`，调用 `main()` | 一 |

---

## 6. 入口点设计

| 入口 | 用途 | 关系 |
|------|------|------|
| [`__main__.py`](../src/classic_web_agent/__main__.py) | `python -m classic_web_agent` | 仅 `from classic_web_agent.main import main; main()` |
| [`main.py`](../src/classic_web_agent/main.py) | 唯一 CLI 逻辑（argparse） | 定义 `main()` 函数 |
| [`scripts/run.py`](../scripts/run.py) | 开发辅助脚本 | 自动加载 `.env` + 调用 `main()`（不重复 CLI 逻辑） |

---

## 7. 关键配置文件

### 7.1 `config/config.json`

```json
{
  "log_screenshot": false,
  "agent": {
    "model": "deepseek-v4-flash",
    "base_url": "...",
    "api_key": "",
    "temperature": 0.1
  },
  "subagent": {
    "model": "mimo-v2.5",
    "base_url": "...",
    "api_key": "",
    "temperature": 0.1,
    "confidence_threshold": 0.9
  }
}
```

**优先级**：默认值 < `config.json` < 环境变量（`LLM_*` / `VLM_*`）。

**配置传递链**：`config.json` → `config.load_config()` → `main.create_agent()` → `Agent(config)` → `SubAgent(subagent_config)` → `Planner(confidence_threshold)`。

### 7.2 `pyproject.toml` 关键配置

```toml
[project]
name = "ClassicWebAgent"
requires-python = ">=3.11"

[tool.poetry]
packages = [{include = "classic_web_agent", from = "src"}]

[tool.poetry.scripts]
classic-web-agent = "classic_web_agent.main:main"
```

### 7.3 `prompts/` 模板目录

| 模板文件 | 所属模块 | 说明 |
|---------|---------|------|
| [`agent/prompts/director.yaml`](../src/classic_web_agent/agent/prompts/director.yaml) | Director (LLM) | 任务分解 + 子任务调度提示词，含 task_plan 世界知识拓展 |
| [`agent/prompts/reporter.yaml`](../src/classic_web_agent/agent/prompts/reporter.yaml) | Director (LLM) | 最终报告生成提示词，对照 task_plan 组织内容 |
| [`subagent/prompts/planner.yaml`](../src/classic_web_agent/subagent/prompts/planner.yaml) | Planner (VLM) | 动作规划提示词：看图+DOM → Action 序列 |

---

## 8. 图片编码策略

### 8.1 截图 → VLM 传输协议

Playwright 截图（PNG）通过 **PIL (Pillow) optimize PNG** 编码为 base64 data URI 后传递给 VLM。

**理由**（基于环境测试结果）：
- PIL `save(format="PNG", optimize=True)` 可获得 **~6.9% 压缩率**，同时保持 VLM (mimo-v2.5) 识别成功率 100%
- JPEG 有损压缩对小截图（<50KB）因编码开销反而膨胀体积，不适用
- 原始文件直接 base64 无压缩，但 PIL optimize 零损失且减少传输 token
- mimo-v2.5 对 PIL 重新编码的 PNG 字节变化**不敏感**

**实现位置**：`browser.py` 截图后调用编码函数，生成 data URI 传递给 `llm.py` 的 VLM 调用。

---

## 9. 模型调度

LLM 与 VLM 的分工遵循 **调用者与被调用者分离** 原则：

- **LLM（Director）**：负责任务分解和子任务调度，不操作浏览器
- **VLM（SubAgent）**：自治执行子任务，通过 `SubAgent.run(sub_task) → observations` 接口返回结果

LLM 通过持久对话上下文维护任务状态，VLM 的 observations 在消息历史中自明。

详见 [模型调度方案](model-routing.md)。

---

## 10. 阶段规划与文件映射

| 阶段 | 对应文件 |
|------|---------|
| **阶段一**（✅ 完成） | Infrastructure：Browser, LLMClient, Perception, Executor, Memory + 目录重构 |
| **阶段二**（✅ 完成） | SubAgent 自治执行循环 + VLM Planner |
| **阶段三**（✅ 完成） | LLM Director：任务分解 + 子任务调度 + 报告生成 |
| **阶段四**（进行中） | 完整 LLM ↔ VLM 双层架构 + 多 VLM 并行 + 运行目录系统 |

---

## 11. 参考资料

| 参考资料 | 关联设计 |
|---------|---------|
| **CoALA (2024)** | 总体架构：记忆层 + 动作空间 + 决策循环 |
| **ReAct** | 执行流程：Thought-Action-Observation 交替 |
| **Mind2Web (2023)** | 粗粒度规划 + 细粒度执行的分层思想 |
| **SeeAct (2024)** | 感知先行、按需推理——高置信度直行，低置信度调用 LLM |
| **V-GEMS / See and Remember (2026)** | 步骤完成后更新状态、重评估路径 |
| **WebVoyager (2024)** | VLM 直接输出动作（对应 vlm_only 模式） |
| **browser-harness** | Skill 库短路 + 自愈机制 |
| **BrowserAgent (2025)** | Playwright 原子操作设计 |

---

## 附录：文档导航

| 文档 | 位置 | 说明 |
|------|------|------|
| 本文件 | [`docs/design.md`](design.md) | 项目主设计方案 |
| 动作空间 | [`docs/action-space.md`](action-space.md) | 21 动作类型定义（16 外部 + 5 内部）、Playwright 映射、参考对比 |
| 感知模块设计 | [`docs/perception-design.md`](perception-design.md) | CDP 四流采集 + 增强 DOM 树 + 元素定位映射 + 输出格式 |
| 模型调度方案 | [`docs/model-routing.md`](model-routing.md) | LLM/VLM 协作、层级规划、三级路由细节 |
| 审查报告 | [`.agent/review_report.md`](../.agent/review_report.md) | 子代理设计审查（A- / 87分） |
| 用户向概述 | [`docs/architecture.md`](architecture.md) | 面向用户的架构概览 |
