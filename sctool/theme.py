"""设计令牌与视觉工厂（纯 tkinter + PIL 预渲染）。

本模块是**所有界面的唯一视觉出处**：颜色、圆角、间距、字号、阴影都从这里取，
不允许在别处硬编码色值。改造前项目里有四套互不相干的色系（结果窗口蓝
`#2F6FD0`、遮罩绿 `#2ecc71`、工具栏 `#2b2b2b`、放大镜 `#1e1e1e`），
现在全部收进下面这张表。

⚠️ DPI：令牌里的尺寸一律是 **@1x 逻辑值**，用之前必须过 `px()` 换算成物理
   像素。本机 200% 缩放，写死像素必然出错（README #3 有历史教训）。

⚠️ 圆角抗锯齿：PIL 的 `rounded_rectangle` **不做抗锯齿**，直接画会看到阶梯。
   所以所有圆角图都在 `SS=4` 倍的画布上绘制、再 LANCZOS 缩回，边缘才平滑。
"""

from __future__ import annotations

import functools
import tkinter as tk

from PIL import Image, ImageDraw, ImageFilter, ImageTk

# ============================ 颜色令牌 ============================

# ---- 中性色阶 ----
N0 = "#FFFFFF"  # 卡片 / 内容底
N50 = "#F7F8FA"  # 应用底
N100 = "#F1F3F5"  # 次级底 / 悬停底
N200 = "#E5E7EB"  # 分隔线 / 细边框
N300 = "#D1D5DB"  # 强边框
N500 = "#6B7280"  # 次要文字
N700 = "#374151"  # 正文
N900 = "#111827"  # 标题

# ---- 品牌色阶（沿用原 #2F6FD0 色相，补齐悬停与选中档）----
B50 = "#EFF5FD"  # 选中底 / 浅填充
B100 = "#DCE9FA"  # 浅填充加深
B300 = "#8FB6E8"  # 描边
B500 = "#2F6FD0"  # 主色（与改造前一致）
B600 = "#2560B8"  # 悬停
B700 = "#1D4E96"  # 按下

# ---- 选区 / 成功 ----
G500 = "#22C55E"  # 选区框、手柄、成功态
G600 = "#16A34A"

# ---- 危险 ----
R500 = "#EF4444"  # 取消键悬停、错误文字

# ---- 主控制面板的品牌绿（2026-10-10 参考图）----
# ⚠️ 这一组**只服务主控制面板**。结果窗口 / 遮罩 / 设置窗口继续用上面的蓝色
#    B500 系 —— 那些界面已经过八轮验收，不跟着换色（主人本轮只要求改主窗口）。
BRAND = "#0F5132"  # 主按钮底（深绿）
BRAND_HOVER = "#14603C"  # 悬停
BRAND_PRESS = "#0A3D26"  # 按下
BRAND_SOFT = "#E7F6EC"  # 浅绿底（徽章 / 提示底）
BRAND_SOFT_LINE = "#CFE8DA"  # 浅绿底的描边
BRAND_TEXT = "#166534"  # 浅绿底上的文字

# ---- 深色面（工具栏 / 放大镜 / Toast）----
D900 = "#1F2225"  # 面板底（统一了原来的 #2b2b2b 与 #1e1e1e）
D800 = "#2A2E33"  # 悬停底
D700 = "#343A40"  # 激活底 / 分隔线
D100 = "#E8EAED"  # 深底上的主文字
D400 = "#9AA0A6"  # 深底上的次要文字

#: 深色面上的分隔线
D_SEP = "#3A4045"

# ============================ 尺寸令牌（@1x）============================

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14
#: 胶囊：取一个远大于任何控件半高的值即可
RADIUS_PILL = 999

SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

#: 描边宽度（@1x）
STROKE_HAIRLINE = 1
STROKE_ICON = 1.75

# ============================ 字体令牌 ============================

FONT_FAMILY = "Microsoft YaHei UI"

#: ⚠️ 字号**不放大**：现有 10pt 在 200% DPI 下渲染出来已经不小，放大会把每个
#: 窗口尺寸顶大、重新踩一遍布局坑（README #3 / #11）。这里只补层级。
FONT_TIP = (FONT_FAMILY, 9)
FONT_BODY = (FONT_FAMILY, 10)
FONT_EMPH = (FONT_FAMILY, 11)
FONT_BUTTON = (FONT_FAMILY, 13, "bold")
FONT_TITLE = (FONT_FAMILY, 15, "bold")
FONT_BRAND = (FONT_FAMILY, 20, "bold")
#: 主控制面板的品牌名（2026-10-10 参考图）。比 FONT_BRAND 小一档 ——
#: 参考图里 "SnapLingo" 约占窗口宽 35%，480 逻辑宽下对应 ~17pt。
FONT_HERO = (FONT_FAMILY, 17, "bold")

#: 工具栏上「识」「译」这两个**汉字按钮**的字号。
#: 主人 2026-10-08 明确要求保留这两个字："它们是软件的主要功能，用字更醒目"。
#: 所以它们不走自绘图标通道，而是用加粗汉字 + 品牌浅蓝着色（见 overlay 里的
#: ACTION_KEYS），字号比图标略小一档、但墨量大得多，视觉重量反而更重。
FONT_ACTION = (FONT_FAMILY, 14, "bold")

# ============================ 阴影预设 ============================

SHADOW_CARD = {"blur": 8, "offset": (0, 3), "alpha": 0.10, "color": (17, 24, 39)}
SHADOW_FLOAT = {"blur": 14, "offset": (0, 6), "alpha": 0.14, "color": (17, 24, 39)}
SHADOW_DARK = {"blur": 12, "offset": (0, 5), "alpha": 0.35, "color": (0, 0, 0)}

#: 超采样倍数（圆角抗锯齿用）
SS = 4


# ============================ DPI 换算 ============================


def scale(widget: tk.Misc) -> float:
    """当前显示器的缩放比例（1.0 = 100%，本机为 2.0）。

    与 `ui.dpi_scale` 是同一套算法；这里自己实现一份，是为了让 theme 保持
    最底层、不反向依赖界面模块。
    """
    try:
        return widget.winfo_fpixels("1i") / 96.0
    except tk.TclError:
        return 1.0


def px(widget: tk.Misc, value: float) -> int:
    """把 @1x 逻辑尺寸换算成当前 DPI 下的物理像素。"""
    return int(round(value * scale(widget)))


def pxf(factor: float, value: float) -> int:
    """已知 scale 时用这个（避免反复查询 widget）。"""
    return int(round(value * factor))


# ============================ 圆角 / 阴影工厂 ============================


def rgba(color: str, alpha: float) -> tuple[int, int, int, int]:
    """`#RRGGBB` + 透明度 → RGBA 元组（PIL 用）。"""
    value = color.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return (r, g, b, int(round(255 * max(0.0, min(1.0, alpha)))))


@functools.lru_cache(maxsize=512)
def _rounded(
    w: int, h: int, radius: int, fill: str, outline, outline_width: int, ss: int
):
    """在 `ss` 倍画布上画圆角矩形再缩回 —— 这样边缘才是抗锯齿的。"""
    w, h = max(1, int(w)), max(1, int(h))
    canvas = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (0, 0, w * ss - 1, h * ss - 1),
        radius=max(0, int(radius)) * ss,
        fill=fill,
        outline=outline,
        width=max(0, int(outline_width)) * ss,
    )
    if ss == 1:
        return canvas
    return canvas.resize((w, h), Image.LANCZOS)


def rounded_image(
    w: int,
    h: int,
    radius: int = RADIUS_MD,
    fill: str = N0,
    outline: str | None = None,
    outline_width: int = 0,
    *,
    antialias: bool = True,
) -> Image.Image:
    """一张圆角矩形（带缓存）。返回的图**不含**任何额外边距。

    ⚠️ `antialias=False` 是给 **Toast / tooltip** 这类无边框浮层用的：
    它们要靠 Tk 的 `-transparentcolor` 把圆角外的区域抠成透明，而
    `-transparentcolor` 是**精确匹配**——抗锯齿产生的半透明边缘像素抠不掉，
    会在圆角外留一圈杂色描边。关掉超采样后外侧就是纯魔法色，能干净抠除。
    """
    return _rounded(
        int(w), int(h), int(radius), fill, outline, int(outline_width), SS if antialias else 1
    )


def _shadow_key(shadow: dict | None) -> tuple | None:
    """把 `shadow` 字典转成可哈希的缓存键 —— dict 本身进不了 `lru_cache`。"""
    if shadow is None:
        return None
    return tuple(
        sorted(
            (key, tuple(value) if isinstance(value, (list, tuple)) else value)
            for key, value in shadow.items()
        )
    )


@functools.lru_cache(maxsize=64)
def _shadowed_cached(
    w: int,
    h: int,
    radius: int,
    fill: str,
    outline: str | None,
    outline_width: int,
    shadow_key: tuple | None,
    ss: int,
) -> tuple[Image.Image, int]:
    """`shadowed_image` 的缓存实现体。参数全部可哈希，见下面的公开包装。"""
    spec = dict(shadow_key) if shadow_key is not None else dict(SHADOW_CARD)
    blur = int(spec.get("blur", 8))
    offset = tuple(spec.get("offset", (0, 3)))
    alpha = float(spec.get("alpha", 0.10))
    color = tuple(spec.get("color", (17, 24, 39)))

    pad = blur * 2
    total_w, total_h = int(w) + pad * 2, int(h) + pad * 2

    layer = Image.new("RGBA", (total_w * ss, total_h * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    ox, oy = offset
    draw.rounded_rectangle(
        (
            (pad + ox) * ss,
            (pad + oy) * ss,
            (pad + ox + int(w)) * ss,
            (pad + oy + int(h)) * ss,
        ),
        radius=max(0, int(radius)) * ss,
        fill=color + (int(round(255 * alpha)),),
    )
    layer = layer.resize((total_w, total_h), Image.LANCZOS).filter(
        ImageFilter.GaussianBlur(blur)
    )
    layer.alpha_composite(
        rounded_image(w, h, radius, fill, outline, outline_width), (pad, pad)
    )
    return layer, pad


def shadowed_image(
    w: int,
    h: int,
    radius: int = RADIUS_MD,
    fill: str = N0,
    *,
    outline: str | None = None,
    outline_width: int = 0,
    shadow: dict | None = None,
) -> tuple[Image.Image, int]:
    """圆角矩形 + 投影。返回 `(图, 边距)`。

    ⚠️ 返回的图比 `w×h` **大 `2×边距`**，摆放时必须把坐标减去边距，否则会偏移。
    边距 = 2×模糊半径，留够空间让阴影自然扩散、不被裁掉。

    ⚠️⚠️ **带缓存**（见 `_shadowed_cached`）。一张卡片要 4× 超采样画完再 LANCZOS
    缩回 + 高斯模糊，实测 86~163ms —— 而遮罩的放大镜卡片、工具栏底、气泡、面板
    每张截图都会重建一遍，是"按热键到画面出现"延迟里最大的单项。缓存之后第 2 次
    起只剩一次 `copy()`。

    ⚠️ 因此**返回的是私有副本**（不是缓存对象本身）：`overlay._open_palette` /
    `_open_strokes` 会拿到图后直接 `ImageDraw.Draw(board)` 就地画色块，若把缓存
    对象交出去，第二次打开面板色块就会重复叠加。
    """
    image, pad = _shadowed_cached(
        int(w),
        int(h),
        int(radius),
        fill,
        outline,
        int(outline_width),
        _shadow_key(shadow),
        SS,
    )
    return image.copy(), pad


def flat_image(
    w: int,
    h: int,
    radius: int = RADIUS_MD,
    fill: str = N0,
    *,
    outline: str | None = None,
    outline_width: int = 0,
    shadow: dict | None = None,
) -> tuple[Image.Image, int]:
    """统一入口：`shadow=None` 时就是纯圆角图（边距 0）。

    与 `shadowed_image` 一样，**返回的是私有副本**，调用方可以放心就地绘制。
    """
    if shadow is None:
        return rounded_image(w, h, radius, fill, outline, outline_width).copy(), 0
    return shadowed_image(
        w,
        h,
        radius,
        fill,
        outline=outline,
        outline_width=outline_width,
        shadow=shadow,
    )


def framed_image(
    image: Image.Image,
    radius: int,
    *,
    outline: str | None = N200,
    outline_width: int = 1,
    shadow: dict | None = None,
    antialias: bool = True,
) -> tuple[Image.Image, int]:
    """把一张**现成的图**裁成圆角、加描边、可选投影。返回 `(图, 边距)`。

    结果窗口的截图预览用它 —— 改造前预览图是 `tk.Label(bd=1, relief="solid")`，
    一个硬邦邦的直角黑框。

    ⚠️ 遮罩直接复用 `rounded_image` 的 alpha 通道，而不是自己再画一遍圆角：
       既省掉一次超采样，也保证圆角半径和别处的卡片完全一致。
    ⚠️ `antialias=False` 给钉图窗口用：那边圆角外要靠 `-transparentcolor` 抠成
       透明，抗锯齿的半透明边缘抠不干净，会留一圈杂色。
    """
    w, h = image.size
    mask = rounded_image(w, h, radius, "#FFFFFF", antialias=antialias).getchannel("A")

    body = image.convert("RGBA")
    body.putalpha(mask)
    if outline and outline_width:
        ImageDraw.Draw(body).rounded_rectangle(
            (0, 0, w - 1, h - 1),
            radius=max(0, int(radius)),
            outline=outline,
            width=int(outline_width),
        )
    if shadow is None:
        return body, 0

    spec = dict(shadow)
    blur = int(spec.get("blur", 8))
    ox, oy = tuple(spec.get("offset", (0, 3)))
    alpha = float(spec.get("alpha", 0.10))
    color = tuple(spec.get("color", (17, 24, 39)))
    pad = blur * 2
    total_w, total_h = w + pad * 2, h + pad * 2

    layer = Image.new("RGBA", (total_w * SS, total_h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        ((pad + ox) * SS, (pad + oy) * SS, (pad + ox + w) * SS, (pad + oy + h) * SS),
        radius=max(0, int(radius)) * SS,
        fill=color + (int(round(255 * alpha)),),
    )
    layer = layer.resize((total_w, total_h), Image.LANCZOS).filter(
        ImageFilter.GaussianBlur(blur)
    )
    layer.alpha_composite(body, (pad, pad))
    return layer, pad


# ============================ PhotoImage 缓存 ============================
#
# ⚠️ 不能给 PhotoImage 用 lru_cache：Tk 端图像数据由 Python 对象持有，
# 对象一旦被 GC，Canvas 就会渲染出未初始化内存（表现为彩色条纹 —— 
# 这个坑项目里已经踩过，见 overlay.py 里 `_refresh_region` 的注释）。
# 所以用一个永不回收的模块级 dict 明确持有引用。

_photos: dict[object, ImageTk.PhotoImage] = {}


def photo(image: Image.Image, key: object = None, master: tk.Misc | None = None):
    """PIL 图 → Tk PhotoImage（`key` 非空时缓存并长期持有引用）。"""
    if key is not None:
        cached = _photos.get(key)
        if cached is not None:
            return cached
    result = ImageTk.PhotoImage(image, master=master)
    if key is not None:
        _photos[key] = result
    return result


def rounded_photo(
    master: tk.Misc,
    w: int,
    h: int,
    *,
    radius: int = RADIUS_MD,
    fill: str = N0,
    outline: str | None = None,
    outline_width: int = 0,
    key: object = None,
):
    """圆角图的 PhotoImage 便捷封装。"""
    cache_key = key if key is not None else ("round", w, h, radius, fill, outline, outline_width)
    return photo(
        rounded_image(w, h, radius, fill, outline, outline_width),
        key=cache_key,
        master=master,
    )


def clear_photo_cache() -> None:
    """释放所有缓存的 PhotoImage（仅在 Tk 根窗口被销毁时用）。"""
    _photos.clear()
