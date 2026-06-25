# 感知模块设计

> **模块定位**：感知模块在 ReAct 闭环中承担 **Observe** 环节，将页面截图与 DOM/AXTree 信息整合为 VLM/LLM 可理解的结构化输入。
>
> **核心路线**：CDP 做数据采集与元素解析，Playwright 做动作执行，`backendNodeId` 贯穿全链路。
>
> **参考方案**：[TIGER-AI-Lab/BrowserAgent](https://github.com/TIGER-AI-Lab/BrowserAgent) 与 [browser-use/browser-use](https://github.com/browser-use/browser-use)。

---

## 一、技术选型

### 总体架构

```
感知阶段 (CDP)                              执行阶段 (Playwright)
═══════════════                             ═════════════════════

CDP 三流采集                                   模型输出: CLICK [1548]
  ↓                                                 ↓
构建增强 DOM 树                              CDP DOM.resolveNode({backendNodeId: 1548})
  ↓                                                 ↓
遍历 → 检测可交互                              ElementHandle
  ↓                                                 ↓
序列化 [backendNodeId] 喂给模型                .click() / .fill()  ← 纯 Playwright
```

**核心原则**：CDP 只出现在采集和解析层，不出现在动作执行流中。

### CDP 数据流

| 流 | CDP 方法 | 提供内容 |
|----|---------|---------|
| **DOM 骨架** | `DOM.getDocument({depth: -1})` | 完整节点层级、父子关系、HTML 属性 |
| **AX 语义** | `Accessibility.getFullAXTree()` | role、name、properties (disabled/checked/expanded…) |
| **布局数据** | `DOMSnapshot.captureSnapshot()` | bounds (坐标)、computed styles、is_clickable |

三条流通过 `backendNodeId` 对齐到同一棵增强 DOM 树。

### CDP Session 管理

```python
# Playwright 原生接口，自动管理生命周期
cdp_session = await page.context.new_cdp_session(page)
# ... 采集与解析，Playwright 自动清理
```

## 二、感知流程（6 步）

```
步骤1: 截图
       └── page.screenshot(type="png", scale="css") → PIL optimize PNG → base64 data URI

步骤2: CDP 三流并行获取
       ├── DOM.getDocument({depth: -1})
       ├── Accessibility.getFullAXTree()
       └── DOMSnapshot.captureSnapshot()

步骤3: 构建 Enhanced DOM Tree
       ├── DOM 树为骨架
       ├── 每个节点挂 AX 语义 (role/name/properties)
       ├── 每个节点挂 Snapshot 数据 (bounds/styles/is_clickable)
       └── 可见性判定（见下方规则）

步骤4: 收集 SoM 可交互元素
       └── 递归收集可交互元素，提取其视口坐标（调整滚动偏移），
           为后续 Set-of-Mark 标注准备

步骤5: 遍历 + 序列化
       └── 递归遍历 DOM 树，一步完成筛选与文本输出

步骤6: SoM 标注 + 组装 PageState
       ├── 在截图上绘制 Set-of-Mark 编号标签（包围框 + 编号徽章）
       └── screenshot(已标注) + url + title + tree_text → PageState
```

### 可见性判定

以下任一条件满足则节点标记为 hidden，整个子树跳过：

- CSS `display: none` — 节点不在布局树中
- CSS `visibility: hidden` — 节点占空间但不可见（注意祖先级联继承）
- `aria-hidden="true"` — 无障碍隐藏
- HTML `hidden` 属性
- 处于视口外（bounds 与 viewport 无交集）且非 `position: fixed`
- CSS `opacity: 0` — 可选，视需求决定是否跳过（人眼不可见但技术上可点击）

`DOMSnapshot.captureSnapshot()` 输出的 `is_clickable` 字段可辅助可见性判断，减少自行计算负担。

### 遍历与序列化细节

从 Enhanced DOM Tree 根节点开始递归，对每种节点类型分别处理：

| 节点类型 | 条件 | 输出行为 |
|---------|------|---------|
| **ELEMENT_NODE** | 可交互 且 非 disabled | 输出 `\t × depth + [backendNodeId]<tag attr/>`，子节点 depth+1 |
| **ELEMENT_NODE** | 不可交互（容器 div/li 等） | 不输出标签，子节点 depth+1（保留层级），末尾加空行 |
| **TEXT_NODE** | 可见 且 非空白 | 输出 `\t × depth + node_value` |
| **任意节点** | hidden / display:none | 跳过整个子树 |

```python
# ⚠️ 伪代码，仅示意核心算法结构，实际实现可能不同

def serialize_node(node: EnhancedDOMNode, depth: int = 0) -> str:
    # ---- 跳过隐藏节点 ----
    if is_hidden(node):
        return ""

    # ---- 文本节点：直接输出文本内容 ----
    if node.type == TEXT_NODE:
        text = node.node_value.strip()
        if text:
            return "\t" * depth + text + "\n"
        return ""

    # ---- 元素节点 ----
    if node.type == ELEMENT_NODE:
        interactive = (
            is_interactive_by_rules(node)   # 5级检测条件
            and not node.is_disabled         # 跳过 disabled
        )
        lines = ""
        next_depth = depth + 1  # 始终递进，保留真实 DOM 嵌套层级
        has_interactive_child = False

        if interactive:
            # 输出可交互标签行（含完整原始属性 + 坐标 bounds）
            attrs = all_attrs(node)  # 输出所有原始 HTML 属性
            lines += "\t" * depth + f"[{node.backend_node_id}]<{node.tag_name}"
            if attrs:
                lines += " " + attrs
            lines += " />"
            if node.bounds:
                lines += f" @({node.bounds.x:.0f},{node.bounds.y:.0f},{node.bounds.width:.0f},{node.bounds.height:.0f})"
            lines += "\n"

        # 递归处理所有子节点
        for child in node.children:
            child_text = serialize_node(child, next_depth)
            if child_text.strip():
                lines += child_text
                if not has_interactive_child and child.interactive:
                    has_interactive_child = True

        # 容器退出时空行（不可交互 + 非根节点 + 含直接交互子元素）
        if not interactive and depth > 0 and has_interactive_child:
            lines += "\n"

        return lines

    return ""
```

> **两项核心改动**（相对 browser-use 完全穿透策略）：
> - **A: depth 不穿透** — `next_depth = depth + 1` 始终递进，让缩进层级反映真实 DOM 嵌套深度。
> - **B: 容器退出时空行** — 不可交互容器在处理完所有子节点后附加一个 `\n`，作为显式语义分组边界。
>
> **空行触发三条件**（缺一不可）：
> - `not interactive` — 当前节点是不可交互的容器，不是可交互标签本身。
> - `depth > 0` — 不是根节点，避免文件末尾多余空行。
> - `has_interactive_child` — 至少一个直接子元素是交互的。只检查直接子元素，不递归孙级；嵌套容器各自独立判断，避免层层空行泛滥。
>
> **风险考量**：
> - Token 增幅约 5-10%（每层容器增加 1 个 `\t`，每个含交互的容器增加 1 个 `\n`），可接受。
> - 根节点 (`depth == 0`) 不加空行，避免文件末尾多余空行。
> - 容器内无交互元素时（如 `<div><span>纯文本</span></div>`）不加空行。

---

## 三、可交互元素检测

### 5 级检测条件

| 条件 | 检测依据 | 示例 |
|------|---------|------|
| 1 | 原生交互标签 | `button`, `input`, `select`, `textarea`, `a`, `label`, `details`, `summary` |
| 2 | AX role 为交互型 | `button`, `link`, `checkbox`, `radio`, `tab`, `textbox`, `combobox`, `listbox`, `slider`, `spinbutton`, `menuitem`, `search`, `searchbox` |
| 3 | DOM 事件属性 | `onclick`, `onmousedown`, `tabindex` |
| 4 | CSS cursor | `cursor: pointer` |
| 5 | AX 交互属性 | `focusable=true`, `editable=true`, `checked`, `expanded`, `pressed`, `selected` |

### 跳过规则

满足以下任一条件的节点不分配编号、不纳入可交互元素：

- AX `disabled` property = true（节点仍出现在树中，携带 `disabled=true` 属性）
- AX `hidden` property = true（节点及其子树不出现在输出中）
- CSS `display: none` / `visibility: hidden`（节点及其子树不出现在输出中）

---

## 四、输出格式

### 格式规范

- **缩进**：`\t` 字符表示父子层级关系
- **元素编号**：直接使用 CDP `backendNodeId`（如 `[1548]`），无需重新映射
- **只有 `[backendNodeId]` 可交互**，无编号行为纯文本，不可交互
- 非可交互容器元素不输出标签，但保留其文本子节点并参与层级缩进
- **可交互元素输出完整原始 HTML 属性**（不截断、不白名单过滤）
- **坐标**：`@(x,y,w,h)` 追加在 `/>` 后，x/y 为元素左上角相对视口的 CSS 像素坐标，w/h 为元素宽高。数据来自 `DOMSnapshot.captureSnapshot()` 的 layout tree bounds。

### 输出示例（京东搜索页）

**源 HTML**（简化，仅保留结构）：

```html
<body>                                       <!-- depth=0  根 -->
  <nav class="top-nav">                      <!-- depth=1  容器 -->
    <a href="/">首页</a>                      <!-- depth=2  交互 -->
    <a href="/my/">我的京东</a>                <!-- depth=2  交互 -->
  </nav>

  <form action="/search/">                   <!-- depth=1  容器 -->
    <input type="text" placeholder="搜索" value="iPhone 15" />
    <button type="submit">                   <!-- depth=2  交互 -->
      搜索                                    <!-- depth=3  文本 -->
      🔍                                      <!-- depth=3  文本 -->
    </button>                                 <!-- depth=2  交互 -->
  </form>

  <div class="filter-area">                  <!-- depth=1  容器 -->
    <input type="checkbox" checked /> Apple   <!-- depth=2  交互 + 文本 -->
    <input type="checkbox" /> ¥5000-6000      <!-- depth=2  交互 + 文本 -->
  </div>

  <div class="product-list">                 <!-- depth=1  容器 -->
    <div class="product-item">               <!-- depth=2  容器 -->
      <a href="/product/123456.html">        <!-- depth=3  交互 -->
        iPhone 15 128GB 5G手机 黑色 128GB     <!-- depth=4  文本 -->
        ¥5999                                 <!-- depth=4  文本 -->
      </a>
      <button>加入购物车</button>              <!-- depth=3  交互 -->
    </div>
    <div class="product-item">               <!-- depth=2  容器 -->
      <a href="/product/789012.html">        <!-- depth=3  交互 -->
        iPhone 15 Pro Max 256GB 5G手机        <!-- depth=4  文本 -->
        ¥8999                                 <!-- depth=4  文本 -->
      </a>
      <button>加入购物车</button>              <!-- depth=3  交互 -->
    </div>
    <div class="product-item">               <!-- depth=2  容器 -->
      <a href="/product/345678.html">        <!-- depth=3  交互 -->
        iPhone 15 256GB 5G手机 蓝色 256GB     <!-- depth=4  文本 -->
        ¥6999                                 <!-- depth=4  文本 -->
      </a>
      <button>加入购物车</button>              <!-- depth=3  交互 -->
    </div>
  </div>
</body>
```

**序列化输出**：

```text
\t\t[87]<a href=/ /> @(20,80,80,30)
\t\t\t首页
\t\t[91]<a href=/my/ /> @(120,80,100,30)
\t\t\t我的京东

\t\t[203]<input type=text placeholder=搜索 value=iPhone 15 /> @(20,140,400,40)
\t\t[211]<button type=submit /> @(440,140,80,40)
\t\t\t搜索
\t\t\t🔍

\t\t[407]<input type=checkbox checked=true /> @(20,220,20,20)
\t\tApple
\t\t[412]<input type=checkbox /> @(60,260,20,20)
\t\t¥5000-6000

\t\t\t[478]<a href=/product/123456.html /> @(20,320,300,20)
\t\t\t\tiPhone 15 128GB 5G手机 黑色 128GB
\t\t\t\t¥5999
\t\t\t[489]<button /> @(340,320,80,30)
\t\t\t\t加入购物车

\t\t\t[523]<a href=/product/789012.html /> @(20,380,300,20)
\t\t\t\tiPhone 15 Pro Max 256GB 5G手机
\t\t\t\t¥8999
\t\t\t[531]<button /> @(340,380,80,30)
\t\t\t\t加入购物车

\t\t\t[587]<a href=/product/345678.html /> @(20,440,300,20)
\t\t\t\tiPhone 15 256GB 5G手机 蓝色 256GB
\t\t\t\t¥6999
\t\t\t[593]<button /> @(340,440,80,30)
\t\t\t\t加入购物车

```

> **对照解读**：`<body>` 是根节点（depth=0），不输出标签，且 `depth > 0` 条件阻止其末尾加空行。`<nav>`、`<form>`、`<div class="filter-area">`、`<div class="product-list">`、`<div class="product-item">` 均为不可交互容器，不输出标签行但 depth 递增，退出时插入空行分隔。导航链接 depth=2，筛选区 depth=2，商品区因多一层 `product-item` 包裹 depth=3——模型通过缩进差异感知层级深浅，通过空行感知语义分组边界。

---

## 五、元素定位映射

`backendNodeId` 是 CDP 协议原生标识符，贯穿采集→序列化→解析→执行的全程，无需重新映射。

### 完整闭环

```
感知阶段：
  DOM 遍历 → 检测 button "加入购物车" → backendNodeId = 1548
  → 序列化 "[1548]<button />\n\t加入购物车"
  → 喂给模型

模型输出：
  CLICK 1548

执行阶段：
  cdp_session.send("DOM.resolveNode", {"backendNodeId": 1548})
  → handle = page.evaluate_handle("o => o", {"objectId": result["object"]["objectId"]})
  → await handle.click()  ← 纯 Playwright 动作
```

### 协议分工

| 动作 | 定位 | 执行 |
|------|------|------|
| CLICK, TYPE, HOVER | CDP `resolveNode` | Playwright ElementHandle |
| MOUSE_CLICK | CDP `resolveNode` → bounds 坐标 | Playwright `mouse.click()` |
| SCROLL, PRESS, WAIT | 不需要 | Playwright |
| GOTO, GO_BACK, GO_FORWARD | 不需要 | Playwright |
| NEW_TAB, CLOSE_TAB, SWITCH_TAB | 不需要 | Playwright |
| SCREENSHOT, EXTRACT, FIND | 不需要 | Playwright |

---

## 六、PageState 数据结构

```python
@dataclass
class PageState:
    screenshot: str     # base64 JPEG data URI (quality=75, ~30KB)
    url: str            # 当前 URL
    title: str          # 页面标题
    tree_text: str      # 可交互元素树文本（含 backendNodeId）
```

### 双轨输出

| 模型 | 输入内容 |
|------|---------|
| **VLM** | 截图 (data URI) + tree_text |
| **LLM** | tree_text |

---

## 七、参考资料

- [TIGER-AI-Lab/BrowserAgent](https://github.com/TIGER-AI-Lab/BrowserAgent) — CDP `Accessibility.getFullAXTree` + element_id 编号方案
- [browser-use/browser-use](https://github.com/browser-use/browser-use) — CDP 三流合一 + `getEventListeners` + `[id]<tag attr/>` 输出格式
- [Chrome DevTools Protocol: Accessibility](https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/)
- [Chrome DevTools Protocol: DOMSnapshot](https://chromedevtools.github.io/devtools-protocol/tot/DOMSnapshot/)
- [Chrome DevTools Protocol: DOM](https://chromedevtools.github.io/devtools-protocol/tot/DOM/)
