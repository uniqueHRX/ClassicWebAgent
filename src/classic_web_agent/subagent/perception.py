"""感知模块 —— CDP 驱动的 DOM 解析 + 多模态融合。

设计详见 docs/perception-design.md：
- CDP 三流采集：DOM.getDocument + Accessibility.getFullAXTree + DOMSnapshot.captureSnapshot
- backendNodeId 贯穿全链路，是采集→序列化→执行的唯一标识
- 5 步流程：截图 → CDP 采集 → 构建增强 DOM Tree → 序列化 → PageState
"""

from dataclasses import dataclass, field
from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.browser import Browser
from classic_web_agent.common.types import PageState


# ── 内部数据结构 ──────────────────────────────────────────────────────────────


@dataclass
class Bounds:
    """元素的视口坐标和尺寸。"""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


@dataclass
class EnhancedDOMNode:
    """增强 DOM 节点 —— 融合 CDP 三流数据后的统一结构。"""

    # DOM 基础字段
    backend_node_id: int = 0
    node_type: int = 0          # 1=元素, 3=文本
    tag_name: str = ""          # 元素标签名（小写）
    node_value: str = ""        # 文本节点内容
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["EnhancedDOMNode"] = field(default_factory=list)

    # AX 增强数据
    ax_role: str = ""
    ax_name: str = ""
    ax_properties: dict[str, Any] = field(default_factory=dict)

    # Snapshot 布局数据
    bounds: Bounds | None = None

    # 计算结果
    is_hidden: bool = False
    is_interactive: bool = False
    is_disabled: bool = False


# ── 交互标签 + 交互角色 + 交互事件 常量 ──────────────────────────────────────

# 级别 1：原生交互标签
_INTERACTIVE_TAGS = frozenset({
    "a", "button", "input", "select", "textarea",
    "label", "details", "summary", "dialog",
})

# 级别 2：AX 交互角色
_INTERACTIVE_ROLES = frozenset({
    "button", "link", "checkbox", "radio", "tab", "textbox",
    "combobox", "listbox", "slider", "spinbutton",
    "menuitem", "search", "searchbox",
    "switch", "option", "treeitem",
})

# 级别 3：用户交互事件（排除 onerror/onload/onresize 等非交互事件）
_USER_EVENTS = frozenset({
    "onclick", "onmousedown", "onmouseup", "onmouseover", "onmouseout",
    "onmousemove", "onkeydown", "onkeyup", "onkeypress",
    "onfocus", "onblur", "onchange", "onsubmit", "oninput",
    "oncontextmenu", "ondblclick", "onwheel",
    "ontouchstart", "ontouchend", "ontouchmove",
})

# 可聚焦属性（非事件，单独列出）
_FOCUSABLE_ATTRS = frozenset({"tabindex"})


# ── CDP 数据查询构建 ─────────────────────────────────────────────────────────


def _build_ax_lookup(ax_result: dict[str, Any]) -> dict[int, dict]:
    """构建 backendNodeId → AX 节点数据的快速查询字典。

    Accessibility.getFullAXTree() 返回:
        {"nodes": [
            {"nodeId": "...", "backendNodeId": 123,
             "role": {"value": "button", ...},
             "name": {"value": "提交", ...},
             "properties": [{"name": "disabled", "value": {...}}, ...]},
            ...
        ]}
    """
    lookup: dict[int, dict] = {}
    for node in ax_result.get("nodes", []):
        bid = node.get("backendNodeId")
        if bid is not None:
            lookup[bid] = node
    return lookup


def _build_snapshot_lookup(
    snapshot_result: dict[str, Any],
) -> dict[int, dict]:
    """构建 backendNodeId → 布局数据的快速查询字典。

    DOMSnapshot.captureSnapshot() 返回结构较复杂：
        {
            "strings": [...],
            "documents": [{
                "documentURL": 0,
                "layout": {
                    "nodeIndex": [0, 1, 2, ...],
                    "bounds": [[x,y,w,h], ...],
                    ...
                },
                ...
            }]
        }

    简化方案（阶段一）：暂不返回 bounds 数据，留待阶段二完善。
    返回空字典，序列化时不输出坐标 @()。
    """
    # 阶段一暂不实现 Snapshot 解析
    return {}
    # TODO: 阶段二实现完整 Snapshot 解析
    # strings = snapshot_result.get("strings", [])
    # for doc in snapshot_result.get("documents", []):
    #     layout = doc.get("layout", {})
    #     ... (需要对照 DOM tree 的 nodeIndex → backendNodeId 映射)


# ── 可见性判定 ────────────────────────────────────────────────────────────────


def _is_hidden(node: EnhancedDOMNode) -> bool:
    """判定节点是否隐藏。

    满足任一条件即为隐藏（整个子树跳过）：
        1. HTML hidden 属性
        2. aria-hidden="true"
        3. AX hidden property = true（对应 CSS display:none / visibility:hidden）
        4. 零宽零高（不在布局树中）
    """
    if node.node_type != 1:
        return False

    attrs = node.attributes

    # 1. 原生 hidden 属性
    if "hidden" in attrs:
        return True

    # 无交互价值的标签跳过
    if node.tag_name in ("style", "script", "meta", "noscript"):
        return True

    # CSS class 名含 hide/hidden 的隐藏元素（常见于通过 class 设置 display:none）
    for cls in attrs.get("class", "").split():
        if cls in ("hide", "hidden") or cls.endswith("-hide"):
            return True

    # input[type=hidden] 不可见也不可交互
    if node.tag_name == "input" and attrs.get("type") == "hidden":
        return True

    # 1.5 style 属性中的 CSS 隐藏（阶段一无法通过 CSS 计算属性检测）
    style_attr = attrs.get("style", "")
    if any(hidden in style_attr for hidden in
           ("display: none", "display:none",
            "opacity: 0", "opacity:0",
            "visibility: hidden", "visibility:hidden")):
        return True

    # 2. aria-hidden
    aria_hidden = attrs.get("aria-hidden", "").lower()
    if aria_hidden == "true":
        return True

    # 3. AX hidden property
    if node.ax_properties.get("hidden", False):
        return True

    # 4. 零宽零高（不在布局树中）
    if node.bounds is not None:
        if node.bounds.width == 0 and node.bounds.height == 0:
            return True

    return False


# ── 可交互元素检测（5 级） ────────────────────────────────────────────────────


def _is_interactive(node: EnhancedDOMNode) -> bool:
    """5 级检测条件，满足任一即判定为可交互元素。

    级别 1: 原生交互标签（a, button, input, select, textarea 等）
    级别 2: AX role 为交互型（button, link, checkbox, textbox 等）
    级别 3: DOM 事件属性（onclick, onmousedown, tabindex）
    级别 4: CSS cursor:pointer（通过 AX 属性间接判断）
    级别 5: AX 交互属性（focusable, editable, checked, expanded 等）
    """
    if node.node_type != 1:
        return False

    tag = node.tag_name

    # 级别 1: 原生交互标签
    if tag in _INTERACTIVE_TAGS:
        return True

    # 级别 2: AX role 为交互型
    if node.ax_role in _INTERACTIVE_ROLES:
        return True

    # 级别 3: DOM 用户交互事件（排除 onerror/onload 等非交互事件）
    for attr_name in node.attributes:
        if attr_name in _USER_EVENTS:
            return True

    # 级别 3 补充: 可聚焦属性
    for attr_name in node.attributes:
        if attr_name in _FOCUSABLE_ATTRS:
            return True

    # 级别 4 & 5: AX 交互属性
    props = node.ax_properties
    for key in ("focusable", "editable", "checked", "expanded", "pressed", "selected"):
        if props.get(key, False):
            return True

    return False


# ── AX 属性解析 ───────────────────────────────────────────────────────────────


def _parse_ax_properties(
    properties: list[dict[str, Any]],
) -> dict[str, Any]:
    """解析 AX properties 列表为扁平字典。

    Accessibility.getFullAXTree 中每个节点的 properties 字段结构：
        [{"name": "disabled", "value": {"type": "boolean", "value": true}}, ...]

    返回:
        {"disabled": true, "focusable": true, ...}
    """
    result: dict[str, Any] = {}
    for prop in properties:
        name = prop.get("name", "")
        value_info = prop.get("value", {})
        # value 可能是 {type: "boolean", value: true} 或 {type: "string", value: "..."}
        val = value_info.get("value", None)
        if val is not None:
            result[name] = val
    return result


# ── 增强 DOM 树构建 ──────────────────────────────────────────────────────────


def _build_enhanced_tree(
    dom_node: dict[str, Any],
    ax_lookup: dict[int, dict],
    snapshot_lookup: dict[int, dict],
) -> EnhancedDOMNode:
    """递归构建增强 DOM 树。

    DOM.getDocument 返回的 Node 结构：
        {
            "nodeId": 1,
            "backendNodeId": 123,
            "nodeType": 1,
            "nodeName": "DIV",
            "nodeValue": "",
            "attributes": ["class", "container", "id", "main"],
            "children": [...],
            ...
        }
    """
    backend_id = dom_node.get("backendNodeId", 0)
    node_type = dom_node.get("nodeType", 0)

    enode = EnhancedDOMNode(
        backend_node_id=backend_id,
        node_type=node_type,
    )

    if node_type == 1:  # ELEMENT_NODE
        enode.tag_name = dom_node.get("nodeName", "").lower()

        # 解析属性（CDP 返回交替数组 ["k1","v1","k2","v2"]）
        raw_attrs = dom_node.get("attributes")
        if raw_attrs:
            keys = raw_attrs[::2]
            values = raw_attrs[1::2]
            enode.attributes = dict(zip(keys, values))

        # 挂载 AX 数据
        ax_data = ax_lookup.get(backend_id)
        if ax_data:
            role_info = ax_data.get("role", {})
            enode.ax_role = role_info.get("value", "") if isinstance(role_info, dict) else ""
            name_info = ax_data.get("name", {})
            enode.ax_name = name_info.get("value", "") if isinstance(name_info, dict) else ""
            enode.ax_properties = _parse_ax_properties(ax_data.get("properties", []))

        # 挂载 Snapshot 数据（阶段一暂不实现）
        snap_data = snapshot_lookup.get(backend_id)
        if snap_data:
            bounds_data = snap_data.get("bounds")
            if bounds_data and len(bounds_data) == 4:
                enode.bounds = Bounds(*bounds_data)

    elif node_type == 3:  # TEXT_NODE
        enode.node_value = dom_node.get("nodeValue", "")

    # 可见性判定
    enode.is_hidden = _is_hidden(enode)

    # 可交互检测（仅对可见节点）
    if not enode.is_hidden:
        enode.is_interactive = _is_interactive(enode)

        # disabled 状态
        disabled_val = enode.ax_properties.get("disabled", False)
        enode.is_disabled = bool(disabled_val)

    # 递归处理子节点
    for child in dom_node.get("children", []):
        enode.children.append(
            _build_enhanced_tree(child, ax_lookup, snapshot_lookup)
        )

    return enode


# ── 序列化 ────────────────────────────────────────────────────────────────────


def _serialize(node: EnhancedDOMNode, depth: int = 0) -> str:
    """递归序列化增强 DOM 树为文本格式。

    序列化规则（详见 docs/perception-design.md §4）：
        - 隐藏节点：跳过整个子树
        - 文本节点：输出 \t*depth + text
        - 可交互元素：输出 \t*depth + [backendNodeId]<tag attr/> @(x,y,w,h)
        - 不可交互容器：不输出标签，depth 递增，子节点处理完后加空行
    """
    # 跳过隐藏节点
    if node.is_hidden:
        return ""

    indent = "\t" * depth

    # ── 文档节点（nodeType=9）：跳过本身，直接序列化子节点 ──
    if node.node_type == 9:  # DOCUMENT_NODE
        result = ""
        for child in node.children:
            result += _serialize(child, depth)
        return result

    # ── 文本节点 ──
    if node.node_type == 3:  # TEXT_NODE
        text = node.node_value.strip()
        if text:
            return f"{indent}{text}\n"
        return ""

    # ── 元素节点 ──
    if node.node_type == 1:
        interactive = node.is_interactive and not node.is_disabled
        lines = ""
        next_depth = depth + 1
        has_interactive_child = False

        if interactive:
            # 构建属性字符串
            attr_parts = []
            for k, v in node.attributes.items():
                if " " in v:
                    attr_parts.append(f'{k}="{v}"')
                else:
                    attr_parts.append(f"{k}={v}")
            attrs_str = " ".join(attr_parts)

            # 输出标签行
            lines += f"{indent}[{node.backend_node_id}]<{node.tag_name}"
            if attrs_str:
                lines += f" {attrs_str}"
            lines += " />"
            if node.bounds:
                b = node.bounds
                lines += f" @({b.x:.0f},{b.y:.0f},{b.width:.0f},{b.height:.0f})"
            lines += "\n"

        # 递归子节点
        for child in node.children:
            child_text = _serialize(child, next_depth)
            if child_text.strip():
                lines += child_text
                if not has_interactive_child and child.is_interactive and not child.is_disabled:
                    has_interactive_child = True

        # 容器退出空行（不可交互 + 非根节点 + 含直接交互子元素）
        if not interactive and depth > 0 and has_interactive_child:
            lines += "\n"

        return lines

    return ""


# ── 主类 ──────────────────────────────────────────────────────────────────────


class Perception:
    """多模态感知器 —— CDP 驱动，5 步完成页面感知。

    用法:
        perception = Perception(vlm=None, browser=browser)
        state = perception.observe()
        print(state.tree_text)
        print(f"找到 {state.tree_text.count('[')} 个可交互元素")
    """

    def __init__(self, vlm: LLMClient | None, browser: Browser | None) -> None:
        self.vlm = vlm
        self.browser = browser

    def observe(self) -> PageState:
        """观察当前页面状态，返回 PageState。

        流程：
            1. 截图（browser.screenshot → data URI）
            2. CDP 三流并行采集
            3. 构建增强 DOM Tree
            4. 遍历 + 序列化 → tree_text
            5. 组装 PageState

        Returns:
            PageState 对象。浏览器未启动或页面异常时返回安全的空 PageState。
        """
        if not self.browser or not self.browser._browser:
            return PageState()

        try:
            page = self.browser.current_page
        except Exception as e:
            logger.warning("[Perception] 获取当前页面失败: %s", e)
            return PageState()

        # ── 步骤 1: 截图（带保护，页面崩溃时不会抛异常） ──
        try:
            screenshot = self.browser.screenshot()
        except Exception as e:
            logger.warning("[Perception] 截图失败: %s", e)
            screenshot = ""

        # ── 步骤 2: CDP 三流采集 ──
        try:
            cdp = self.browser.get_cdp_session(page)
            dom_result = cdp.send("DOM.getDocument", {"depth": -1})
            ax_result = cdp.send("Accessibility.getFullAXTree")
        except Exception as e:
            logger.warning("[Perception] CDP 采集失败: %s", e)
            try:
                return PageState(screenshot=screenshot, url=page.url, title=page.title())
            except Exception:
                return PageState(screenshot=screenshot)

        try:
            snapshot_result = cdp.send("DOMSnapshot.captureSnapshot", {
                "computedStyles": [],
            })
        except Exception:
            snapshot_result = {"documents": []}

        # ── 步骤 3 & 4: 构建增强树 + 序列化 ──
        try:
            ax_lookup = _build_ax_lookup(ax_result)
            snapshot_lookup = _build_snapshot_lookup(snapshot_result)
            root = _build_enhanced_tree(
                dom_result["root"], ax_lookup, snapshot_lookup,
            )
            tree_text = _serialize(root)
        except Exception as e:
            logger.warning("[Perception] DOM 树构建失败: %s", e)
            tree_text = ""

        # ── 标签页信息 ──
        try:
            tab_id = f"tab_{self.browser.active_index}"
            tabs_lines: list[str] = []
            for i, p in enumerate(self.browser.all_pages):
                marker = " ← 当前" if i == self.browser.active_index else ""
                tabs_lines.append(f"  tab_{i}: {p.url} - {p.title()}{marker}")
            tabs_list = "\n".join(tabs_lines)
        except Exception:
            tab_id = ""
            tabs_list = ""

        # ── 步骤 5: 组装 PageState ──
        try:
            url = page.url
            title = page.title()
        except Exception:
            url = ""
            title = ""

        return PageState(
            screenshot=screenshot,
            url=url,
            title=title,
            tree_text=tree_text,
            current_tab_id=tab_id,
            tabs_list=tabs_list,
        )
