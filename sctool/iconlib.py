"""自绘线性图标集（PIL 手绘，无第三方图标库依赖）。

改造前工具栏用的是 Unicode 字符当图标（`▭ ◯ ☺ ↗ ✎ ▦ T 译 识 ↶ ⬇ 📌 ⧉ ✕ ✓`），
四个问题叠在一起就是"廉价感"的全部来源：

  1. `▭ ◯` 这类是**字体里的字符**，不是图形符号，不同字体粗细不一、基线不齐；
  2. `📌` 是**彩色 emoji**，跟周围单色字符放一起像贴错了图；
  3. `译`/`识` 拿汉字当图标，字号与符号对不上；
  4. 无法做 hover / active 换色，只能整块换背景。

这里统一成：**24×24 网格、1.75px 描边、圆头圆角端点、4× 超采样抗锯齿**，
按颜色生成位图，于是同一套图形能在深色工具栏、浅色按钮、胶囊徽章里复用。

⚠️ 返回的 `Image` 对象是**共享缓存**（`lru_cache`），调用方只读，不要就地修改。
"""

from __future__ import annotations

import functools
import math

from PIL import Image, ImageDraw

from . import theme

#: 图标画布边长（逻辑值，@1x）
CANVAS = 24
#: 默认描边宽度（逻辑值）
STROKE = theme.STROKE_ICON
#: 超采样倍数（抗锯齿）
SS = 4


# ============================ 绘制辅助 ============================


def _pt(x: float, y: float, n: float) -> tuple[float, float]:
    """把 24 网格坐标换算到画布坐标。"""
    return (x * n / CANVAS, y * n / CANVAS)


def _line(draw, points, color, w, n) -> None:
    """画折线，并在两端补圆点 —— PIL 的 `line` 没有圆头端点（capstyle）。"""
    pts = [_pt(x, y, n) for x, y in points]
    draw.line(pts, fill=color, width=w, joint="curve")
    r = w / 2.0
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _arrow(draw, tip, direction_deg, size, color, w, n) -> None:
    """在网格坐标 `tip` 处画 V 形箭头，`direction_deg` 是箭头**指向**的角度，
    `size` 用网格单位。

    ⚠️ 这里**绝不能**复用 `_line`：`_line` 会把传进来的点当网格坐标再换算一次，
    而箭头的翼是按画布像素算出来的，二次换算会把整个箭头扔到画布外面 ——
    表现是箭头**完全消失**（第一版就是这个坑，translate 画出来是个等号）。
    """
    cx, cy = _pt(tip[0], tip[1], n)
    span = size * n / CANVAS
    radius = w / 2.0
    for delta in (150, 210):
        angle = math.radians(direction_deg + delta)
        wing = (cx + span * math.cos(angle), cy + span * math.sin(angle))
        draw.line([(cx, cy), wing], fill=color, width=w)
        draw.ellipse(
            (wing[0] - radius, wing[1] - radius, wing[0] + radius, wing[1] + radius),
            fill=color,
        )
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius), fill=color
    )


def _box(draw, x1, y1, x2, y2, color, w, n, radius: float = 0.0) -> None:
    box = (*_pt(x1, y1, n), *_pt(x2, y2, n))
    if radius:
        draw.rounded_rectangle(box, radius=radius * n / CANVAS, outline=color, width=w)
    else:
        draw.rectangle(box, outline=color, width=w)


def _circle(draw, cx, cy, r, color, w, n, fill=None) -> None:
    box = (*_pt(cx - r, cy - r, n), *_pt(cx + r, cy + r, n))
    draw.ellipse(box, outline=color, width=w, fill=fill)


def _dot(draw, cx, cy, r, color, n) -> None:
    box = (*_pt(cx - r, cy - r, n), *_pt(cx + r, cy + r, n))
    draw.ellipse(box, fill=color)


# ============================ 各图标绘制 ============================


def _rect(d, n, c, w):
    _box(d, 4, 5, 20, 19, c, w, n, radius=2.5)


def _ellipse(d, n, c, w):
    # ⚠️ 不能走 `_box`（那里 radius=0 会退化成 rectangle），椭圆必须用 ellipse
    box = (*_pt(4, 5, n), *_pt(20, 19, n))
    d.ellipse(box, outline=c, width=w)


def _arrow_icon(d, n, c, w):
    _line(d, [(6, 18), (17, 7)], c, w, n)
    _arrow(d, (17.5, 6.5), -45, 7.0, c, w, n)


def _pen(d, n, c, w):
    # 斜放的铅笔：两条平行笔身线 + 笔尾封口 + 笔尖三角 + 笔尖分界线。
    # ⚠️ 两条边线的间距给到 ~3.2 网格单位（约 4px @32px 图标）才看得出"笔身"，
    #    第一版只给 2.8，缩到 32px 后糊成一根斜线。
    _line(d, [(6.5, 15.5), (15.5, 6.5)], c, w, n)
    _line(d, [(8.8, 17.8), (17.8, 8.8)], c, w, n)
    _line(d, [(15.5, 6.5), (17.8, 8.8)], c, w, n)
    _line(d, [(6.5, 15.5), (5.5, 18.8)], c, w, n)
    _line(d, [(8.8, 17.8), (5.5, 18.8)], c, w, n)
    _line(d, [(6.5, 15.5), (8.8, 17.8)], c, w, n)


def _mosaic(d, n, c, w):
    # 九宫格外框 + 两条内线 + 两个对角填充格，表达"打码"
    _box(d, 4, 5, 20, 19, c, w, n, radius=2.5)
    _line(d, [(4, 12), (20, 12)], c, w, n)
    _line(d, [(12, 5), (12, 19)], c, w, n)
    for x1, y1, x2, y2 in ((4, 5, 12, 12), (12, 12, 20, 19)):
        pts = [_pt(x1 + 1.2, y1 + 1.2, n), _pt(x2 - 1.2, y2 - 1.2, n)]
        d.rectangle((*pts[0], *pts[1]), fill=c)


def _text(d, n, c, w):
    _line(d, [(6, 6.5), (18, 6.5)], c, w, n)
    _line(d, [(12, 6.5), (12, 18.5)], c, w, n)
    _line(d, [(9.5, 18.5), (14.5, 18.5)], c, w, n)


def _emoji(d, n, c, w):
    _circle(d, 12, 12, 8.5, c, w, n)
    _dot(d, 9, 10, 1.3, c, n)
    _dot(d, 15, 10, 1.3, c, n)
    box = (*_pt(7.5, 9.5, n), *_pt(16.5, 17.5, n))
    d.arc(box, start=25, end=155, fill=c, width=w)


def _ocr(d, n, c, w):
    # 四个角括号 + 中间两条文本线 = "扫描识别"
    for sx, sy in ((4, 7), (20, 7), (4, 17), (20, 17)):
        dx = 3 if sx < 12 else -3
        _line(d, [(sx, sy), (sx + dx, sy)], c, w, n)
        _line(d, [(sx, sy), (sx, sy + (3 if sy < 12 else -3))], c, w, n)
    _line(d, [(8, 10.5), (16, 10.5)], c, w, n)
    _line(d, [(8, 13.5), (13, 13.5)], c, w, n)


def _translate(d, n, c, w):
    # 双向箭头 ⇄。⚠️ 两行的间距必须大于箭头翼的纵向投影，否则翼会压到另一条
    # 线上、视觉上糊成两道粗横线（第一版就是这样，实测看不出来是箭头）。
    _line(d, [(6, 8.5), (18, 8.5)], c, w, n)
    _arrow(d, (18, 8.5), 0, 6.0, c, w, n)
    _line(d, [(18, 15.5), (6, 15.5)], c, w, n)
    _arrow(d, (6, 15.5), 180, 6.0, c, w, n)


def _undo(d, n, c, w):
    # 上半圆弧 + 左端向下的箭头（经典 undo 造型）
    box = (*_pt(5.5, 7, n), *_pt(18.5, 20, n))
    d.arc(box, start=170, end=370, fill=c, width=w)
    _arrow(d, (5.7, 14.4), 95, 5.5, c, w, n)


def _save(d, n, c, w):
    _line(d, [(12, 3.5), (12, 15)], c, w, n)
    _arrow(d, (12, 15), 90, 6.0, c, w, n)
    _line(d, [(5, 19.5), (19, 19.5)], c, w, n)


def _pin(d, n, c, w):
    # 图钉俯视：钉帽（上宽下窄的方框）+ 中间竖针。
    # 第一版帽高 4.5、针长 9.5，比例失衡画出来像个酒杯，这里压扁帽、拉长针。
    _line(d, [(8.5, 4), (15.5, 4)], c, w, n)
    _line(d, [(8.5, 4), (8.5, 7)], c, w, n)
    _line(d, [(15.5, 4), (15.5, 7)], c, w, n)
    _line(d, [(8.5, 7), (15.5, 7)], c, w, n)
    _line(d, [(12, 7), (12, 19.5)], c, w, n)


def _copy(d, n, c, w):
    # 两个框对角错开，避免重叠处需要底色遮罩
    _box(d, 8.5, 4, 20, 15.5, c, w, n, radius=2.5)
    _box(d, 4, 8.5, 15.5, 20, c, w, n, radius=2.5)


def _close(d, n, c, w):
    _line(d, [(6.5, 6.5), (17.5, 17.5)], c, w, n)
    _line(d, [(17.5, 6.5), (6.5, 17.5)], c, w, n)


def _confirm(d, n, c, w):
    _line(d, [(4.5, 12.5), (9.5, 17.5), (19.5, 6)], c, w, n)


def _capture(d, n, c, w):
    """取景框四角 + 中心圆点 —— 「开始截屏」主按钮的图标（2026-10-10 参考图）。

    改造前这个按钮没有图标（纯文字）。四角 + 圆点是最通用的"截图"隐喻，
    和工具栏上那些标注图标也不会混。
    """
    arm = 4.8
    for x, y, sx, sy in (
        (3.5, 3.5, 1, 1),
        (20.5, 3.5, -1, 1),
        (3.5, 20.5, 1, -1),
        (20.5, 20.5, -1, -1),
    ):
        _line(d, [(x + sx * arm, y), (x, y), (x, y + sy * arm)], c, w, n)
    _circle(d, 12, 12, 3.4, c, w, n)


def _settings(d, n, c, w):
    """滑块（两条轨道 + 各一枚滑块）。

    改造前画的是"圆环 + 8 根辐条" —— 那恰好就是**亮度 / 太阳**图标的画法，
    主人在主窗口里一眼看成了"切换深色模式"的开关。滑块是"偏好设置"的通用隐喻，
    和主题切换再无歧义。

    轨道在滑块处**断开**再放一枚实心圆：同色的实心圆压在同色的线上是看不出来的，
    必须留出空隙（透明底上没法靠描边解决）。
    """
    for y, knob_x in ((8.5, 15.0), (15.5, 9.0)):
        gap = 3.6
        _line(d, [(4.5, y), (knob_x - gap, y)], c, w, n)
        _line(d, [(knob_x + gap, y), (19.5, y)], c, w, n)
        _dot(d, knob_x, y, 2.9, c, n)


def _folder(d, n, c, w):
    _box(d, 3.5, 6.5, 20.5, 19, c, w, n, radius=2.5)
    _line(d, [(3.5, 10.5), (20.5, 10.5)], c, w, n)


def _log(d, n, c, w):
    _box(d, 5, 3.5, 19, 20.5, c, w, n, radius=2.5)
    _line(d, [(8.5, 8.5), (15.5, 8.5)], c, w, n)
    _line(d, [(8.5, 12), (15.5, 12)], c, w, n)
    _line(d, [(8.5, 15.5), (12.5, 15.5)], c, w, n)


def _opacity(d, n, c, w):
    _circle(d, 12, 12, 8, c, w, n)
    box = (*_pt(4, 4, n), *_pt(20, 20, n))
    d.pieslice(box, start=90, end=270, fill=c)


def _zoom(d, n, c, w):
    _circle(d, 10.5, 10.5, 6.5, c, w, n)
    _line(d, [(15.5, 15.5), (20.5, 20.5)], c, w, n)


def _palette(d, n, c, w, accent: str | None = None):
    """色卡：**半圆三等分**，中间那一格实时显示"当前标注色"。

    历史：圆环+3点 → 颜料滴 → 色轮（4 象限）→ 2×2 色卡 → **半圆三等分色卡**
    （主人 2026-10-08 定稿：指定"半圆形状并三等分，中间部分实时显示当前颜色"）。

    画法（24 网格）：圆心 (12, 19)、半径 **10.5** 的**上半圆**，被两条径向线分成 3 个
    60° 扇区；**中间扇区（正上方）填 `accent`**（= 当前标注色），左右两格只留轮廓。

    ⚠️ 半径必须给足（10.5，几乎占满画布）：工具栏图标只有 19px，半圆画小了在
       LANCZOS 缩放后会被抹成"三角形 / 帐篷"，中间那格的颜色也小到看不清
       （主人 2026-10-08 实测反馈："这个图标不是半圆，而且图标过小了，实时颜色显示
       不够显眼"——原半径 8.5 只占 17×8.5，太小）。

    ⚠️ `accent` 是这个图标的"第二颜色"（描边色由 `c` 给）。见 `_ACCENT_ICONS` ——
       普通图标都是单色的，只有它需要两色，所以 `icon_image` / `icon_photo` 多了一个
       `accent` 参数，并且**它是缓存键的一部分**（换色必须出新的位图）。
    ⚠️ PIL 的角度是**从 3 点钟起顺时针**（y 轴向下），所以"正上方"是 270°，
       中间扇区取 `start=240, end=300`。
    """
    fill_color = accent or theme.B500
    cx, cy, r = 12.0, 19.0, 10.5
    box = (*_pt(cx - r, cy - r, n), *_pt(cx + r, cy + r, n))
    # 中间扇区（正上方 60°）填当前标注色 —— 先填，后面画的线才能压在上面
    d.pieslice(box, start=240, end=300, fill=fill_color)
    # 上半圆弧 + 底边（直径）
    d.arc(box, start=180, end=360, fill=c, width=w)
    _line(d, [(cx - r, cy), (cx + r, cy)], c, w, n)
    # 两条径向分割线（240° / 300°）
    for deg in (240.0, 300.0):
        ang = math.radians(deg)
        _line(
            d,
            [(cx, cy), (cx + r * math.cos(ang), cy + r * math.sin(ang))],
            c,
            w,
            n,
        )


def _stroke(d, n, c, w):
    # 三条粗细递增的横线，表达"线宽"
    for y, factor in ((7, 0.7), (12, 1.3), (17, 2.1)):
        _line(d, [(5, y), (19, y)], c, max(1, int(round(w * factor))), n)


def _trash(d, n, c, w):
    _line(d, [(4, 6.5), (20, 6.5)], c, w, n)
    _line(d, [(9.5, 6.5), (9.5, 4)], c, w, n)
    _line(d, [(14.5, 6.5), (14.5, 4)], c, w, n)
    _line(d, [(9.5, 4), (14.5, 4)], c, w, n)
    _line(d, [(6, 6.5), (7.5, 20), (16.5, 20), (18, 6.5)], c, w, n)


def _external(d, n, c, w):
    _line(d, [(13, 4.5), (19.5, 4.5), (19.5, 11)], c, w, n)
    _line(d, [(19.5, 4.5), (11, 13)], c, w, n)
    _line(d, [(17, 14), (17, 19.5), (4.5, 19.5), (4.5, 7), (10, 7)], c, w, n)


def _info(d, n, c, w):
    _circle(d, 12, 12, 8.5, c, w, n)
    _line(d, [(12, 11), (12, 16.5)], c, w, n)
    _dot(d, 12, 7.8, 1.2, c, n)


def _refresh(d, n, c, w):
    # 缺口开在右侧的圆环 + 右上端一个朝外的箭头
    box = (*_pt(5.5, 5.5, n), *_pt(18.5, 18.5, n))
    d.arc(box, start=40, end=320, fill=c, width=w)
    _arrow(d, (17.0, 7.9), -50, 6.0, c, w, n)


#: 图标名 → 绘制函数
_ICONS = {
    "rect": _rect,
    "ellipse": _ellipse,
    "arrow": _arrow_icon,
    "pen": _pen,
    "mosaic": _mosaic,
    "text": _text,
    "emoji": _emoji,
    "ocr": _ocr,
    "translate": _translate,
    "undo": _undo,
    "save": _save,
    "pin": _pin,
    "copy": _copy,
    "close": _close,
    "confirm": _confirm,
    "capture": _capture,
    "settings": _settings,
    "folder": _folder,
    "log": _log,
    "opacity": _opacity,
    "zoom": _zoom,
    "palette": _palette,
    "stroke": _stroke,
    "trash": _trash,
    "external": _external,
    "info": _info,
    "refresh": _refresh,
}

#: 需要"第二颜色"（accent）的图标 —— 目前只有色卡：它的中间格要实时显示当前标注色，
#: 而描边色是另一个通道。其余图标都是单色的。
_ACCENT_ICONS = frozenset({"palette"})

#: 可用图标名（供校验 / 排查）
NAMES = tuple(sorted(_ICONS))


# ============================ 对外入口 ============================


@functools.lru_cache(maxsize=512)
def icon_image(
    name: str,
    color: str,
    size: int = CANVAS,
    stroke: float = STROKE,
    accent: str | None = None,
):
    """生成图标位图（带缓存）。**返回的图是共享的，只读。**

    `accent` 只对 `_ACCENT_ICONS` 里的图标有意义（目前只有色卡：中间格显示当前标注色）。

    ⚠️ 走 `lru_cache`，所以 `size` / `stroke` / `accent` 都参与缓存键 —— 传浮点没关系，
       但同一尺寸别用 `24` 和 `24.0` 混着传，那会命中两个不同的缓存条目。
    """
    painter = _ICONS.get(name)
    if painter is None:
        raise KeyError(f"未知图标：{name}（可用：{', '.join(NAMES)}）")

    n = int(size) * SS
    canvas = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    width = max(1, int(round(stroke * SS)))
    if name in _ACCENT_ICONS:
        painter(draw, n, color, width, accent)
    else:
        painter(draw, n, color, width)
    return canvas.resize((int(size), int(size)), Image.LANCZOS)


def icon_photo(
    master,
    name: str,
    color: str,
    size: int = CANVAS,
    stroke: float = STROKE,
    accent: str | None = None,
):
    """图标 → Tk PhotoImage（缓存并长期持有引用，见 theme.photo 的说明）。"""
    key = ("icon", name, color, int(size), round(float(stroke), 2), accent)
    return theme.photo(
        icon_image(name, color, size, stroke, accent), key=key, master=master
    )
