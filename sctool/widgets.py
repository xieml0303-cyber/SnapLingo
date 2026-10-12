"""自绘控件库（tkinter Canvas + PIL）。

tkinter 原生控件做不出这些东西：

    tk.Button        不支持圆角，只能整块换背景色
    tk.Checkbutton   90 年代外观，且方框在 200% DPI 下会被拉变形
    ttk.Progressbar  直角、跟随系统主题、和本项目的配色体系打架
    —                没有 tooltip、没有 toast、没有分段控件

所以这里全部用 `tk.Canvas` 手工绘制。

⚠️ 每个 Canvas 都必须显式 `highlightthickness=0` —— Canvas 默认带 2px 高亮
   边框，不关掉的话圆角外面会套一圈灰框（这是最容易漏的一处）。
⚠️ 所有尺寸都过 `theme.px()` 换算：本机 200% DPI，写死像素必然错（README #3）。
⚠️ **绝对不要用 `self._w` / `self._h` / `self._name` 存自己的尺寸和名字** ——
   这三个是 tkinter `Misc` 的内部属性（`_w` 是 widget 路径名、`_name` 是 widget
   名），`super().__init__()` 会把它们覆盖成字符串，之后再拿去 `int()` 就炸：
   `ValueError: invalid literal for int() with base 10: '.!toplevel.!frame.!canvas'`。
   本模块统一用 `_pw` / `_ph`（pixel width / height）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Callable

from . import iconlib, theme

#: `-transparentcolor` 用的魔法色。选洋红是因为它绝不可能出现在本项目的
#: 设计令牌里，不会误伤卡片自身的像素。
MAGIC = "#FF00FE"


def _parent_bg(master: tk.Misc) -> str:
    """取父容器的底色 —— 自绘控件要用它填四角，否则会露出方块。"""
    try:
        return str(master.cget("bg"))
    except (tk.TclError, AttributeError):
        return theme.N50


# ============================ 圆角按钮 ============================


class RoundButton(tk.Canvas):
    """圆角按钮。`tk.Button` 做不到圆角，所以整颗自绘。

    variant 决定配色：

        primary    品牌色实心（主操作：复制、开始截屏）
        secondary  白底细描边（次操作：保存）
        ghost      纯文字，悬停才有浅底（取消、关闭）
        danger     红字，悬停浅红底（清空历史）
    """

    #: (常态底, 悬停底, 按下底, 字色, 描边)
    VARIANTS = {
        "primary": (theme.B500, theme.B600, theme.B700, "#FFFFFF", None),
        #: 主控制面板的深绿主按钮（2026-10-10 参考图）。与 primary 区分开，
        #: 免得换掉结果窗口等已验收界面的按钮色。
        "brand": (theme.BRAND, theme.BRAND_HOVER, theme.BRAND_PRESS, "#FFFFFF", None),
        "secondary": (theme.N0, theme.N100, theme.N200, theme.N700, theme.N200),
        "ghost": (None, theme.N100, theme.N200, theme.N500, None),
        "danger": (None, "#FEE2E2", "#FECACA", theme.R500, None),
        "dark": (None, theme.D800, theme.D700, theme.D100, None),
    }

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        variant: str = "primary",
        icon: str | None = None,
        icon_size: int = 16,
        font=None,
        pad_x: int = 16,
        pad_y: int = 9,
        radius: int = theme.RADIUS_MD,
        width: int | None = None,
        height: int | None = None,
        tooltip: str | None = None,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        super().__init__(
            master,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self._text = text
        self._command = command
        self._variant = variant if variant in self.VARIANTS else "primary"
        self._icon_name = icon
        self._icon_size = icon_size
        self._font = font or theme.FONT_BODY
        self._pad_x = pad_x
        self._pad_y = pad_y
        self._radius = radius
        self._fixed_w = width
        self._fixed_h = height
        self._state = "normal"
        self._enabled = True
        self._tooltip = Tooltip(self, tooltip) if tooltip else None

        self._font_obj = tkfont.Font(font=self._font)
        self._resize()
        self._render()

        self.bind("<Enter>", lambda _e: self._set_state("hover"))
        self.bind("<Leave>", lambda _e: self._set_state("normal"))
        self.bind("<Button-1>", lambda _e: self._set_state("press"))
        self.bind("<ButtonRelease-1>", self._on_release)

    # ---------- 对外 ----------

    def set_text(self, text: str) -> None:
        self._text = text
        self._resize()
        self._render()

    def set_enabled(self, flag: bool) -> None:
        self._enabled = bool(flag)
        self._state = "normal" if flag else "disabled"
        self.configure(cursor="hand2" if flag else "arrow")
        self._render()

    def set_variant(self, variant: str) -> None:
        self._variant = variant if variant in self.VARIANTS else self._variant
        self._render()

    def set_icon(self, name: str | None) -> None:
        self._icon_name = name
        self._resize()
        self._render()

    def set_command(self, command: Callable[[], None] | None) -> None:
        """换掉点击动作（结果窗口的复制按钮要在「复制原文/译文」之间切换）。"""
        self._command = command

    def set_fixed_width(self, width: int | None) -> None:
        """固定宽度（`None` = 回到按内容自适应）。

        主控制面板用它把「开始截屏」撑满整行 —— Canvas 的 `pack(fill="x")` 只拉伸
        控件框、不会重画里面的圆角底图，所以必须显式把宽度算出来再重绘。
        """
        self._fixed_w = width
        self._resize()
        self._render()

    @property
    def text(self) -> str:
        return self._text

    # ---------- 内部 ----------

    def _colors(self):
        fill, hover, press, fg, outline = self.VARIANTS[self._variant]
        if not self._enabled:
            return (theme.N100, theme.N100, theme.N100, theme.N500, None)
        if self._state == "hover":
            return (hover, hover, press, fg, outline)
        if self._state == "press":
            return (press, press, press, fg, outline)
        return (fill, hover, press, fg, outline)

    def _resize(self) -> None:
        text_w = self._font_obj.measure(self._text) if self._text else 0
        icon_w = 0
        if self._icon_name:
            icon_w = theme.pxf(self._scale, self._icon_size) + theme.pxf(
                self._scale, theme.SPACE_2
            )
        width = self._fixed_w or (
            text_w + icon_w + 2 * theme.pxf(self._scale, self._pad_x)
        )
        height = self._fixed_h or (
            self._font_obj.metrics("linespace") + 2 * theme.pxf(self._scale, self._pad_y)
        )
        self.configure(width=max(1, int(width)), height=max(1, int(height)))

    def _set_state(self, state: str) -> None:
        if not self._enabled:
            return
        if self._state != state:
            self._state = state
            self._render()

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._set_state("hover" if inside else "normal")
        if inside and self._command is not None:
            self._command()

    def _render(self) -> None:
        self.delete("all")
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        fill, _hover, _press, fg, outline = self._colors()
        if fill is not None:
            self.create_image(
                0,
                0,
                anchor="nw",
                image=theme.rounded_photo(
                    self,
                    w,
                    h,
                    radius=theme.pxf(self._scale, self._radius),
                    fill=fill,
                    outline=outline,
                    outline_width=theme.pxf(self._scale, theme.STROKE_HAIRLINE)
                    if outline
                    else 0,
                    key=("btn", w, h, self._radius, fill, outline, self._scale),
                ),
            )

        icon_w = 0
        if self._icon_name:
            size = theme.pxf(self._scale, self._icon_size)
            icon_w = size + theme.pxf(self._scale, theme.SPACE_2)
        text_w = self._font_obj.measure(self._text) if self._text else 0
        start = (w - icon_w - text_w) / 2

        if self._icon_name:
            size = theme.pxf(self._scale, self._icon_size)
            self.create_image(
                start,
                h / 2,
                anchor="w",
                image=iconlib.icon_photo(self, self._icon_name, fg, size),
            )
        if self._text:
            self.create_text(
                start + icon_w,
                h / 2,
                anchor="w",
                text=self._text,
                font=self._font,
                fill=fg,
            )


# ============================ 图标按钮 ============================


class IconButton(tk.Canvas):
    """方形图标按钮（工具栏 / 钉图迷你工具条用）。

    常态**不画背景**（只画图标），悬停/激活时才贴一张圆角底 —— 这样图标按钮
    排在一起时不会有一堆方块边界，视觉上更干净。
    """

    def __init__(
        self,
        master: tk.Misc,
        name: str,
        command: Callable[[], None] | None = None,
        *,
        size: int = 20,
        pad: int = 7,
        radius: int = theme.RADIUS_SM,
        fg: str = theme.D100,
        fg_hover: str = "#FFFFFF",
        fg_active: str = "#FFFFFF",
        bg_hover: str = theme.D800,
        bg_active: str = theme.B500,
        active: bool = False,
        tooltip: str | None = None,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        side = theme.pxf(self._scale, size + pad * 2)
        super().__init__(
            master,
            width=side,
            height=side,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self._icon_name = name
        self._command = command
        self._size = size
        self._radius = radius
        self._fg = fg
        self._fg_hover = fg_hover
        self._fg_active = fg_active
        self._bg_hover = bg_hover
        self._bg_active = bg_active
        self._active = bool(active)
        self._hover = False
        self._enabled = True
        self._tooltip = Tooltip(self, tooltip) if tooltip else None

        self._render()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # ---------- 对外 ----------

    def set_active(self, flag: bool) -> None:
        if self._active != bool(flag):
            self._active = bool(flag)
            self._render()

    def set_icon(self, name: str, fg: str | None = None) -> None:
        self._icon_name = name
        if fg is not None:
            self._fg = fg
        self._render()

    def set_enabled(self, flag: bool) -> None:
        self._enabled = bool(flag)
        self.configure(cursor="hand2" if flag else "arrow")
        self._render()

    def set_tooltip(self, text: str | None) -> None:
        if self._tooltip is None:
            self._tooltip = Tooltip(self, text)
        else:
            self._tooltip.set_text(text)

    @property
    def active(self) -> bool:
        return self._active

    # ---------- 内部 ----------

    def _on_enter(self, _event: tk.Event) -> None:
        self._hover = True
        self._render()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover = False
        self._render()

    def _on_click(self, _event: tk.Event) -> None:
        if self._enabled and self._command is not None:
            self._command()

    def _render(self) -> None:
        self.delete("all")
        side = self.winfo_reqwidth()
        if self._active:
            self.create_image(
                0,
                0,
                anchor="nw",
                image=theme.rounded_photo(
                    self,
                    side,
                    side,
                    radius=theme.pxf(self._scale, self._radius),
                    fill=self._bg_active,
                    key=("ib", side, self._radius, self._bg_active, self._scale),
                ),
            )
            color = self._fg_active
        elif self._hover and self._enabled:
            self.create_image(
                0,
                0,
                anchor="nw",
                image=theme.rounded_photo(
                    self,
                    side,
                    side,
                    radius=theme.pxf(self._scale, self._radius),
                    fill=self._bg_hover,
                    key=("ib", side, self._radius, self._bg_hover, self._scale),
                ),
            )
            color = self._fg_hover
        else:
            color = self._fg if self._enabled else theme.D700

        size = theme.pxf(self._scale, self._size)
        self.create_image(
            side / 2,
            side / 2,
            anchor="center",
            image=iconlib.icon_photo(self, self._icon_name, color, size),
        )


# ============================ 分段控件 ============================


class SegmentedControl(tk.Canvas):
    """胶囊分段控件（设置窗口的「OCR 引擎 / 翻译模式 / 离线语言对」在用）。

    结果窗口的「原文 | 译文」曾经也用它，但主人 2026-10-08 第三轮要求改回
    **左侧竖排标签栏**（见 `VerticalTabBar`），所以现在只剩设置窗口在用。
    """

    def __init__(
        self,
        master: tk.Misc,
        items: list[str],
        command: Callable[[int], None] | None = None,
        *,
        value: int = 0,
        font=None,
        pad_x: int = 18,
        pad_y: int = 7,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._items = list(items)
        self._command = command
        self._value = int(value)
        self._font = font or theme.FONT_BODY
        self._font_obj = tkfont.Font(font=self._font)
        self._pad_x = pad_x
        self._pad_y = pad_y
        self._hover = -1

        self._cell_w = [
            self._font_obj.measure(text) + 2 * theme.pxf(self._scale, pad_x)
            for text in self._items
        ]
        self._seg_h = self._font_obj.metrics("linespace") + 2 * theme.pxf(
            self._scale, pad_y
        )
        super().__init__(
            master,
            width=sum(self._cell_w),
            height=self._seg_h,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self._render()
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _e: self._set_hover(-1))

    # ---------- 对外 ----------

    def set_value(self, index: int) -> None:
        if 0 <= index < len(self._items) and index != self._value:
            self._value = index
            self._render()

    @property
    def value(self) -> int:
        return self._value

    # ---------- 内部 ----------

    def _hit(self, x: int) -> int:
        cursor = 0
        for index, width in enumerate(self._cell_w):
            cursor += width
            if x < cursor:
                return index
        return len(self._items) - 1

    def _set_hover(self, index: int) -> None:
        if self._hover != index:
            self._hover = index
            self._render()

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._hit(event.x))

    def _on_click(self, event: tk.Event) -> None:
        index = self._hit(event.x)
        if index == self._value:
            return
        self._value = index
        self._render()
        if self._command is not None:
            self._command(index)

    def _render(self) -> None:
        self.delete("all")
        w = self.winfo_reqwidth()
        h = self._seg_h
        radius = theme.pxf(self._scale, theme.RADIUS_PILL)
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self, w, h, radius=radius, fill=theme.N100, key=("seg", w, h, self._scale)
            ),
        )

        cursor = 0
        for index, (text, width) in enumerate(zip(self._items, self._cell_w)):
            if index == self._value:
                self.create_image(
                    cursor + theme.pxf(self._scale, 2),
                    theme.pxf(self._scale, 2),
                    anchor="nw",
                    image=theme.rounded_photo(
                        self,
                        width - 2 * theme.pxf(self._scale, 2),
                        h - 2 * theme.pxf(self._scale, 2),
                        radius=radius,
                        fill=theme.N0,
                        outline=theme.N200,
                        outline_width=theme.pxf(self._scale, theme.STROKE_HAIRLINE),
                        key=("segitem", width, h, self._scale),
                    ),
                )
                color, font = theme.B500, (self._font[0], self._font[1], "bold")
            elif index == self._hover:
                color, font = theme.N700, self._font
            else:
                color, font = theme.N500, self._font
            self.create_text(
                cursor + width / 2,
                h / 2,
                text=text,
                font=font,
                fill=color,
            )
            cursor += width


# ============================ 左侧竖排标签栏 ============================


class VerticalTabBar(tk.Canvas):
    """竖排标签栏：文字**逐字换行**，各标签**均分整列高度**。

    用在结果窗口的「原文 / 译文」上，摆在文本框（输出栏）左边。

    这条路径来回走过三次，主人最终定的就是这一版：
      1. 最早是 `ttk.Notebook` —— 标签按文字宽度紧凑排在顶部，做不到均分高度；
      2. 改成自绘 `tk.Button` 竖排（README #13），整条栏从 212px 收到 63px；
      3. 视觉焕新时换成顶部胶囊分段控件（README #23）；
      4. **现在**（2026-10-08 第三轮）主人要求改回左侧竖排 —— 这次直接做成
         自绘的圆角卡片，和新的视觉体系一致。

    ⚠️ 均分高度靠 `pack(fill="both", expand=True)` 天然实现，但**本控件内部**是
       一个 Canvas，所以改成按 `<Configure>` 拿到的实际高度自己切分 —— 不写死
       高度，窗口怎么拉伸都均分。
    """

    def __init__(
        self,
        master: tk.Misc,
        items: list[str],
        command: Callable[[int], None] | None = None,
        *,
        value: int = 0,
        pad_x: int = 10,
        gap: int = 6,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._items = list(items)
        self._command = command
        self._value = int(value)
        self._font = theme.FONT_BODY
        self._font_bold = (theme.FONT_FAMILY, theme.FONT_BODY[1], "bold")
        self._pad_x = pad_x
        self._gap = gap
        self._hover = -1

        # 宽度按**最宽的那个字**定，再各留一份内边距。加粗字要一起量进来，
        # 否则选中时文字会被挤出去（竖排单字，宽度变化直接看得出来）。
        plain = tkfont.Font(font=self._font)
        bold = tkfont.Font(font=self._font_bold)
        widest = max(
            (max(plain.measure(ch), bold.measure(ch)) for text in self._items for ch in text),
            default=plain.measure("文"),
        )
        self._cell_w = widest + 2 * theme.pxf(self._scale, pad_x)

        super().__init__(
            master,
            width=self._cell_w,
            height=1,  # 真实高度交给外层 fill="y"，见 _render
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _e: self._set_hover(-1))

    # ---------- 对外 ----------

    def set_value(self, index: int) -> None:
        if 0 <= index < len(self._items) and index != self._value:
            self._value = index
            self._render()

    @property
    def value(self) -> int:
        return self._value

    # ---------- 内部 ----------

    def _cell_height(self) -> float:
        """单个标签的高度（均分剩余空间，扣掉标签之间的空隙）。"""
        count = len(self._items)
        if count == 0:
            return 0.0
        gap = theme.pxf(self._scale, self._gap)
        return max(1.0, (self.winfo_height() - gap * (count - 1)) / count)

    def _index_at(self, y: int) -> int:
        cell = self._cell_height()
        gap = theme.pxf(self._scale, self._gap)
        for index in range(len(self._items)):
            top = index * (cell + gap)
            if top <= y <= top + cell:
                return index
        return -1

    def _set_hover(self, index: int) -> None:
        if self._hover != index:
            self._hover = index
            self._render()

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._index_at(event.y))

    def _on_click(self, event: tk.Event) -> None:
        index = self._index_at(event.y)
        if index < 0 or index == self._value:
            return
        self._value = index
        self._render()
        if self._command is not None:
            self._command(index)

    def _render(self) -> None:
        self.delete("all")
        count = len(self._items)
        if count == 0:
            return
        s = self._scale
        width = max(1, self.winfo_width())
        cell = self._cell_height()
        gap = theme.pxf(s, self._gap)
        radius = theme.pxf(s, theme.RADIUS_MD)
        inset = theme.pxf(s, 1)

        for index, text in enumerate(self._items):
            top = index * (cell + gap)
            selected = index == self._value
            hovered = index == self._hover and not selected

            if selected:
                # 白底 + 细描边：内容区也是白底，看起来就是"这一页正被翻开"
                self.create_image(
                    inset,
                    top + inset,
                    anchor="nw",
                    image=theme.rounded_photo(
                        self,
                        max(1, width - 2 * inset),
                        max(1, int(cell) - 2 * inset),
                        radius=radius,
                        fill=theme.N0,
                        outline=theme.N200,
                        outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
                        key=("vtab", width, int(cell), s),
                    ),
                )
                color, font = theme.B500, self._font_bold
            elif hovered:
                self.create_image(
                    inset,
                    top + inset,
                    anchor="nw",
                    image=theme.rounded_photo(
                        self,
                        max(1, width - 2 * inset),
                        max(1, int(cell) - 2 * inset),
                        radius=radius,
                        fill=theme.N100,
                        key=("vtabhover", width, int(cell), s),
                    ),
                )
                color, font = theme.N700, self._font
            else:
                color, font = theme.N500, self._font

            self.create_text(
                width / 2,
                top + cell / 2,
                # 逐字换行 —— 竖排单字，这就是"文字竖排显示"
                text="\n".join(text),
                font=font,
                fill=color,
                justify="center",
            )

            if selected:
                # 左侧强调色竖条。用圆头竖线画，天然就是个胶囊，不用另做一张图。
                bar_h = max(1.0, cell * 0.36)
                self.create_line(
                    theme.pxf(s, 2),
                    top + (cell - bar_h) / 2,
                    theme.pxf(s, 2),
                    top + (cell + bar_h) / 2,
                    fill=theme.B500,
                    width=theme.pxf(s, 3),
                    capstyle="round",
                )


# ============================ Toast ============================


class Toast:
    """窗口内浮出的轻提示，替代 `messagebox.showinfo`。

    改造前复制成功、保存成功、翻译失败全靠原生弹窗 —— 一弹就打断操作，还得
    点一次"确定"。这里改成右下角浮出、两秒后自动淡出。

    ⚠️ 同一个父窗口同时只保留**一条** Toast，新的直接顶掉旧的：连续操作时
       堆一屏幕提示比弹窗更烦。
    ⚠️ 圆角外的透明靠 `-transparentcolor` 抠（精确匹配），所以卡片必须用
       `antialias=False` 的硬边圆角，否则边缘会留一圈杂色。
    """

    _KINDS = {
        "info": ("info", theme.D100),
        "success": ("confirm", theme.G500),
        "error": ("close", theme.R500),
        "warn": ("info", "#F59E0B"),
    }
    _active: dict[str, "Toast"] = {}

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        *,
        kind: str = "info",
        duration: int = 2200,
    ) -> None:
        self.parent = parent
        self.text = text
        self.kind = kind if kind in self._KINDS else "info"
        self.duration = duration
        self.win: tk.Toplevel | None = None
        self._job: str | None = None
        self._alpha = 0.0

    # ---------- 对外 ----------

    @classmethod
    def show(
        cls,
        parent: tk.Misc,
        text: str,
        *,
        kind: str = "info",
        duration: int = 2200,
    ) -> "Toast":
        key = str(parent)
        old = cls._active.pop(key, None)
        if old is not None:
            old.destroy()
        toast = cls(parent, text, kind=kind, duration=duration)
        cls._active[key] = toast
        toast._build()
        return toast

    def destroy(self) -> None:
        if self._job is not None:
            try:
                self.parent.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    # ---------- 内部 ----------

    def _build(self) -> None:
        parent = self.parent
        try:
            parent.update_idletasks()
        except tk.TclError:
            return
        scale = theme.scale(parent)
        icon_name, icon_color = self._KINDS[self.kind]

        font = tkfont.Font(font=theme.FONT_BODY)
        text_w = font.measure(self.text)
        pad = theme.pxf(scale, 14)
        icon_size = theme.pxf(scale, 16)
        gap = theme.pxf(scale, 8)
        height = font.metrics("linespace") + 2 * theme.pxf(scale, 11)
        width = pad * 2 + icon_size + gap + text_w
        radius = theme.pxf(scale, theme.RADIUS_MD)

        win = tk.Toplevel(parent)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        transparent = False
        try:
            win.configure(bg=MAGIC)
            win.attributes("-transparentcolor", MAGIC)
            transparent = True
        except tk.TclError:
            win.configure(bg=theme.D900)
        _ = transparent

        card = theme.rounded_image(
            width, height, radius, theme.D900, antialias=False
        )
        label = tk.Label(
            win,
            image=theme.photo(card, key=("toast", width, height, radius)),
            bd=0,
            highlightthickness=0,
            bg=MAGIC if win.cget("bg") == MAGIC else theme.D900,
        )
        label.pack()

        icon = tk.Label(
            win,
            image=iconlib.icon_photo(win, icon_name, icon_color, icon_size),
            bd=0,
            bg=theme.D900,
        )
        icon.place(x=pad, y=(height - icon_size) // 2)
        tk.Label(
            win,
            text=self.text,
            font=theme.FONT_BODY,
            fg=theme.D100,
            bg=theme.D900,
        ).place(x=pad + icon_size + gap, y=(height - font.metrics("linespace")) // 2)

        margin = theme.pxf(scale, 18)
        try:
            x = parent.winfo_rootx() + parent.winfo_width() - width - margin
            y = parent.winfo_rooty() + parent.winfo_height() - height - margin
        except tk.TclError:
            x = y = 0
        x = max(0, x)
        y = max(0, y)
        win.geometry(f"{width}x{height}+{x}+{y}")

        self._alpha = 0.0
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        self._fade(0.0, 0.96, 6, 14, then=self._hold)

    def _hold(self) -> None:
        self._job = self.parent.after(self.duration, self._fade_out)

    def _fade_out(self) -> None:
        self._fade(0.96, 0.0, 8, 18, then=self.destroy)

    def _fade(
        self,
        start: float,
        end: float,
        steps: int,
        interval: int,
        *,
        then: Callable[[], None] | None = None,
    ) -> None:
        def step(index: int) -> None:
            if self.win is None:
                return
            ratio = index / max(1, steps)
            value = start + (end - start) * ratio
            try:
                self.win.attributes("-alpha", value)
            except tk.TclError:
                return
            if index >= steps:
                if then is not None:
                    then()
                return
            self._job = self.parent.after(interval, lambda: step(index + 1))

        step(0)


# ============================ Tooltip ============================


class Tooltip:
    """自定义悬浮提示（tkinter 没有原生 tooltip）。

    改造前工具栏的提示文本是 `_ = tip` —— 也就是**根本没做**，纯图标零文字，
    学习成本极高。这里补上。
    """

    def __init__(
        self,
        widget: tk.Misc,
        text: str | None,
        *,
        delay: int = 420,
        side: str = "bottom",
    ) -> None:
        self.widget = widget
        self.text = text or ""
        self.delay = delay
        self.side = side
        self.win: tk.Toplevel | None = None
        self._job: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def set_text(self, text: str | None) -> None:
        self.text = text or ""
        if self.win is not None:
            self._hide()
            self._schedule()

    # ---------- 内部 ----------

    def _schedule(self, _event: tk.Event | None = None) -> None:
        if not self.text:
            return
        self._cancel()
        try:
            self._job = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._job = None

    def _cancel(self) -> None:
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except (tk.TclError, ValueError):
                pass
            self._job = None

    def _show(self) -> None:
        self._job = None
        if self.win is not None or not self.text:
            return
        widget = self.widget
        try:
            if not widget.winfo_exists():
                return
        except tk.TclError:
            return

        scale = theme.scale(widget)
        font = tkfont.Font(font=theme.FONT_TIP)
        text_w = font.measure(self.text)
        pad = theme.pxf(scale, 9)
        height = font.metrics("linespace") + 2 * theme.pxf(scale, 5)
        width = text_w + 2 * pad
        radius = theme.pxf(scale, theme.RADIUS_SM)

        win = tk.Toplevel(widget)
        self.win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.configure(bg=MAGIC)
            win.attributes("-transparentcolor", MAGIC)
            bg = MAGIC
        except tk.TclError:
            win.configure(bg=theme.D900)
            bg = theme.D900

        card = theme.rounded_image(width, height, radius, theme.D900, antialias=False)
        tk.Label(
            win,
            image=theme.photo(card, key=("tip", width, height, radius)),
            bd=0,
            highlightthickness=0,
            bg=bg,
        ).pack()
        tk.Label(
            win,
            text=self.text,
            font=theme.FONT_TIP,
            fg=theme.D100,
            bg=theme.D900,
        ).place(x=pad, y=(height - font.metrics("linespace")) // 2)

        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            ww = widget.winfo_width()
            wh = widget.winfo_height()
        except tk.TclError:
            self._hide()
            return
        x = wx + (ww - width) // 2
        gap = theme.pxf(scale, 6)
        if self.side == "top":
            y = wy - height - gap
        else:
            y = wy + wh + gap

        screen_w = widget.winfo_screenwidth()
        screen_h = widget.winfo_screenheight()
        x = max(4, min(x, screen_w - width - 4))
        if y + height > screen_h - 4:
            y = wy - height - gap
        y = max(4, y)
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _hide(self, _event: tk.Event | None = None) -> None:
        self._cancel()
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None


# ============================ 开关 ============================


class Switch(tk.Canvas):
    """胶囊开关（设置窗口用）。"""

    def __init__(
        self,
        master: tk.Misc,
        variable: tk.BooleanVar,
        command: Callable[[bool], None] | None = None,
        *,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._pw = theme.pxf(self._scale, 44)
        self._ph = theme.pxf(self._scale, 24)
        super().__init__(
            master,
            width=self._pw,
            height=self._ph,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self.variable = variable
        self._command = command
        self._render()
        self.bind("<Button-1>", self._toggle)

    def _toggle(self, _event: tk.Event | None = None) -> None:
        self.variable.set(not self.variable.get())
        self._render()
        if self._command is not None:
            self._command(self.variable.get())

    def refresh(self) -> None:
        self._render()

    def _render(self) -> None:
        self.delete("all")
        on = bool(self.variable.get())
        track = theme.B500 if on else theme.N300
        radius = self._ph // 2
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self, self._pw, self._ph, radius=radius, fill=track, key=("sw", track, self._ph)
            ),
        )
        knob = self._ph - theme.pxf(self._scale, 6)
        x = self._pw - knob - theme.pxf(self._scale, 3) if on else theme.pxf(self._scale, 3)
        self.create_image(
            x,
            theme.pxf(self._scale, 3),
            anchor="nw",
            image=theme.rounded_photo(
                self, knob, knob, radius=knob // 2, fill=theme.N0, key=("knob", knob)
            ),
        )


# ============================ 进度条 ============================


class ProgressBar(tk.Canvas):
    """圆角细进度条（离线模型下载用）。

    `models.download()` 自带 `progress(已下载, 总字节)` 回调，所以这里能给出
    **真实百分比**，而不是只写"下载中…"。
    """

    def __init__(
        self,
        master: tk.Misc,
        width: int = 220,
        height: int = 8,
        *,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._pw = theme.pxf(self._scale, width)
        self._ph = theme.pxf(self._scale, height)
        super().__init__(
            master,
            width=self._pw,
            height=self._ph,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
        )
        self._ratio = 0.0
        self._render()

    def set(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, float(ratio)))
        if abs(ratio - self._ratio) < 0.005 and ratio not in (0.0, 1.0):
            return
        self._ratio = ratio
        self._render()

    def _render(self) -> None:
        self.delete("all")
        radius = self._ph // 2
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self, self._pw, self._ph, radius=radius, fill=theme.N200, key=("pg", self._pw, self._ph)
            ),
        )
        if self._ratio <= 0:
            return
        fill_w = max(self._ph, int(self._pw * self._ratio))
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self,
                fill_w,
                self._ph,
                radius=radius,
                fill=theme.B500,
                key=("pgfill", fill_w, self._ph),
            ),
        )


# ============================ 徽章 ============================


class Badge(tk.Canvas):
    """状态徽章（"已安装 / 未安装"、热键状态）。"""

    _TONES = {
        "ok": (theme.G500, "#ECFDF5", theme.G600),
        "idle": (theme.N300, theme.N100, theme.N500),
        "warn": ("#F59E0B", "#FFFBEB", "#B45309"),
        "info": (theme.B500, theme.B50, theme.B600),
        #: 主控制面板的浅绿徽章（版本号 / 操作反馈，2026-10-10 参考图）
        "brand": (theme.G500, theme.BRAND_SOFT, theme.BRAND_TEXT),
    }

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        *,
        tone: str = "ok",
        dot: bool = True,
        icon: str | None = None,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._text = text
        self._tone = tone if tone in self._TONES else "ok"
        self._dot = dot
        #: 给了 `icon` 就用图标代替圆点（参考图的「✓ 识别完成」是勾，不是点）
        self._icon = icon
        self._font = tkfont.Font(font=theme.FONT_TIP)
        self._layout()
        super().__init__(
            master,
            width=self._pw,
            height=self._ph,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
        )
        self._render()

    def set(self, text: str, tone: str | None = None) -> None:
        self._text = text
        if tone is not None and tone in self._TONES:
            self._tone = tone
        self._layout()
        self.configure(width=self._pw, height=self._ph)
        self._render()

    def _layout(self) -> None:
        text_w = self._font.measure(self._text)
        if self._icon is not None:
            self._lead_size = theme.pxf(self._scale, 14)
        elif self._dot:
            self._lead_size = theme.pxf(self._scale, 7)
        else:
            self._lead_size = 0
        self._dot_size = self._lead_size
        gap = theme.pxf(self._scale, 6) if self._lead_size else 0
        self._pad = theme.pxf(self._scale, 9)
        self._pw = self._pad * 2 + self._lead_size + gap + text_w
        self._ph = self._font.metrics("linespace") + 2 * theme.pxf(self._scale, 4)

    def _render(self) -> None:
        self.delete("all")
        accent, fill, fg = self._TONES[self._tone]
        radius = self._ph // 2
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self,
                self._pw,
                self._ph,
                radius=radius,
                fill=fill,
                key=("badge", self._pw, self._ph, fill),
            ),
        )
        x = self._pad
        if self._icon is not None:
            self.create_image(
                x,
                self._ph // 2,
                anchor="w",
                image=iconlib.icon_photo(self, self._icon, accent, self._lead_size),
            )
            x += self._lead_size + theme.pxf(self._scale, 6)
        elif self._dot:
            self.create_image(
                x,
                self._ph // 2,
                anchor="w",
                image=theme.rounded_photo(
                    self,
                    self._dot_size,
                    self._dot_size,
                    radius=self._dot_size // 2,
                    fill=accent,
                    key=("dot", self._dot_size, accent),
                ),
            )
            x += self._dot_size + theme.pxf(self._scale, 6)
        self.create_text(
            x, self._ph // 2, anchor="w", text=self._text, font=theme.FONT_TIP, fill=fg
        )


# ============================ 热键键帽 ============================


class HotkeyCaps(tk.Canvas):
    """热键显示：浅底圆角容器 + 每个键一枚键帽 + 「+」分隔（2026-10-10 参考图）。

    改造前热键是一颗普通按钮、里面写 "ctrl+alt+s" 整串 —— 既不像"按键"，
    也看不出到底要按几个键。换成键帽后一眼就能读成"按 Ctrl，再按 D"。

    ⚠️ 点它等同于点旁边的「点击录制」：参考图里两条入口并存，行为一致。
    """

    def __init__(
        self,
        master: tk.Misc,
        combo: str,
        command: Callable[[], None] | None = None,
        *,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._combo = combo
        self._command = command
        self._font = tkfont.Font(font=theme.FONT_BODY)
        self._plus_font = tkfont.Font(font=theme.FONT_TIP)
        super().__init__(
            master,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
            cursor="hand2" if command is not None else "",
        )
        self._resize()
        self._render()
        if command is not None:
            self.bind("<Button-1>", lambda _e: command())

    # ---------- 对外 ----------

    def set_text(self, combo: str) -> None:
        self._combo = combo
        self._resize()
        self._render()

    # ---------- 内部 ----------

    def _tokens(self) -> list[str]:
        """`ctrl+alt+s` → `['Ctrl', 'Alt', 'S']`；录制中的提示语（无 `+`）原样返回。"""
        raw = (self._combo or "").strip()
        if "+" not in raw:
            return [raw] if raw else []
        out: list[str] = []
        for part in raw.split("+"):
            token = part.strip()
            if not token:
                continue
            out.append(token.upper() if len(token) == 1 else token.capitalize())
        return out

    def _resize(self) -> None:
        s = self._scale
        self._cap_h = theme.pxf(s, 26)
        self._cap_pad_x = theme.pxf(s, 11)
        self._box_pad_x = theme.pxf(s, 9)
        self._box_pad_y = theme.pxf(s, 5)
        self._gap = theme.pxf(s, 6)

        tokens = self._tokens()
        self._caps_w = [
            max(self._cap_h, self._font.measure(t) + 2 * self._cap_pad_x) for t in tokens
        ]
        self._plus_w = self._plus_font.measure("+")
        joins = max(0, len(tokens) - 1)
        content = sum(self._caps_w) + joins * (self._plus_w + 2 * self._gap)
        self._pw = max(1, content + 2 * self._box_pad_x)
        self._ph = self._cap_h + 2 * self._box_pad_y
        self.configure(width=int(self._pw), height=int(self._ph))

    def _render(self) -> None:
        self.delete("all")
        s = self._scale
        tokens = self._tokens()

        # 容器：浅灰圆角底（键帽组的外框）
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self,
                self._pw,
                self._ph,
                radius=theme.pxf(s, theme.RADIUS_MD),
                fill=theme.N50,
                outline=theme.N200,
                outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
            ),
        )

        x = self._box_pad_x
        cy = self._ph / 2
        cap_r = theme.pxf(s, theme.RADIUS_SM)
        for index, token in enumerate(tokens):
            cw = self._caps_w[index]
            self.create_image(
                x,
                self._box_pad_y,
                anchor="nw",
                image=theme.rounded_photo(
                    self,
                    cw,
                    self._cap_h,
                    radius=cap_r,
                    fill=theme.N0,
                    outline=theme.N300,
                    outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
                ),
            )
            # 底边加重一道 —— 键盘按键的"侧面"，让键帽立起来（参考图里很明显）
            self.create_line(
                x + cap_r,
                self._box_pad_y + self._cap_h,
                x + cw - cap_r,
                self._box_pad_y + self._cap_h,
                fill=theme.N300,
                width=theme.pxf(s, theme.STROKE_HAIRLINE),
            )
            self.create_text(
                x + cw / 2, cy, text=token, font=theme.FONT_BODY, fill=theme.N700
            )
            x += cw
            if index < len(tokens) - 1:
                x += self._gap
                self.create_text(
                    x + self._plus_w / 2,
                    cy,
                    text="+",
                    font=theme.FONT_TIP,
                    fill=theme.N500,
                )
                x += self._plus_w + self._gap


# ============================ 圆角输入框 ============================


class Entry(tk.Canvas):
    """圆角输入框。

    `tk.Entry` 本身是直角的，塞进这套圆角界面里很扎眼，所以外面套一层 Canvas
    画圆角底 + 描边，真正的 Entry 用 `create_window` 嵌在中间。聚焦时描边换成
    品牌色、加粗一档 —— 这是 tkinter 原生 Entry 给不了的反馈。
    """

    def __init__(
        self,
        master: tk.Misc,
        *,
        textvariable: tk.StringVar | None = None,
        width: int = 200,
        height: int = 34,
        show: str | None = None,
        scale: float | None = None,
    ) -> None:
        self._scale = scale if scale is not None else theme.scale(master)
        self._bg = _parent_bg(master)
        self._pw = theme.pxf(self._scale, width)
        self._ph = theme.pxf(self._scale, height)
        super().__init__(
            master,
            width=self._pw,
            height=self._ph,
            highlightthickness=0,
            bd=0,
            bg=self._bg,
        )
        self.var = textvariable if textvariable is not None else tk.StringVar()
        self._focus = False
        self._masked = show is not None
        self._render_bg()
        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            font=theme.FONT_BODY,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=theme.N0,
            fg=theme.N900,
            insertbackground=theme.B500,
            show=show,
        )
        self.create_window(
            theme.pxf(self._scale, 10),
            self._ph / 2,
            anchor="w",
            window=self.entry,
            width=max(1, self._pw - theme.pxf(self._scale, 20)),
            height=theme.pxf(self._scale, 22),
        )
        self.entry.bind("<FocusIn>", lambda _e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda _e: self._set_focus(False))

    def set_masked(self, masked: bool) -> None:
        """切换密文 / 明文（配合旁边的小眼睛按钮）。

        ⚠️ 只改底层 `tk.Entry` 的 `show`，**不动 StringVar** —— 内容一字不变，
           切换时既不丢字符、也不会触发 trace 回调。
        """
        self._masked = masked
        self.entry.configure(show="●" if masked else "")

    @property
    def masked(self) -> bool:
        return self._masked

    def _set_focus(self, flag: bool) -> None:
        if self._focus != flag:
            self._focus = flag
            self._render_bg()

    def _render_bg(self) -> None:
        self.delete("bg")
        hairline = theme.pxf(self._scale, theme.STROKE_HAIRLINE)
        self.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                self,
                self._pw,
                self._ph,
                radius=theme.pxf(self._scale, theme.RADIUS_SM),
                fill=theme.N0,
                outline=theme.B500 if self._focus else theme.N200,
                outline_width=hairline * (2 if self._focus else 1),
                key=("entry", self._pw, self._ph, self._focus, self._scale),
            ),
            tags="bg",
        )
        self.tag_lower("bg")


# ============================ 辅助 ============================


def hline(master: tk.Misc, *, color: str = theme.N200, pad: int = 0) -> tk.Frame:
    """1px 分隔线。"""
    line = tk.Frame(master, bg=color, height=1)
    _ = pad
    return line
