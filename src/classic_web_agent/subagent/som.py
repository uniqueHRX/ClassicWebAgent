"""Set-of-Mark (SoM) 截图标注 —— 在可交互元素上叠加编号标签。

在 Perception 阶段对截图进行 SoM 标注，让 VLM 能直观地将
tree_text 中的 backend_node_id 与截图上的元素位置对齐。

参考：
    - browser-use python_highlights.py（PIL 绘制方案）
    - BrowserAgent modify_page（DOM 注入方案）

用法：
    from classic_web_agent.subagent.som import annotate_screenshot
    annotated = annotate_screenshot(data_uri, elements)
"""

import base64
import io
import logging
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ── 颜色映射：标签类型 → 标记颜色 ────────────────────────────────────────

_ELEMENT_COLORS: dict[str, str] = {
    "button": "#e74c3c",      # 红
    "input": "#3498db",       # 蓝
    "select": "#9b59b6",      # 紫
    "textarea": "#e67e22",    # 橙
    "a": "#27ae60",           # 绿
    "label": "#1abc9c",       # 青
    "summary": "#f39c12",     # 黄
    "dialog": "#e74c3c",      # 红
    "default": "#95a5a6",     # 灰
}


def _get_color(tag_name: str) -> str:
    """根据标签名返回标记颜色。"""
    return _ELEMENT_COLORS.get(tag_name.lower(), _ELEMENT_COLORS["default"])


# ── 字体管理与跨平台路径 ──────────────────────────────────────────────────

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",              # Linux Arch
    "/System/Library/Fonts/Arial.ttf",                       # macOS
    "/Library/Fonts/Arial.ttf",                              # macOS alt
    "C:\\Windows\\Fonts\\arial.ttf",                         # Windows
    "arial.ttf",                                              # Windows sys
    "Arial Bold.ttf",                                         # macOS alt
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Linux alt
]

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | None] = {}


def _get_font(size: int) -> ImageFont.ImageFont | Any:
    """带缓存的跨平台字体加载。

    依次尝试系统路径，全部失败时返回 PIL 默认字体。
    """
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]

    for path in _FONT_PATHS:
        try:
            font = ImageFont.truetype(path, size)
            _FONT_CACHE[size] = font
            return font
        except (OSError, IOError):
            continue

    # Fallback: PIL 默认字体
    default_font = ImageFont.load_default()
    _FONT_CACHE[size] = None
    return default_font


# ── 核心标注函数 ─────────────────────────────────────────────────────────

def annotate_screenshot(
    screenshot_data_uri: str,
    elements: list[dict[str, Any]],
) -> str:
    """对截图进行 SoM 标注，返回标注后的 data URI。

    Args:
        screenshot_data_uri: 原始截图 (base64 PNG data URI)。
        elements: 可交互元素列表，每个元素包含：
            - backend_node_id: int
            - tag_name: str
            - x, y, width, height: int (视口坐标)

    Returns:
        标注后的 base64 PNG data URI。
        渲染失败或无可标注元素时返回原始截图。
    """
    if not screenshot_data_uri or not elements:
        return screenshot_data_uri

    # 1. 解码截图
    try:
        _, encoded = screenshot_data_uri.split(",", 1)
        image_data = base64.b64decode(encoded)
        image = Image.open(io.BytesIO(image_data))
    except Exception as e:
        logger.warning("[SoM] 截图解码失败: %s", e)
        return screenshot_data_uri

    img_w, img_h = image.size
    draw = ImageDraw.Draw(image)

    # 2. 计算字体大小（基于截图宽度）
    font_size = max(10, min(16, int(img_w * 0.012)))
    font = _get_font(font_size)
    fallback_font_size = max(7, font_size - 3)

    # 3. 逐个绘制元素标注
    for el in elements:
        try:
            _draw_element_label(
                draw=draw,
                backend_node_id=el["backend_node_id"],
                tag_name=el.get("tag_name", ""),
                x=int(el["x"]),
                y=int(el["y"]),
                w=int(el["width"]),
                h=int(el["height"]),
                img_size=(img_w, img_h),
                font=font,
            )
        except Exception as e:
            logger.debug("[SoM] 绘制元素 %d 失败: %s", el.get("backend_node_id", 0), e)
            continue

    # 4. 编码回 data URI
    try:
        output = io.BytesIO()
        image.save(output, format="PNG")
        encoded_out = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded_out}"
    except Exception as e:
        logger.warning("[SoM] 重编码失败: %s", e)
        return screenshot_data_uri


# ── 单元素标注绘制 ──────────────────────────────────────────────────────

def _draw_element_label(
    draw: ImageDraw.Draw,
    backend_node_id: int,
    tag_name: str,
    x: int, y: int,
    w: int, h: int,
    img_size: tuple[int, int],
    font: ImageFont.ImageFont | Any,
) -> None:
    """在单个元素上绘制包围框 + 左上角编号标签。

    绘制内容：
        1. 元素区域的虚线/实线包围框（使用元素类型对应颜色）
        2. 包围框左上角或正上方的一个实心编号标签

    标签位置策略：
        - 元素够大 → 标签放在元素内部左上角
        - 元素太小 → 标签放在元素正上方（居中对齐）
        自动处理边界裁剪，确保标签和包围框不超出截图范围。
    """
    label = str(backend_node_id)
    color = _get_color(tag_name)
    img_w, img_h = img_size

    # ── 裁剪元素框到视口边界 ──
    # 元素可能部分在视口外（尤其在滚动后），只绘制在视口内的部分
    clip_x = max(0, x)
    clip_y = max(0, y)
    clip_w = min(w, img_w - clip_x)
    clip_h = min(h, img_h - clip_y)
    if clip_w <= 2 or clip_h <= 2:
        return  # 裁剪后太小，跳过

    # ── 绘制元素包围框 ──
    # 在元素四条边上分别画短的线段模拟虚线效果
    dash_len = 4
    gap_len = 6
    line_width = 1
    x2 = clip_x + clip_w
    y2 = clip_y + clip_h

    for xs in range(clip_x, x2, dash_len + gap_len):
        xe = min(xs + dash_len, x2)
        draw.line([(xs, clip_y), (xe, clip_y)], fill=color, width=line_width)
        draw.line([(xs, y2), (xe, y2)], fill=color, width=line_width)
    for ys in range(clip_y, y2, dash_len + gap_len):
        ye = min(ys + dash_len, y2)
        draw.line([(clip_x, ys), (clip_x, ye)], fill=color, width=line_width)
        draw.line([(x2, ys), (x2, ye)], fill=color, width=line_width)

    # ── 计算编号标签文字尺寸 ──
    bbox_text = draw.textbbox((0, 0), label, font=font)
    text_w = bbox_text[2] - bbox_text[0]
    text_h = bbox_text[3] - bbox_text[1]

    # 标签背景内边距
    pad_x = 4
    pad_y = 2
    badge_w = text_w + pad_x * 2
    badge_h = text_h + pad_y * 2

    # ── 定位标签 ──
    min_badge_area = badge_w * badge_h * 2
    element_area = clip_w * clip_h

    if element_area >= min_badge_area:
        # 放在元素内部左上角（偏移 2px）
        bx = clip_x + 2
        by = clip_y + 2
    else:
        # 放在元素正上方（居中对齐）
        bx = clip_x + (clip_w - badge_w) // 2
        by = clip_y - badge_h - 2

    # 边界裁剪
    bx = max(0, min(bx, img_w - badge_w))
    by = max(0, min(by, img_h - badge_h))

    # ── 绘制编号标签 ──
    draw.rectangle(
        [bx, by, bx + badge_w, by + badge_h],
        fill=color,
        outline="#ffffff",
        width=1,
    )
    text_x = bx + pad_x - bbox_text[0]
    text_y = by + pad_y - bbox_text[1]
    draw.text((text_x, text_y), label, fill="white", font=font)
