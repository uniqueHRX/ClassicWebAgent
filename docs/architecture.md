# ClassicWebAgent 架构概览

> 面向用户的快速入门与架构说明。详细设计见 [设计方案](design.md) 和 [模型调度方案](model-routing.md)。

## 项目简介

ClassicWebAgent 是一个由自然语言指令驱动的网页多模态 Agent 系统，基于 **CoALA 认知架构**与 **ReAct 闭环决策**范式。系统能够接收用户的自然语言任务描述，自主操控浏览器完成网页操作。

## 核心架构

```
用户任务 → LLM (Agent) → 子任务清单 → VLM (SubAgent) → 浏览器操作
                            │                              │
                    逐个子任务执行 ← observations 返回参与
                                            │
                                     LLM 汇总生成报告
```

系统采用 **双层 Agent 架构**：

- **LLM 层**（`agent/`）：战略级决策者。将用户任务分解为子任务清单，逐项派发给 VLM，收到结果后汇总生成报告。
- **VLM 层**（`subagent/`）：战术级执行者。自治执行单个子任务（看图→决策→操作→验证→循环），返回 observations。
- **Executor**（`subagent/executor.py` + `browser.py`）：将 Action 翻译为 Playwright 浏览器操作。

## 双模型协作

- **LLM**（大语言模型）：Agent 的"大脑"——负责任务分解、子任务调度、报告生成。
- **VLM**（视觉语言模型）：SubAgent 的"眼睛和手"——分析页面截图和 DOM，输出操作动作。

LLM 是 VLM 的调用者，两者通过 `SubAgent.run(sub_task) → observations` 接口通信。

## 动作空间

系统定义了 **16 个外部动作**（浏览器操作）+ **5 个内部动作**（推理/记忆），覆盖元素交互、页面操作、导航、标签页管理和信息获取五大类。详见 [动作空间设计](action-space.md)。

## 快速启动

```bash
# 安装依赖
poetry install

# 配置 API 密钥
cp .env.example .env
# 编辑 .env 填入你的 API 密钥

# 运行
python scripts/run.py "你的任务描述"
# 或
python -m classic_web_agent --task "你的任务描述"
```

## 项目结构

```
src/classic_web_agent/
├── common/              # 共享数据模型（types/memory/action）
├── agent/               # LLM 主代理（core + director）
├── subagent/            # VLM 子代理（core + planner + executor + perception + verifier）
├── browser.py           # Playwright 浏览器驱动
├── llm.py               # LLM/VLM 客户端
├── logger.py            # 结构化日志
└── main.py              # CLI 入口
```

## 技术栈

- **语言**：Python >= 3.11
- **浏览器驱动**：Playwright
- **模型接口**：OpenAI 兼容 API
- **构建系统**：Poetry
