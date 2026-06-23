# 模型调度方案：LLM/VLM 双层协作

> 设计日期：2026-06-11 | 修订：2026-06-22（反映 LLM=VLM 新分工定位）
> 关联文档：[主设计方案](design.md) | [动作空间设计](action-space.md) | [感知模块设计](perception-design.md) | [Memory 增强方案](../plans/memory-enhancement-plan.md)

---

## 1. 核心思想

```
LLM（调用者）                    VLM（被调用者 / 工具）
────────────                    ───────────────────────
分解任务为子任务清单             接收单个子任务
每次调用 VLM 执行一个子任务      自治执行（内部 ReAct 循环 + confidence 机制）
VLM 返回 → LLM 审查 → 再调用    完成后返回 observations 给 LLM
汇总所有 observations 生成报告   不保留跨调用状态
```

LLM 有**持久上下文**——VLM 每次返回的 observations 通过消息历史在 LLM 上下文中自明，不需要额外的结构化存储。

---

## 2. 调用流程

```
LLM 调用 1: create_plan(task)
  → 返回子任务清单: [子任务1, 子任务2, 子任务3]

LLM 调用 2: "请执行子任务1" + VLM.execute(子任务1)
  VLM 自治执行
  → 返回 observations: "论文A: A Novel Approach (2025)\n摘要: This paper..."

LLM 调用 3: "收到，请执行子任务2" + VLM.execute(子任务2)
  ...同上...

LLM 调用 4: "所有子任务完成，生成对比报告"
  → 返回最终报告
```

**LLM 调用次数** ≈ N+2（N=子任务数）。

---

## 3. LLM 执行逻辑

### 3.1 伪代码

```python
def llm_agent_run(task: str):
    """LLM 作为调用者的主循环。"""
    messages = [SystemMessage("你是一个网页任务规划者..."), UserMessage(task)]
    
    # 调用 1: 初始规划
    plan = llm.chat(messages + [UserMessage("请分解为子任务")])
    
    all_observations = []
    for step in plan.steps:
        # 调用 2..N: 调度每个子任务
        messages.append(AssistantMessage(f"请执行: {step.goal}"))
        obs = vlm.execute(sub_task=step.goal)
        messages.append(UserMessage(f"子任务{step.id}完成: {obs}"))
        all_observations.append(obs)
        # LLM 检查结果，可决定跳过/重试/修改后续计划
    
    # 调用 N+1: 汇总报告
    report = llm.chat(messages + [UserMessage("请生成最终报告")])
    return report
```

### 3.2 示例：串行依赖子任务

以下展示 LLM 根据 VLM 返回动态决定下一个子任务（子任务间有数据依赖）：

```
用户: "帮我找一款适合摄影师的笔记本电脑，预算8000左右"

━━ LLM 调用 1: create_plan ━━━━━━━━━━━━━━━━━━━━━━━
LLM 初始规划:
  子任务1: 在京东搜索笔记本，收集7000-9000元产品列表
  （后续待定，需根据结果决定）

━━ LLM 调用 2: 调度子任务1 ━━━━━━━━━━━━━━━━━━━━━━━
LLM → VLM: "在京东搜索'笔记本电脑 摄影师'，列出7000-9000元产品"

VLM 执行:
  Step 1: GOTO jd.com → TYPE 搜索 → CLICK
          memory: "进入京东搜索页"
  Step 2: EXTRACT 产品列表
          memory: "找到: ThinkPad X1(8499), MateBook 16(7999),
                  MacBook Air M3(8999), ProArt(8299), XPS 15(7699), 战99(7299)"
  Step 3: DONE
  → observations: "找到6款7000-9000元产品..."

━━ LLM 调用 3: 审查 + 规划子任务2 ━━━━━━━━━━━━━━━━━
LLM 审查 observations:
  "8000预算适中价位是7999(MateBook)和8299(ProArt)。
  我先了解 MateBook 16 的详细配置。"

LLM → VLM: "进入MateBook 16详情页，获取CPU/GPU/内存/屏幕色域"

VLM 执行:
  Step 1: CLICK 商品 → 进入详情
  Step 2: EXTRACT 参数
          memory: "i7-13700H, RTX4060, 32GB DDR5, 16英寸 100% DCI-P3"
  Step 3: DONE
  → observations: "配置: i7+4060+32GB+100%DCI-P3"

━━ LLM 调用 4: 审查 + 规划子任务3 ━━━━━━━━━━━━━━━━━
LLM: "MateBook适合摄影师。找类似价位竞品对比。"
LLM → VLM: "获取ProArt和MacBook Air M3配置，记录与MateBook的差异"

VLM 执行:
  Step 1: GO_BACK → CLICK ProArt → EXTRACT
          memory: "ProArt: R9-7940H, RTX4060, 16GB, 100% sRGB"
  Step 2: GO_BACK → CLICK MacBook → EXTRACT
          memory: "MacBook Air M3: M3芯片, 16GB, 15.3寸, macOS, 续航12h"
  Step 3: DONE

━━ LLM 调用 5: generate_report ━━━━━━━━━━━━━━━━━━━━━
  → 生成三款产品的对比报告，推荐 MateBook 16
```

### 3.3 示例：可并行子任务

以下展示 LLM 将**互不依赖**的子任务并行调度。这类子任务天然适合使用多个 VLM 实例同时执行（见 §8 讨论）。

```
用户: "收集最近一周内关于'多模态大模型幻觉问题'的最新研究进展"

━━ LLM 调用 1: create_plan ━━━━━━━━━━━━━━━━━━━━━━━
LLM: "这个任务需要从多个学术来源收集论文。各来源互不依赖，可以并行执行。"

LLM 初始规划（4个独立子任务，无依赖关系）:
  子任务1: 在 arxiv.org 搜索 "multimodal LLM hallucination 2025"，列出最新5篇
  子任务2: 在 Semantic Scholar 搜索同主题，列出最新5篇
  子任务3: 在 Google Scholar 搜索，列出最新5篇
  子任务4: 在 Papers With Code 搜索，列出最新5篇

注 ⚡: 子任务1-4 完全独立，可以并行执行，每个在独立浏览器标签页中运行。
  执行结束后 LLM 汇总去重，再规划串行子任务（如深入阅读某篇论文）。

━━ LLM 调用 2-5: 并行调度（逻辑并行，实际可按序或异步） ━━━

LLM → VLM[tab1]: "在 arxiv 搜索 multimodal LLM hallucination 2025，列5篇"
  VLM 执行:
    GOTO arxiv → TYPE → EXTRACT → DONE
    → observations: "1. Paper A: Survey of Hallucination (arxiv.org/abs/2501.xxx)\n
                    2. Paper B: Mitigating Visual Hallucination...\n..."

LLM → VLM[tab2]: "在 Semantic Scholar 搜索同主题，列5篇"
  VLM 执行:
    GOTO semanticscholar → TYPE → EXTRACT → DONE
    → observations: "1. Paper A: Survey of Hallucination... (重复)\n
                    2. Paper F: RLAIF for MLLM... (新发现)\n..."

LLM → VLM[tab3]: "在 Google Scholar 搜索同主题"
  VLM 执行: ...同上...

LLM → VLM[tab4]: "在 Papers With Code 搜索同主题"
  VLM 执行: ...同上...

━━ LLM 调用 6: 汇总去重 + 深度分析 ━━━━━━━━━━━━━━━━

LLM 收到4组 observations，进行去重和交叉对比:

LLM 审查:
  "4个来源共找到18篇论文，去重后10篇。
  其中5篇综述类，3篇提出新方法，2篇基准评测。
  重点关注2篇高引用新方法论文。"

LLM 规划串行子任务:
  子任务5: 进入 Paper F (RLAIF for MLLM) 的详情页，提取摘要和方法
  子任务6: 进入 Paper G (Cross-modal Consistency) 详情页，提取摘要

LLM → VLM: "进入 Paper F arxiv页面，提取摘要和核心方法描述"
  VLM 执行: GOTO arxiv/abs/xxx → EXTRACT → DONE
  → observations: "Paper F 摘要: 提出基于RLAIF的多模态幻觉检测框架..."

LLM → VLM: "进入 Paper G 详情页，提取摘要"
  VLM 执行: ...同上...

━━ LLM 调用 9: generate_report ━━━━━━━━━━━━━━━━━━━━━
  → 生成: "多模态大模型幻觉问题最新研究进展综述"
    含: 10篇论文列表、研究方法分类、关键趋势、2篇重点论文深度分析
```

### 3.4 子任务调度模式

| 模式 | 特征 | 适用场景 |
|------|------|---------|
| **串行依赖** | 子任务 n+1 依赖子任务 n 的结果，LLM 根据 observations 动态决定 | 对比决策型（如购物比价、逐步深入调研） |
| **并行独立** | 子任务之间无依赖，互不干扰 | 信息收集型（如多源搜索、多站点数据采集） |
| **混合** | 先并行收集 → LLM 汇总去重 → 串行深度分析 | 复杂调研任务 |

---

## 4. VLM 执行逻辑

### 4.1 调用契约

```
输入:  子任务目标（自然语言字符串）
输出:  observations（字符串 —— VLM 每步 memory 的拼接）
```

VLM 类似于一个 `async function`：接收子任务，返回结果。

### 4.2 伪代码

```python
def vlm_execute(sub_task: str) -> str:
    """VLM 自治执行单个子任务。"""
    memory.clear_observations()
    memory.clear_working()
    
    step = 0
    retry_count = 0
    confidence_threshold = 0.9
    
    while step < MAX_STEPS:
        state = perception.observe()
        
        response = vlm.chat(
            system="你是网页操作助手...",
            user=f"子任务: {sub_task}\n"
                 f"截图: {state.screenshot}\n"
                 f"DOM树: {state.tree_text}\n"
                 f"最近操作: {memory.get_working(limit=5)}"
        )
        
        if response.confidence >= confidence_threshold:
            executor.execute(response.action)
            memory.add_observation(response.memory)
            retry_count = 0
        else:
            retry_count += 1
            if retry_count >= 3:
                return memory.get_observations() + "\n[FAIL] 连续3次低置信度"
            continue
        
        if response.action.action_type == "DONE":
            return memory.get_observations()
        if response.action.action_type == "FAIL":
            return memory.get_observations() + f"\n[FAIL] {response.action.text}"
        
        step += 1
    
    return memory.get_observations() + "\n[FAIL] 超步数"
```

### 4.3 Confidence 机制

| 条件 | 行为 |
|------|------|
| `confidence >= threshold`（默认 0.9） | 直接执行动作，`memory` 追加到 `observations` |
| `confidence < threshold` | VLM 重新规划当前步骤（不执行动作） |
| 连续 3 次重规划均不达标 | 退回上一状态 → 返回 FAIL 给 LLM |

### 4.4 VLM 输出格式

参照 browser-use 的 `AgentOutput`：

```python
{
    "thinking": "当前页面是搜索结果，找到 6 款产品...",
    "memory": "找到6款产品: ThinkPad X1(8499), MateBook 16(7999), ...",
    "action": {"action_type": "CLICK", "element_id": 1548},
    "confidence": 0.95
}
```

每次 VLM 输出中的 `memory` 字段自动调用 `Memory.add_observation()`。

---

## 5. Memory 设计

```
Memory
├── observations: list[str]         ← VLM 维护（每步子任务内累积）
│   └── VLM 返回的 memory 字段自动调用 add_observation()
│   └── 每次子任务开始前 clear_observations()
│
├── working: list[MemoryEntry]      ← VLM/Executor 维护
│   └── 操作步骤记录（最近几步，VLM 内部上下文）
│
├── knowledge: dict[str, list[KnowledgeItem]]  ← 预留，暂不使用
│   └── LLM 有持久上下文，VLM 的 observations 在消息历史中自明
│
└── url_stack: list[str]
```

---

## 6. 实施路径

| 阶段 | 内容 | 依赖 |
|------|------|------|
| **阶段一**（✅） | Infrastructure: Browser, LLMClient, Perception, Executor, Memory | — |
| **阶段二**（下一步） | VLM Planner: 看图输出 Action + memory + confidence | prompt 模板 |
| **阶段三** | LLM Planner: 任务分解 + 调用 VLM + 汇总报告 | prompt 模板 |
| **阶段四** | 完整双层架构: LLM ↔ VLM 系统调用 | 阶段二 + 三 |
| **阶段五**（远期） | 多 VLM 并行：LLM 同时调度多个 VLM 在独立标签页中执行 | 阶段四 + 异步支持 |

---

## 7. 与旧设计的区别

| 维度 | 旧设计 | 新设计 |
|------|--------|--------|
| LLM 定位 | 每步辅助决策（与 VLM 平级） | VLM 的调用者（高一层） |
| VLM 定位 | ReAct 循环中的一个参与者 | 被 LLM 调用的自治工具 |
| Confidence | Level 1/2/3 + RETRY/ESCALATE | 阈值判定 + 3 次重上限 |
| Planner 方法 | 5 | 2 (create_plan / generate_report) |
| knowledge | LLM 汇总使用 | 预留不用 |
| 子任务模式 | 仅串行 | 串行 / 并行 / 混合 |

---

## 8. 多 VLM 并行化的可行性探讨

### 8.1 是否能并行？

**可以。** VLM 本质是一个异步的正则函数调用：输入子任务描述，返回 observations。多个 VLM 之间**没有共享状态**——每个 VLM 在自己的浏览器标签页中运行，拥有独立的 CDP session 和 Memory。

并行执行的条件：[`browser.py`](src/classic_web_agent/browser.py) 已支持多标签页（`new_tab()` / `switch_tab()`），且每个标签页有独立的 CDP session（`_cdp_sessions` 字典以页面 ID 为 key）。

VLM prompt 位于 [`subagent/prompts/planner.yaml`](src/classic_web_agent/subagent/prompts/planner.yaml)，
Executor 和感知模块位于 `subagent/` 目录下。

### 8.2 并行架构

```python
import asyncio

async def llm_run_parallel(sub_tasks: list[str]) -> list[str]:
    """LLM 并行调度多个 VLM。"""
    
    # 为每个子任务创建独立的浏览器标签页
    tabs = [browser.new_tab() for _ in sub_tasks]
    
    # 并行执行：每个 VLM 在独立标签页中运行
    async def run_one(task: str, tab_index: int):
        browser.switch_tab(tab_index)
        return await vlm_execute_async(task)
    
    results = await asyncio.gather(*[
        run_one(task, i) for i, task in enumerate(sub_tasks)
    ])
    
    return results
```

### 8.3 优势

- **时间效率**：4 个并行子任务耗时 ≈ max(单个) 而非 sum(所有)
- **信息收集类任务**：多源搜索天然可并行（arxiv + Semantic Scholar + Google Scholar 可同时进行）
- **LLM 的等待成本消失**：VLM 执行期间 LLM 不需要空闲等待

### 8.4 需要解决的问题

| 挑战 | 解决方案 |
|------|---------|
| 浏览器标签页管理 | 为每个并行子任务创建独立标签页，执行完关闭 |
| CDP Session 隔离 | 每个标签页有独立 CDP session（`browser.py` 已支持） |
| Memory 隔离 | 并行 VLM 需要**独立的 Memory 实例**，各自的 observations 不混淆 |
| VLM API 并发限制 | 取决于 API 提供商（如 OpenAI 的 rate limit），可用异步控制并发数 |
| LLM 结果汇聚 | 所有 VLM 完成后，LLM 收到一组 observations，进行去重/合并/交叉验证 |
| 错误恢复 | 并行 VLM 之一失败不影响其他；LLM 汇总时标记失败子任务 |

### 8.5 何时做

**阶段五**，在基础双层架构（阶段四）稳定之后再考虑。原因：

1. 并行化增加了调试复杂性（多标签页 + 多 Memory 实例）
2. 基础架构需要先验证 VLM 自治执行的可靠性
3. 串行模式已能覆盖大部分场景；并行化是效率优化而非功能必需
4. Python asyncio + Playwright async API 需要额外的集成工作

---

## 9. 修订记录

| 日期 | 变更 |
|------|------|
| 2026-06-11 | 初稿：LLM/VLM 平级 + 三级路由 + 求救分级 |
| 2026-06-13 | 新增 confidence_threshold、StepSummary |
| 2026-06-22 | **重大重写**：LLM→VLM 调用者；每子任务返回 LLM；串行依赖示例；可并行子任务示例；多 VLM 并行化可行性探讨（阶段五） |
