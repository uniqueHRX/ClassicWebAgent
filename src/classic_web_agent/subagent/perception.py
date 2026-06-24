"""感知模块 —— CDP 驱动的 DOM 解析 + 多模态融合。

设计详见 docs/perception-design.md：
- CDP 三流采集：DOM.getDocument + Accessibility.getFullAXTree + DOMSnapshot.captureSnapshot
- backendNodeId 贯穿全链路，是采集→序列化→执行的唯一标识
- 5 步流程：截图 → CDP 采集 → 构建增强 DOM Tree → 序列化 → PageState
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from classic_web_agent.llm import LLMClient
from classic_web_agent.browser import Browser
from classic_web_agent.common.types import PageState

logger = logging.getLogger(__name__)


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

    DOMSnapshot.captureSnapshot() 返回结构如下：
        {
            "strings": ["str0", "str1", ...],
            "documents": [{
                "documentURL": 0,  # index into strings
                "nodes": {
                    "parentIndex": [0, 1, 2, ...],
                    "nodeType": [1, 3, 1, ...],
                    "nodeName": [0, 1, 0, ...],   # string index
                    "nodeValue": [2, 3, ...],     # string index
                    "backendNodeId": [11, 22, 33, ...],
                    ...
                },
                "layout": {
                    "nodeIndex": [0, 2, 0, 3, ...],  # index into nodes
                    "bounds": [[x1,y1,w1,h1], [x2,y2,w2,h2], ...],
                    ...
                },
                ...
            }]
        }

    layout.nodeIndex[i] 指向 nodes 数组中的索引，layout.bounds[i] 为该节点的坐标。
    构建 backend_node_id → {x, y, width, height} 的映射字典。
    """
    lookup: dict[int, dict] = {}
    if not snapshot_result:
        return lookup

    strings = snapshot_result.get("strings", [])
    documents = snapshot_result.get("documents", [])
    if not documents:
        return lookup

    doc = documents[0]
    nodes = doc.get("nodes", {})
    layout = doc.get("layout", {})

    backend_ids: list[int] = nodes.get("backendNodeId", [])
    node_indices: list[int] = layout.get("nodeIndex", [])
    bounds_list: list[list[float]] = layout.get("bounds", [])

    # 构建 layout.nodeIndex → backendNodeId 的映射
    for i, node_idx in enumerate(node_indices):
        if i >= len(bounds_list):
            break
        if node_idx < len(backend_ids):
            bid = backend_ids[node_idx]
            if bid == 0:
                continue
            b = bounds_list[i]
            if len(b) >= 4:
                lookup[bid] = {
                    "bounds": [b[0], b[1], b[2], b[3]],
                }

    return lookup


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
    parent_hidden: bool = False,
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

    Args:
        parent_hidden: 父元素是否隐藏（CSS display:none / visibility:hidden 继承）。
                       True 时该节点及其所有子树都被标记为隐藏，无需重复检测。
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

    # 可见性判定：父元素隐藏 → 子元素必隐藏（CSS 继承）
    if parent_hidden:
        enode.is_hidden = True
    else:
        enode.is_hidden = _is_hidden(enode)

    # 可交互检测（仅对可见节点）
    if not enode.is_hidden:
        enode.is_interactive = _is_interactive(enode)

        # disabled 状态
        disabled_val = enode.ax_properties.get("disabled", False)
        enode.is_disabled = bool(disabled_val)

    # 递归处理子节点（传递父元素隐藏状态）
    child_hidden = parent_hidden or enode.is_hidden
    for child in dom_node.get("children", []):
        enode.children.append(
            _build_enhanced_tree(child, ax_lookup, snapshot_lookup, parent_hidden=child_hidden)
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


# ── SoM 标注数据收集 ──────────────────────────────────────────────────────────────


def _collect_som_elements(
    node: EnhancedDOMNode,
    scroll_x: int = 0,
    scroll_y: int = 0,
    viewport_w: int = 0,
    viewport_h: int = 0,
) -> list[dict]:
    """递归收集增强树中适合 SoM 标注的元素（位于视口内且有坐标）。

    收集条件：
        1. 元素节点（node_type == 1）
        2. 可交互（is_interactive）
        3. 未隐藏（is_hidden == False）
        4. 有有效的布局坐标（bounds 非 None）
        5. 调整滚动后位于视口内

    Args:
        scroll_x, scroll_y: 当前页面滚动偏移，用于将文档坐标转为视口坐标。
        viewport_w, viewport_h: 视口尺寸，用于过滤视口外的元素。

    Returns:
        list[dict]: 每个元素包含 {backend_node_id, tag_name, x, y, width, height}。
    """
    results: list[dict] = []

    if node.node_type == 1 and node.is_interactive and not node.is_hidden and node.bounds is not None:
        b = node.bounds
        # 过滤最小尺寸（小于 5px 的不标注，避免噪音）
        if b.width > 5 and b.height > 5:
            # 文档坐标 → 视口坐标（减去滚动偏移）
            vp_x = int(b.x) - scroll_x
            vp_y = int(b.y) - scroll_y
            vp_w = int(b.width)
            vp_h = int(b.height)

            # 完全在视口外（任何方向都不可见）的元素跳过
            if not (vp_x + vp_w > 0 and vp_y + vp_h > 0):
                pass  # 跳过
            elif viewport_w > 0 and (vp_x >= viewport_w or vp_y >= viewport_h):
                pass  # 完全在视口右/下方，跳过
            else:
                results.append({
                    "backend_node_id": node.backend_node_id,
                    "tag_name": node.tag_name,
                    "x": max(0, vp_x),
                    "y": max(0, vp_y),
                    "width": vp_w,
                    "height": vp_h,
                })

    for child in node.children:
        results.extend(_collect_som_elements(
            child, scroll_x, scroll_y, viewport_w, viewport_h,
        ))

    return results


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
            4. SoM 标注 → 在截图叠加编号标签（可配置开关）
            5. 遍历 + 序列化 → tree_text
            6. 组装 PageState

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

        # ── 步骤 3: 构建增强树 ──
        try:
            ax_lookup = _build_ax_lookup(ax_result)
            snapshot_lookup = _build_snapshot_lookup(snapshot_result)
            root = _build_enhanced_tree(
                dom_result["root"], ax_lookup, snapshot_lookup,
            )
        except Exception as e:
            logger.warning("[Perception] DOM 树构建失败: %s", e)
            root = None

        # ── 步骤 4: SoM 标注 ──（仅在 enhanched tree 构建成功时）
        if root is not None and screenshot:
            try:
                # 获取当前滚动偏移、视口尺寸和 DPR
                scroll_x = 0
                scroll_y = 0
                viewport_w = 0
                viewport_h = 0
                dpr = 1.0
                try:
                    page_data = page.evaluate(
                        "() => ({x: window.pageXOffset, y: window.pageYOffset, "
                        "w: document.documentElement.clientWidth, "
                        "h: document.documentElement.clientHeight, "
                        "dpr: window.devicePixelRatio})"
                    )
                    scroll_x = int(page_data.get("x", 0))
                    scroll_y = int(page_data.get("y", 0))
                    viewport_w = int(page_data.get("w", 0))
                    viewport_h = int(page_data.get("h", 0))
                    dpr = float(page_data.get("dpr", 1.0))
                except Exception:
                    pass

                elements = _collect_som_elements(
                    root,
                    scroll_x=scroll_x,
                    scroll_y=scroll_y,
                    viewport_w=viewport_w,
                    viewport_h=viewport_h,
                )
                if elements and dpr != 1.0:
                    # scale="css" 确保截图尺寸与 CSS 像素一致，
                    # 但在有头模式下 Playwright 可能仍输出物理像素。
                    # 通过 DPR 缩放坐标，确保标注与截图元素对齐。
                    for el in elements:
                        el["x"] = int(el["x"] * dpr)
                        el["y"] = int(el["y"] * dpr)
                        el["width"] = int(el["width"] * dpr)
                        el["height"] = int(el["height"] * dpr)
                if elements:
                    from classic_web_agent.subagent.som import annotate_screenshot
                    annotated = annotate_screenshot(screenshot, elements)
                    if annotated != screenshot:
                        logger.info(
                            "[Perception] SoM 标注 %d 个元素 "
                            "(scroll=%d,%d dpr=%.1f)",
                            len(elements), scroll_x, scroll_y, dpr,
                        )
                        screenshot = annotated
            except Exception as e:
                logger.warning("[Perception] SoM 标注失败: %s", e)

        # ── 步骤 5: 序列化 → tree_text ──
        try:
            tree_text = _serialize(root) if root is not None else ""
        except Exception as e:
            logger.warning("[Perception] 序列化失败: %s", e)
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
