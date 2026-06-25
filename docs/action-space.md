# 动作空间设计

> 设计日期：2026-06-13
> 关联文档：[主设计方案](design.md) | [模型调度方案](model-routing.md)
> 参考：CoALA 框架、BrowserAgent (2025)、WebVoyager (2024)、browser-harness

---

## 1. 设计原则

按照 **CoALA** 框架，动作空间分为**外部动作**（与浏览器环境交互）和**内部动作**（与记忆/推理系统交互）。设计遵循以下原则：

1. **最小充分集**：每个动作对应 Playwright 一条或数条原子调用，不做高层抽象封装（BrowserAgent、browser-harness 理念）
2. **VLM 友好**：动作类型清晰无歧义，避免过多相近选项增加 VLM 选择负担
3. **覆盖完整浏览行为**：涵盖元素交互、页面操作、导航、标签页管理、信息获取五大类
4. **可扩展**：通过 `extra: dict` 承载类型相关参数，新增动作不改变 `Action` dataclass 结构

---

## 2. 动作总览

| 分类 | 动作 | 参数 | Playwright 映射 |
|------|------|------|----------------|
| **元素交互** | `CLICK` | `element_id: int` | `page.locator(...).click()` |
| | `MOUSE_CLICK` | `x: int`, `y: int` | `page.mouse.click(x, y)` |
| | `TYPE` | `element_id: int`, `text: str` | `page.locator(...).fill(text)` |
| | `HOVER` | `element_id: int` | `page.locator(...).hover()` |
| **页面操作** | `SCROLL` | `direction: str` | `page.mouse.wheel(0, delta)` |
| | `PRESS` | `key: str` | `page.keyboard.press(key)` |
| | `WAIT` | `condition: str` | `page.wait_for_load_state()` 等 |
| **导航** | `GOTO` | `url: str` | `page.goto(url)` |
| | `GO_BACK` | — | `page.go_back()` |
| | `GO_FORWARD` | — | `page.go_forward()` |
| | `REFRESH` | — | `page.reload()` |
| **标签页** | `NEW_TAB` | `url: str \| None` | `context.new_page()` |
| | `CLOSE_TAB` | — | `page.close()` |
| | `SWITCH_TAB` | `tab_index: int` | `context.pages[i].bring_to_front()` |
| **信息获取** | `SCREENSHOT` | — | `page.screenshot()` |
| | `EXTRACT` | `element_id: int \| None` | `page.inner_text()` / `page.text_content()` |
| | `FIND` | `text: str, exact: bool` | `page.get_by_text(text)` → `scroll_into_view()` |
| | `GET_ELEMENT` | `text: str, exact: bool` | `page.evaluate()` 遍历 DOM 查找文本+坐标 |

**内部动作（5 个）：**

| 动作 | 参数 | 说明 |
|------|------|------|
| `THINK` | `thought: str` | ReAct Thought 环节，显式推理步骤 |
| `REMEMBER` | `key: str`, `value: str` | 将关键信息存入工作记忆（如"商品价格=2999"） |
| `RECALL` | `query: str` | 从工作记忆中检索之前存储的信息 |
| `DONE` | `summary: str` | 任务完成，输出摘要 |
| `FAIL` | `reason: str` | 任务无法完成，输出原因 |

---

## 3. 动作详解

### 3.1 元素交互

**`CLICK`** — 点击 SoM 标注元素

最常用的动作。`element_id` 为感知模块输出的 SoM 编号，Executor 通过编号映射到 Playwright locator 后执行 `click()`。支持左键单击，如需双击/右键可通过 `extra` 扩展。

**`MOUSE_CLICK`** — 坐标点击

SoM 标注的盲区 fallback。当目标在 Canvas、WebGL、iframe 内或动态生成元素中，VLM 无法获得 `element_id` 但仍能视觉定位大致坐标。`extra` 传递 `{"x": int, "y": int}`。

> 设计依据：BrowserAgent 将 `MOUSE_CLICK` 与 `CLICK` 列为独立动作。VLM 感知系统天然需要坐标级 fallback（WebVoyager / SeeAct 的 SoM 无法 100% 覆盖所有可交互元素）。

**`TYPE`** — 输入文本

内置操作序列：聚焦 → 清除现有内容 → 逐字输入 → 确认。VLM 不需要操心输入框生命周期。`element_id` 指向 `<input>` / `<textarea>` 元素。

**`HOVER`** — 悬停触发

现代电商网站（京东/淘宝）的导航菜单几乎全是 hover 触发，没有 HOVER 则无法浏览分类树。BrowserAgent 将其纳入核心动作集。

### 3.2 页面操作

**`SCROLL`** — 滚动页面

`direction` 取 `"up"` 或 `"down"`，默认滚动一视口高度。不拆分 `SCROLL_UP` / `SCROLL_DOWN` 以减少动作类型膨胀。

**`PRESS`** — 键盘单键

独立于 `TYPE`——`TYPE` 操作的是 `<input>` 元素（有 `element_id`），`PRESS` 操作的是键盘本身（无目标元素）。Playwright 实现分别为 `page.fill()` 和 `page.keyboard.press()`，合并会增加不必要的分支判断。

**`WAIT`** — 显式等待

用于语义级等待：等待搜索结果渲染、等待价格加载、等待验证码出现。这些只有 VLM 知道"等到什么程度"，Executor 的通用等待无法替代。`condition` 取 Playwright 标准值：`"load"`（所有资源加载完）/ `"domcontentloaded"`（DOM 就绪）/ `"networkidle"`（网络空闲）/ `"commit"`（导航完成）。

> 设计依据：WebVoyager 和 browser-harness 均将 wait 作为一等动作。

### 3.3 导航

**`GOTO`** — URL 导航。**`GO_BACK`** — 浏览器后退。**`GO_FORWARD`** — 浏览器前进。**`REFRESH`** — 刷新当前页面。

`GO_BACK` 保持独立语义而非合入 `GOTO`——减少 VLM 对 `GOTO("back")` 字符串的歧义理解。`GO_FORWARD` 与 `GO_BACK` 对称，Playwright 有原生 `page.go_forward()`。`REFRESH` 用于清除页面弹窗/加载异常等场景，刷新后应配合 WAIT。

### 3.4 标签页管理

**`NEW_TAB`** — 新建标签页。可选传入 `url` 在当前标签页打开指定 URL；无参则在空白标签页打开。

**`CLOSE_TAB`** — 关闭当前标签页。关闭后自动回到最近的相邻标签页。

**`SWITCH_TAB`** — 切换到指定标签页。`tab_index` 为 0-based 索引，对应 `context.pages[i]`。

> 设计依据：BrowserAgent 包含完整的多标签页操作集（NEW_TAB / PAGE_CLOSE / GO_BACK / GO_FORWARD / PAGE_FOCUS）。我们将 PAGE_FOCUS 合并进 SWITCH_TAB（切换即聚焦），剔除 NONE 无效动作。

### 3.5 信息获取

**`SCREENSHOT`** — 截取当前视口

触发感知模块重新分析当前页面。VLM 需要在"执行动作后立刻观察新状态"时显式调用——异步页面变化（AJAX 更新、动画结束、弹窗出现）不完全伴随导航事件，感知模块的固定频率截图无法替代主动观察。

**`EXTRACT`** — 提取文本内容

`element_id` 指定目标元素时提取该元素的 `inner_text`；`None` 时提取页面全文（`document.body.innerText` 截断）。与 `SCREENSHOT`（视觉信息）互补——前者获取结构化文本数据，后者获取视觉布局。

**`FIND`** — 页内文本搜索

利用 Playwright `get_by_text()` 在 DOM 层精确定位文本，并 `scroll_into_view_if_needed()` 滚动到目标位置。解决 VLM 视觉感知在长页面中的低效搜索问题——VLM 仅能"看见"一个视口，需要多次 SCROLL + SCREENSHOT 才能遍历长页面。

> 设计依据：弥补 VLM 感知架构与 BrowserAgent 的 Accessible Tree 之间的能力差距——浏览器文本搜索是确定性匹配，不依赖模型。

**`GET_ELEMENT`** — 查找未标记元素

与 `FIND` 参数相同（`text` + 可选 `exact`），但返回所有匹配元素的 DOM 信息与视口坐标，而非滚动到目标位置。用于 SoM 未标记的元素（如下拉菜单项、动态内容），输出格式与 DOM 树条目一致但不带编号：`<tag#id.class>"文本" @(x,y,w,h)`。拿到坐标后用 `MOUSE_CLICK` 点击。

> 设计依据：SoM 标注依赖 CDP snapshot 的 backendNodeId，动态生成/Shadow DOM 穿透节点无编号，VLM 看得到但无法用 CLICK 操作。GET_ELEMENT 绕过此限制，直接用浏览器 JS 遍历 DOM。

### 3.6 内部动作

**`THINK`** — ReAct Thought。显式记录推理步骤到工作记忆，提升可解释性。

**`REMEMBER`** — 显式记忆存入。Agent 在任务执行过程中识别到关键信息（价格、标题、状态等）时，主动调用此动作存入工作记忆。`extra` 承载 `{"key": str, "value": str}`。与 `memory.py` 的自动记录互补——自动记录捕获动作序列，显式存入标记语义信息。

> 设计依据：V-GEMS 状态栈思想——关键信息显式建模，避免长链任务中遗忘。阶段一实现会话级工作记忆（单任务），阶段二扩展为持久记忆（跨任务经验积累）。

**`RECALL`** — 显式记忆检索。Agent 需要之前存储的某项信息时，通过查询从工作记忆中检索。`extra` 承载 `{"query": str}`。

**`DONE`** — 任务完成。携带完成摘要。**`FAIL`** — 任务失败。携带失败原因。

---

## 4. Action 数据结构

统一 `Action` dataclass，不拆分外部/内部子类：

| 字段 | 类型 | 说明 |
|------|------|------|
| `action_type` | `ActionType` | 动作类型枚举（18 外部 + 5 内部 = 23 项） |
| `element_id` | `int \| None` | SoM 元素引用（外部动作） |
| `text` | `str \| None` | 文本参数（TYPE / THINK / DONE / FAIL / FIND） |
| `extra` | `dict[str, Any] \| None` | 扩展参数，承载类型相关数据 |
| `confidence` | `float` | VLM 生成此动作时的置信度（默认 1.0） |

`extra` 各动作的承载内容：

| 动作 | extra |
|------|-------|
| `MOUSE_CLICK` | `{"x": int, "y": int}` |
| `SCROLL` | `{"direction": "up" \| "down"}` |
| `WAIT` | `{"condition": "load" \| "domcontentloaded" \| "networkidle" \| "commit"}` |
| `GOTO` | `{"url": str}` |
| `PRESS` | `{"key": str}` |
| `NEW_TAB` | `{"url": str \| None}` |
| `SWITCH_TAB` | `{"tab_index": int}` |
| `EXTRACT` | `{"element_id": int \| None}` |
| `FIND` | `{"text": str, "exact": bool}` |
| `GET_ELEMENT` | `{"text": str, "exact": bool}` |

---

## 5. 动作校验（ActionSpace 职责）

`ActionSpace` 不只是类型枚举器，它负责：

1. **合法性校验**：`element_id` 是否在当前 `PageState` 可达元素范围内
2. **合理性校验**：`TYPE` 的目标是否为 `<input>` / `<textarea>` 类型；`CLICK` 的目标是否可见
3. **去重检测**：连续 ≥3 次相同动作且结果无变化 → 标记为异常，建议 Planner 重新规划

---

## 6. 与参考工作的对比

| 参考 | 动作数 | 本方案对齐 |
|------|--------|-----------|
| **BrowserAgent** | 18（含 NONE） | 替换 NONE/CHECK/SELECT_OPTION/PAGE_FOCUS → SCREENSHOT/WAIT/EXTRACT/FIND/GET_ELEMENT/REFRESH。总数 23 vs 18，去掉了 LLM 无法有效利用的动作，补充了 VLM 感知架构所需和显式记忆操作 |
| **WebVoyager** | ~10 | 覆盖其全部动作（Click / Type / Scroll / Goto / GoBack / Wait / Screenshot 等），并扩展标签页管理和文本获取 |
| **browser-harness** | ~12 | 共享轻量原子动作哲学；新增 FIND 和 EXTRACT 弥补纯 VLM 感知的定位短板 |

### 与 BrowserAgent 的逐项对照

| BrowserAgent | 本方案 | 理由 |
|-------------|--------|------|
| NONE | ❌ | 由 Executor 内部处理无效动作 |
| CLICK, MOUSE_CLICK, MOUSE_HOVER | CLICK, MOUSE_CLICK, HOVER | ✅ |
| KEYBOARD_TYPE, KEY_PRESS | TYPE, PRESS | ✅ |
| SCROLL | SCROLL | ✅ |
| PAGE_FOCUS | ❌ | SWITCH_TAB 已隐含聚焦 |
| NEW_TAB, PAGE_CLOSE, GO_BACK, GO_FORWARD | NEW_TAB, CLOSE_TAB, GO_BACK, GO_FORWARD | ✅ |
| GOTO_URL | GOTO | ✅ |
| CHECK, SELECT_OPTION | ❌ | CLICK 两步法更可靠（VLM 无法预知未展开的下拉选项） |
| STOP | DONE / FAIL / REMEMBER / RECALL | ✅ 语义拆分更精确，新增显式记忆操作 |
| — | SCREENSHOT | VLM 感知的主动观察触发 |
| — | WAIT | VLM 语义级等待 |
| — | EXTRACT | 按需获取页面文本 |
| — | FIND | 页内文本搜索定位 |

---

## 7. 与模型调度方案的关联

动作空间是模型调度方案（[model-routing.md](model-routing.md)）的支撑层：

- **Level 1（动作自明）**：VLM 高置信度时直接输出外部动作，跳过 Planner
- **Level 2（Skill 匹配）**：预定义操作序列由多个原子动作编排，Skill 注册在 `skills.py`
- **Level 3（LLM 推理）**：外部动作不足以推进任务时，LLM 通过 Planner 输出复杂推理链，可能含 `THINK` 内部动作

终端动作 `DONE` / `FAIL` 终止当前步骤的执行循环，触发步间审查。
