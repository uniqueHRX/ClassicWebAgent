# ClassicWebAgent 架构概览

> 面向用户的快速入门与架构说明。详细设计见 [设计方案](design.md) 和 [模型调度方案](model-routing.md)。

## 项目简介

ClassicWebAgent 是一个由自然语言指令驱动的网页多模态 Agent 系统，基于 **CoALA 认知架构**与 **ReAct 闭环决策**范式。系统能够接收用户的自然语言任务描述，自主操控浏览器完成网页操作。

## 核心架构

```
用户任务 → Agent 主循环 → 浏览器操作
              │
   ┌──────────┼──────────┐
   │          │          │
感知模块   规划模块    执行模块
(VLM)     (LLM)      (Playwright)
```

- **感知** (`perception.py`)：VLM 视觉分析 + DOM 解析，理解当前页面状态
- **规划** (`planner.py`)：LLM 推理下一步最优动作
- **执行** (`executor.py` + `browser.py`)：将动作翻译为 Playwright 浏览器操作
- **验证** (`verifier.py`)：检查动作效果，支持自动恢复

## 双模型协作

- **VLM**（视觉语言模型）：高频战术执行——看页面、做决策、执行动作
- **LLM**（大语言模型）：低频战略规划——任务分解、异常恢复、路径审查

三种运行模式：`auto`（推荐）、`vlm_only`（纯 VLM）、`dual_model`（对照实验）。详见 [模型调度方案](model-routing.md)。

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
src/classic_web_agent/   # 主包
├── agent/               # Agent 核心（感知/规划/执行/验证/记忆）
├── browser.py           # Playwright 浏览器驱动
├── llm.py               # LLM/VLM 客户端
├── logger.py            # 结构化日志
└── main.py              # CLI 入口

config/                  # 配置与提示词模板
scripts/                 # 辅助脚本
docs/                    # 文档
```

## 技术栈

- **语言**：Python >= 3.11
- **浏览器驱动**：Playwright
- **模型接口**：OpenAI 兼容 API
- **构建系统**：Poetry
