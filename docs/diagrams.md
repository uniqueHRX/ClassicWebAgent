# ClassicWebAgent UML 图集

> 在 `.vscode/settings.json` 中添加以下配置即可在 VS Code 中预览：
> ```json
> "markdown-preview-enhanced.plantumlServer": "https://kroki.io/plantuml/svg/"
> ```

---

## 图 1：系统架构总览

```plantuml
@startuml

skinparam backgroundColor #FFFFFF
skinparam defaultFontSize 16
skinparam arrowThickness 2.5
skinparam nodesep 80
skinparam ranksep 60

rectangle "  LLM 主代理 (Agent)\n===================\n  Director 编排器\n  · 任务分解 (plan)\n  · 子任务调度 (review)\n  · 报告生成 (report)" as agent #FFCCCC

rectangle "  VLM 子代理 (SubAgent)\n===================\n  ReAct 自治执行闭环\n  Perception → Planner\n  → Executor → Verifier" as subagent #FFFFCC

rectangle "  Playwright 浏览器\n===================\n  Chromium 自动化\n  CDP 三流感知采集" as browser #CCCCFF

rectangle "  用户\n========\n  自然语言\n  任务指令" as user #E8E8E8

rectangle "  共享数据模型\n  types / action / memory" as common #DDFFDD

rectangle "  模型接口\n  LLM + VLM API" as llm #F0E0FF

user -down-> agent : ① 输入任务
agent -down-> subagent : ② 派发子任务
subagent -down-> browser : ③ 操控浏览器
browser -up-> subagent : ④ 返回页面状态
subagent -up-> agent : ⑤ 返回观测结果
agent -up-> user : ⑥ 输出报告

agent -left-> llm
subagent -left-> llm
agent -right-> common
subagent -right-> common

@enduml
```

---

## 图 2：ReAct 执行闭环

```plantuml
@startuml

skinparam backgroundColor #FFFFFF
skinparam defaultFontSize 15
skinparam sequenceMessageAlign center

title SubAgent 内部 ReAct 闭环

participant "Perception\n感知模块" as P #D0FFD0
participant "Planner\n规划模块 (VLM)" as PL #FFD0D0
participant "Executor\n执行模块" as E #D0D0FF
participant "Memory\n记忆模块" as M #FFFFD0
participant "Browser\n浏览器" as B #E0E0E0

loop 最多 50 步

  P -> P : CDP 三流采集\n截图 + DOM + AXTree
  P -> PL : PageState\n(截图 + 增强 DOM 树)

  PL -> PL : VLM 看图决策\n输出 Action[] + confidence

  alt confidence ≥ 0.9
    PL -> E : 执行动作序列
    E -> B : CLICK / TYPE / SCROLL ...
    B --> E : ActionResult
    E -> M : 记录到 working
    PL -> M : memory → observations

  else confidence < 0.9
    PL -> PL : 重规划（不执行）
    note right : 连续 3 次不达标 → FAIL
  end

  PL -> PL : 检查 DONE / FAIL

end

PL -> PL : 返回 observations 给 Director

@enduml
```
