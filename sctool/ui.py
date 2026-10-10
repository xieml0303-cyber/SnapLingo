"""tkinter 界面组件。

    ResultWindow   展示截图 / 原文 / 译文，提供复制与保存
    ControlPanel   主控制面板：全局热键、开始截屏、设置入口

截屏的框选与标注界面在 overlay.py，不在这里。

⚠️ DPI：**不要写死像素**，所有自绘尺寸都过 `theme.scale()` / `theme.pxf()`。
进程声明 DPI 感知后，tkinter 的 point 字号会按系统 DPI 缩放（例如 200% 缩放下
15pt 约 40 像素高），窗口尺寸不跟着放大会把文字挤成多行、标题被截断。
⚠️ 本机 DPI 会变（README「已知限制」记过一次：2880×1800/200% → 1920×1080/100%），
排查布局问题前先量一次当前 DPI，别照抄旧结论。

⚠️ 布局顺序不能乱：底部按钮栏必须**先 pack 并贴底**。Tk 按 pack 顺序分配空间，
最后 pack 的 widget 在窗口偏矮时会被挤成 0 高 —— 表现就是"原文/译文一片空白、
底下一排按钮全不见"（README #11 记录过这个坑）。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, font as tkfont, ttk
from typing import Callable

from PIL import Image, ImageTk

from . import APP_TITLE, __version__, icons, storage, theme, widgets

FONT = theme.FONT_BODY
FONT_BOLD = (theme.FONT_FAMILY, 10, "bold")
FONT_TITLE = theme.FONT_TITLE
FONT_SMALL = theme.FONT_TIP

BG = theme.N50
ACCENT = theme.B500


def dpi_scale(widget: tk.Misc) -> float:
    """当前显示器的缩放比例（1.0 = 100%，本机为 2.0）。"""
    return theme.scale(widget)


#: Tk 的 keysym → keyboard 库认识的按键名（两边命名不一样，得翻译一层）
KEYSYM_MAP = {
    "return": "enter",
    "kp_enter": "enter",
    "escape": "esc",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "prior": "page up",
    "next": "page down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "print": "print screen",
    "pause": "pause",
    "minus": "-",
    "equal": "=",
    "bracketleft": "[",
    "bracketright": "]",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "grave": "`",
}

#: 光按修饰键不算一个热键组合，得继续等真正的按键
MODIFIER_KEYSYMS = {
    "control_l",
    "control_r",
    "shift_l",
    "shift_r",
    "alt_l",
    "alt_r",
    "super_l",
    "super_r",
    "meta_l",
    "meta_r",
    "caps_lock",
    "num_lock",
    "scroll_lock",
    "iso_level3_shift",
}


def combo_from_event(event: tk.Event) -> str | None:
    """把 Tk 的按键事件拼成 `keyboard` 库认识的组合键字符串。

    主人 2026-10-08 要求："设置全局热键…居然要手打快捷键，改成映射" ——
    也就是点一下热键框、直接按组合键，程序自己认出来。

    返回 `None` 表示"只按了修饰键"，还没构成完整组合，调用方应该继续等。

    ⚠️ Alt 在 Windows 的 Tk 里是 `0x20000`。
    **不要**顺手把 `0x0008` 也当成 Alt —— 实测这个位在 Windows 上**恒置**
    （单独按一个 `d`，state 就已经是 `0x0008` 了），把它算进去会把 `Ctrl+D`
    认成 `ctrl+alt+d`（主人 2026-10-08 就这么踩到的）。
    """
    state = event.state
    parts: list[str] = []
    if state & 0x0004:
        parts.append("ctrl")
    if state & 0x20000:
        parts.append("alt")
    if state & 0x0001:
        parts.append("shift")

    lower = event.keysym.lower()
    if lower in MODIFIER_KEYSYMS:
        return None
    parts.append(KEYSYM_MAP.get(lower, lower))
    return "+".join(parts)


def work_area(widget: tk.Misc) -> tuple[int, int, int, int]:
    """主显示器的**工作区**（去掉任务栏），返回 (left, top, right, bottom)。

    ⚠️ 居中必须按工作区算，不能按整屏 —— 实测按整屏居中时窗口底边会被任务栏
    切掉，底部那排按钮（尤其「关闭」）就点不到了。
    """
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        SPI_GETWORKAREA = 0x0030
        rect = RECT()
        if ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        ):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:  # noqa: BLE001 - 拿不到就退回整屏
        pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def window_frame_size(
    widget: tk.Misc, client_w: int, client_h: int
) -> tuple[int, int]:
    """按窗口样式算出**含边框/标题栏**的总尺寸，**不用先把窗口摆出来**。

    用 Win32 `AdjustWindowRectEx`（系统给的标准算法）：给它一个客户区矩形，
    它把边框和标题栏加回去。

    ⚠️ 别改成"先 geometry 摆一次、GetWindowRect 量、再摆第二次"—— 那样主人会
    看到窗口先闪到别处再跳过来（实测反馈："有二次定位的问题，希望一次就能居中
    显示不用调整位置"）。
    """
    try:
        import ctypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        user32 = ctypes.windll.user32
        hwnd = int(widget.frame(), 16)
        GWL_STYLE, GWL_EXSTYLE = -16, -20
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        rect = RECT(0, 0, client_w, client_h)
        if user32.AdjustWindowRectEx(ctypes.byref(rect), style, False, exstyle):
            return rect.right - rect.left, rect.bottom - rect.top
    except Exception:  # noqa: BLE001
        pass
    return client_w, client_h


def fit_image(image: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """等比缩放到不超过 max_w × max_h（只缩不放）。"""
    ratio = min(max_w / image.width, max_h / image.height, 1.0)
    if ratio >= 1.0:
        return image.copy()
    return image.resize(
        (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
        Image.LANCZOS,
    )


class ResultWindow:
    """展示截图、原文与译文。

    布局：预览图 → 内容区（**左侧竖排标签栏** + 右侧文本框）→ 底部按钮栏。

    页签这条路径来回走过三次（详见 `widgets.VerticalTabBar` 的说明）：
    `ttk.Notebook` → 自绘竖排按钮 → 顶部胶囊分段控件 → **回到左侧竖排**
    （主人 2026-10-08 第三轮明确要求："标签页放在输出栏的左边，文字竖排显示"）。

    其余改造前后对比：
        预览图   1px 硬黑框直角                        → 圆角 + 细边 + 轻投影
        按钮     三颗一样重的深灰方块                  → 主/次/幽灵三级层次
        反馈     原生 messagebox 弹窗                  → 右下角自动淡出的 Toast
        加载态   干巴巴一行"翻译中…"                   → 带动画的省略号
    """

    def __init__(
        self,
        master: tk.Misc,
        image: Image.Image,
        on_translate: Callable[[], None] | None = None,
        title: str = "截图结果",
        topmost: bool = False,
        on_notice: Callable[[str], None] | None = None,
    ) -> None:
        self.master = master
        self.image = image
        self.on_translate = on_translate
        #: 轻量提示（app 传进来写日志用）。保存图片成功**不弹窗**，只留一条记录。
        self.on_notice = on_notice
        self.scale = dpi_scale(master)

        self.win = tk.Toplevel(master)
        self.win.title(title)
        # 结果窗口也要**按尺寸精确**设图标：只靠 iconbitmap 的默认图标，大小两档
        # 会拿到同一个 32×32，标题栏缩一半就糊了（见 icons._set_exact_icons）。
        icons.apply_tk_icon(self.win)
        self.win.minsize(int(620 * self.scale), int(480 * self.scale))
        self.win.geometry(f"{int(840 * self.scale)}x{int(660 * self.scale)}")
        self.win.configure(bg=BG)
        if topmost:
            # 遮罩整屏置顶，结果窗口不跟着置顶就会被压在下面看不见。
            # set_topmost 内部会重新居中（Tk 改 topmost 会把位置重置回 +0+0）。
            self.set_topmost(True)
        else:
            self._center_on_screen()

        self._build_preview()

        # 底部按钮栏要**先** pack 并贴底：Tk 按 pack 顺序分配空间，最后 pack 的
        # widget 在窗口偏矮时会被挤成 0 高 —— 表现就是"原文/译文一片空白、
        # 底下一排按钮全不见"。先钉住它，再让中间的内容区去吃掉剩余空间。
        bar = tk.Frame(self.win, bg=BG)
        self.bar = bar
        bar.pack(
            side="bottom",
            fill="x",
            padx=int(14 * self.scale),
            pady=(0, int(14 * self.scale)),
        )

        # 内容区：**左边**竖排标签栏（「原/文」「译/文」）+ 右边文本框。
        # 主人 2026-10-08 第三轮明确要求："标签页放在输出栏的左边，文字竖排显示"。
        body = tk.Frame(self.win, bg=BG)
        body.pack(
            fill="both",
            expand=True,
            padx=int(14 * self.scale),
            pady=(0, int(10 * self.scale)),
        )
        self.tabs = widgets.VerticalTabBar(
            body, ["原文", "译文"], self.select_tab, value=0, scale=self.scale
        )
        self.tabs.pack(side="left", fill="y", padx=(0, int(6 * self.scale)))
        self._build_content(body)

        self._pages: list[tk.Frame] = []
        #: 当前显示的是哪一页（0=原文 1=译文）
        self._current = 0
        #: 自动翻译的状态：正在跑 / 上一次成功了没有。
        #: 成功过就不再重复翻（来回切页反复翻译会很烦）；没翻过或翻失败则允许
        #: 再点「译文」重试 —— 底部那颗「翻译」按钮已按主人要求去掉，
        #: 这里是唯一的翻译入口，必须留一条重试的路。
        self._auto_running = False
        self._auto_ok = False
        self._loading_job: str | None = None
        self._loading_step = 0
        self._loading_widget: tk.Text | None = None
        self._loading_base = ""

        self.text_widget = self._add_page("原文")
        self.trans_widget = self._add_page("译文")

        # 按钮分三级：主操作（复制）实心品牌色，次操作（保存）白底描边，
        # 「关闭」是幽灵按钮靠右。改造前三颗一样重的深灰方块，看不出主次。
        self.copy_button = widgets.RoundButton(
            bar,
            "复制原文",
            self.copy_text,
            variant="primary",
            icon="copy",
            scale=self.scale,
        )
        self.copy_button.pack(side="left", padx=(0, int(8 * self.scale)))
        widgets.RoundButton(
            bar,
            "保存图片",
            self.save_image,
            variant="secondary",
            icon="save",
            scale=self.scale,
        ).pack(side="left")
        widgets.RoundButton(
            bar, "关闭", self.win.destroy, variant="ghost", scale=self.scale
        ).pack(side="right")

        # ⚠️ 落页签必须放在按钮建好之后：select_tab 要按当前页刷新那颗复制按钮
        self.select_tab(0)

    # ---------- 构建 ----------

    def _build_preview(self) -> None:
        """截图预览：圆角 + 细描边 + 轻投影（原来是 `bd=1, relief="solid"` 硬黑框）。"""
        fitted = fit_image(
            self.image, int(780 * self.scale), int(190 * self.scale)
        )
        card, pad = theme.framed_image(
            fitted,
            theme.pxf(self.scale, theme.RADIUS_MD),
            outline=theme.N200,
            outline_width=max(1, int(round(self.scale))),
            shadow=theme.SHADOW_CARD,
        )
        self._preview_photo = theme.photo(
            card, key=("preview", fitted.size, self.scale)
        )
        tk.Label(self.win, image=self._preview_photo, bd=0, bg=BG).pack(
            padx=int(14 * self.scale), pady=(int(14 * self.scale), int(8 * self.scale))
        )
        _ = pad

    def _build_content(self, parent: tk.Misc) -> None:
        """内容区：Canvas 铺一张圆角白卡片，文本页作为 canvas window 放进去。

        `parent` 是"标签栏 + 内容区"那一行容器，卡片就摆在标签栏右边。

        ⚠️ 为什么不用 `tk.Frame(bg="white")` 直接当容器：Frame 做不出圆角。
        而 `tk.Text` 也不能透明，所以必须让 Text 坐在圆角卡片**内部**（内缩 1px
        的描边宽度），圆角才露得出来。
        """
        holder = tk.Canvas(parent, highlightthickness=0, bd=0, bg=BG)
        holder.pack(side="left", fill="both", expand=True)
        self._holder = holder
        self._inner = tk.Frame(holder, bg=theme.N0)
        self._inner_window = holder.create_window(0, 0, anchor="nw", window=self._inner)
        holder.bind("<Configure>", self._on_holder_resize)

    def _on_holder_resize(self, event: tk.Event) -> None:
        """内容区尺寸变了：重铺圆角卡片，并同步内部 Frame 的可用尺寸。"""
        width, height = max(1, event.width), max(1, event.height)
        inset = max(1, int(round(self.scale)))
        holder = self._holder
        holder.delete("cardbg")
        holder.create_image(
            0,
            0,
            anchor="nw",
            image=theme.rounded_photo(
                holder,
                width,
                height,
                radius=theme.pxf(self.scale, theme.RADIUS_MD),
                fill=theme.N0,
                outline=theme.N200,
                outline_width=inset,
                key=("content", width, height, self.scale),
            ),
            tags="cardbg",
        )
        holder.tag_lower("cardbg")
        holder.coords(self._inner_window, inset, inset)
        holder.itemconfigure(
            self._inner_window, width=max(1, width - 2 * inset), height=max(1, height - 2 * inset)
        )

    def _add_page(self, title: str) -> tk.Text:
        """建一页：内容区里一个文本框（两页共用同一块圆角卡片）。"""
        page = tk.Frame(self._inner, bg=theme.N0)
        widget = tk.Text(
            page,
            wrap="word",
            font=FONT,
            # ⚠️ 必须显式给个小 height：tk.Text 默认 24 行，在 200% 缩放下会把
            # 请求高度撑到 600+ 像素，窗口一矮就把底部按钮栏挤成 0 高
            # （表现：原文/译文一片空白、按钮全不见）。高度交给 pack 的 expand 决定。
            height=1,
            undo=False,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=theme.N0,
            fg=theme.N700,
            insertbackground=theme.B500,
            selectbackground=theme.B100,
            padx=int(10 * self.scale),
            pady=int(8 * self.scale),
        )
        scroll = ttk.Scrollbar(page, command=widget.yview)
        widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        widget.pack(fill="both", expand=True)

        self._pages.append(page)
        _ = title
        return widget

    # ---------- 窗口行为 ----------

    def set_topmost(self, flag: bool) -> None:
        """切换置顶。遮罩关掉之后就该取消，免得永远压着别的窗口。

        ⚠️ Tk 在 Windows 上改 `-topmost` 会把窗口位置**重置回 +0+0**
        （实测：设完 topmost，geometry 从 `+587+164` 变成 `+0+0`，窗口跳到左上角）。
        所以每次改完都要重新居中一次 —— 主程序在遮罩退出时就会调这个方法，
        不补这一步，主人看到的结果窗口会歪在屏幕左上角。
        """
        try:
            self.win.attributes("-topmost", bool(flag))
        except tk.TclError:
            return
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        """把窗口摆到**屏幕工作区正中**。

        主人 2026-10-08 要求："调出来的截屏结果窗口强制居中显示"。

        以前是"避开选区/工具栏"摆放 —— 那是为了点完「识」还能接着点工具栏上的
        「译」。现在点「识」/「译」就退出框选了（见 README #14），工具栏根本不在，
        避让没有意义，居中反而最好找。

        ⚠️ 用**工作区**（去掉任务栏）而不是整屏：按整屏居中的话窗口底边会被任务栏
        切掉，「关闭」按钮就点不到了（实测踩过：窗口底边 1810 > 屏幕 1800，
        正对照的点击直接落进了任务栏）。
        """
        width = int(840 * self.scale)
        height = int(660 * self.scale)
        min_width = int(620 * self.scale)
        min_height = int(480 * self.scale)
        margin = int(24 * self.scale)

        left, top, right, bottom = work_area(self.win)
        avail_w = right - left
        avail_h = bottom - top

        # 工作区装不下就压到装得下（但不低于 min，否则内容会被挤没）
        width = max(min_width, min(width, avail_w - 2 * margin))
        height = max(min_height, min(height, avail_h - 2 * margin))

        # Toplevel 一创建就带个默认位置，而且这时底层 HWND 可能还没建好
        # （AdjustWindowRectEx 会失败、退化成客户区尺寸）。先藏起来、把 HWND
        # 逼出来，算好位置**一次**摆到位，再显示 —— 主人看不到任何中间状态。
        was_visible = bool(self.win.winfo_viewable())
        if not was_visible:
            self.win.withdraw()
        self.win.update_idletasks()

        # ⚠️ geometry 的 W×H 是**客户区**尺寸，而 X/Y 是**含边框**的窗口左上角 ——
        #    两个基准不一样，直接按客户区居中会让窗口整体偏右下（实测偏 (13,58)，
        #    正好是边框宽和标题栏高）。含边框的总尺寸用 `AdjustWindowRectEx` 算，
        #    不要"先摆一次、量一次、再摆第二次"（那样会看到窗口闪一下再跳）。
        total_w, total_h = window_frame_size(self.win, width, height)
        x = left + (avail_w - total_w) // 2
        y = top + (avail_h - total_h) // 2

        # minsize 会顶住压缩，得一起放宽
        self.win.minsize(min_width, min(min_height, height))
        self.win.geometry(f"{width}x{height}+{x}+{y}")

        if not was_visible:
            self.win.deiconify()

    def raise_window(self) -> None:
        """把窗口提到同层最上面（不置顶）。

        遮罩退出后结果窗口会取消置顶，这时可能被别的窗口盖住 —— 主人刚截完图
        却看不到结果，太别扭了。这里抢一次可见性。
        """
        try:
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    # ---------- 页签 ----------

    def select_tab(self, index: int, *, auto_translate: bool = True) -> None:
        """切到第 index 页。切到「译文」会顺手把翻译跑起来。

        `auto_translate=False` 供 `set_translation()` 内部调用：它写回译文本身，
        再触发一次翻译就会变成"翻译→写回→再翻译"的无限递归。
        """
        if not 0 <= index < len(self._pages):
            return
        self._current = index
        for i, page in enumerate(self._pages):
            if i == index:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
        if hasattr(self, "tabs"):
            self.tabs.set_value(index)
        # 复制按钮跟着页签走：「复制原文」和「复制译文」永远只出现一个
        if index == 1:
            self.copy_button.set_text("复制译文")
            self.copy_button.set_command(self.copy_translation)
        else:
            self.copy_button.set_text("复制原文")
            self.copy_button.set_command(self.copy_text)
        if index == 1 and auto_translate:
            self._maybe_auto_translate()

    def _maybe_auto_translate(self) -> None:
        """主人点「译文」＝要译文，那就自动把翻译跑起来。

        点了「译文」却看到一个空页面，看起来就跟"翻译不生效"一模一样 ——
        所以这里自动跑一次。

        三种情况直接跳过：**正在翻译中**（别重复发起）、**上次已经翻成功**
        （来回切页不用反复翻）、还没有文字。上次**失败**则放行 —— 底部那颗
        「翻译」按钮已经按主人要求去掉了，这里是唯一的翻译入口。
        """
        if self.on_translate is None or self._auto_running or self._auto_ok:
            return
        text = self.get_text()
        if not text.strip() or "识别中" in text:
            return
        self._auto_running = True
        try:
            self.on_translate()
        except Exception:
            # 起不来就把"进行中"撤掉，主人还能再点一次重试
            self._auto_running = False
            raise

    # ---------- 加载动画 ----------

    def _start_loading(self, widget: tk.Text, base: str) -> None:
        """在目标文本框里跑"翻译中 . .. ..."的动画。

        改造前只有一行干巴巴的"翻译中，请稍候…"—— 长文本翻译要好几秒，
        没有任何动效时看着就像卡死了。
        """
        self._stop_loading()
        self._loading_widget = widget
        self._loading_base = base
        self._loading_step = 0
        self._tick_loading()

    def _tick_loading(self) -> None:
        widget = self._loading_widget
        if widget is None:
            return
        try:
            widget.delete("1.0", "end")
            widget.insert("1.0", self._loading_base + "." * (self._loading_step % 4))
        except tk.TclError:
            return
        self._loading_step += 1
        try:
            self._loading_job = self.win.after(380, self._tick_loading)
        except tk.TclError:
            self._loading_job = None

    def _stop_loading(self) -> None:
        if self._loading_job is not None:
            try:
                self.win.after_cancel(self._loading_job)
            except (tk.TclError, ValueError):
                pass
            self._loading_job = None
        self._loading_widget = None

    # ---------- 内容 ----------

    def set_text(self, text: str) -> None:
        self._stop_loading()
        self.text_widget.delete("1.0", "end")
        self.text_widget.insert("1.0", text)
        # 主人可能已经先切到「译文」页等着了；识别一落地就把翻译跑起来
        if self._current == 1:
            self._maybe_auto_translate()

    def set_loading_text(self, base: str = "识别中") -> None:
        """原文页的加载态（OCR 首次加载模型可能要好几秒）。"""
        self._start_loading(self.text_widget, base)

    def set_translation(self, text: str, *, ok: bool = True) -> None:
        """写回译文页。`ok=False` 表示这次翻译失败 —— 那就不算"翻好了"，
        主人再点一次「译文」标签还能重试。"""
        self._stop_loading()
        self._auto_running = False
        self._auto_ok = ok
        self.trans_widget.delete("1.0", "end")
        self.trans_widget.insert("1.0", text)
        # ⚠️ 必须 auto_translate=False：写回译文本身会切到译文页，若再触发一次
        # 翻译，失败时就成了"翻译 → 写回 → 再翻译"的无限递归（实测 calls 一路涨）。
        self.select_tab(1, auto_translate=False)

    def set_translation_loading(self) -> None:
        self._start_loading(self.trans_widget, "翻译中")

    def get_text(self) -> str:
        return self.text_widget.get("1.0", "end").strip()

    def get_translation(self) -> str:
        return self.trans_widget.get("1.0", "end").strip()

    # ---------- 动作 ----------

    def copy_text(self) -> None:
        self._copy(self.get_text(), "原文")

    def copy_translation(self) -> None:
        self._copy(self.get_translation(), "译文")

    def _copy(self, content: str, label: str) -> None:
        """复制到剪贴板。

        改造前是 `messagebox.showinfo` —— 一弹就打断操作、还得点一次"确定"，
        而同一个窗口里"保存成功"已经改成静默写日志了，两套反馈风格自相矛盾。
        现在统一成右下角 Toast。
        """
        if not content:
            widgets.Toast.show(self.win, f"没有可复制的{label}", kind="warn")
            return
        try:
            import pyperclip

            pyperclip.copy(content)
        except Exception:  # noqa: BLE001 - 退回 tkinter 自带剪贴板
            try:
                self.win.clipboard_clear()
                self.win.clipboard_append(content)
            except tk.TclError:
                widgets.Toast.show(self.win, "复制失败", kind="error")
                return
        widgets.Toast.show(self.win, f"{label}已复制到剪贴板", kind="success")

    def save_image(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="保存图片",
            defaultextension=".png",
            filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg")],
            initialfile=f"截图-{storage.timestamp_name()}",
            initialdir=str(storage.paths.default_save_dir()),
        )
        if not path:
            return
        try:
            self.image.save(path)
        except OSError as exc:
            widgets.Toast.show(self.win, f"保存失败：{exc}", kind="error")
            return
        # 主人 2026-10-08 要求：保存成功**不用弹窗告知**。现在给一条自动淡出的
        # Toast（不是弹窗），既能确认又不用点"确定"。
        widgets.Toast.show(self.win, "图片已保存", kind="success")
        if self.on_notice is not None:
            self.on_notice(f"图片已保存：{path}")


def _pretty_hotkey(combo: str) -> str:
    """`ctrl+alt+s` → `Ctrl+Alt+S`（状态行那句「按 … 开始」用这个写法）。"""
    parts = [p.strip() for p in (combo or "").split("+") if p.strip()]
    return "+".join(p.upper() if len(p) == 1 else p.capitalize() for p in parts)


class ControlPanel:
    """主控制面板（2026-10-10 按参考图重做布局）。

    四行结构：

        品牌行   [logo]  SnapLingo  [v0.1.0]         [✓ 识别完成]
                        ● 已就绪 · 按 Ctrl+D 开始
        热键行   全局热键   [Ctrl] + [D]        [点击录制]
        操作行   [ ⌗ 开始截屏 ..................... ]   [⚙]

    ⚠️ 配色只走 `theme.BRAND*`（深绿）。结果窗口 / 遮罩 / 设置窗口仍是蓝色 B500 系
       —— 那些界面已过八轮验收，本轮不动（主人只要求改主窗口）。
    """

    #: 面板**最小**逻辑宽度（@1x）。实际宽度由内容决定 —— 取三行里最宽的一行加上
    #: 左右留白，这样三行的右边缘才会对齐到同一条线（主人 2026-10-10 三次反馈
    #: 「不够紧凑」的核心诉求）。
    MIN_WIDTH = 300
    #: 内容区四周留白（@1x）
    PAD = 24
    #: 状态行显示反馈时的最大文本宽度（@1x）；超出的截断，完整内容仍写 app.log。
    #: 可用宽度 = WIDTH − 2×PAD − 绿点与间距，取 280 留一点余量。
    STATUS_W = 280

    def __init__(
        self,
        root: tk.Tk,
        cfg: dict,
        on_capture: Callable[[], None],
        on_save_settings: Callable[[dict], None],
        on_quit: Callable[[], None],
        on_suspend_hotkey: Callable[[], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.cfg = cfg
        self.on_capture = on_capture
        self.on_save_settings = on_save_settings
        self.on_quit = on_quit
        #: 录制热键前要先注销全局热键，否则按到当前那套组合会直接开始截屏
        self.on_suspend_hotkey = on_suspend_hotkey
        self.on_open_settings = on_open_settings
        self.scale = dpi_scale(root)
        #: 正在录制热键？
        self._recording = False
        #: 录制开始前的热键，取消时还原
        self._hotkey_before = ""
        #: 状态行截断用的字体 —— 按**像素宽度**截（中英文宽度差很多，按字数截不准）
        self._status_font = tkfont.Font(font=theme.FONT_TIP)
        #: 反馈显示几秒后自动恢复成热键状态的任务句柄
        self._restore_job: str | None = None

        root.title(APP_TITLE)
        root.resizable(False, False)
        root.configure(bg=theme.N0)

        pad = int(self.PAD * self.scale)
        body = tk.Frame(root, bg=theme.N0)
        body.pack(fill="both", expand=True, padx=pad, pady=pad)
        self._body = body

        self._build_header(body)
        self._build_hotkey_row(body)
        self._build_actions(body)

        # 宽高都由 `_fit()` 按内容算（宽度 = 最宽那行 + 左右留白）
        root.update_idletasks()
        self._win_w = 0
        self._fit()

    def _fit(self) -> None:
        """按内容重设窗口宽高：宽度取「三行里最宽的一行 + 左右留白」。

        三行的右边缘因此天然对齐到同一条线（主人 2026-10-10 三次反馈的核心诉求是
        "紧凑"）。窗口是 `resizable(False, False)`，不重设就会把底部按钮压扁。

        ⚠️ 尺寸没变就直接返回 —— `log()` 每次都会调这里，不判重会让窗口反复重设、闪。
        """
        self.root.update_idletasks()
        self._sync_capture_width()
        self.root.update_idletasks()
        pad = int(self.PAD * self.scale)
        content = max(
            self._header_row.winfo_reqwidth(),
            self._hotkey_row.winfo_reqwidth(),
            self._actions_row.winfo_reqwidth(),
        )
        self._win_w = max(int(self.MIN_WIDTH * self.scale), content + 2 * pad)
        height = self.root.winfo_reqheight()
        size = (self._win_w, height)
        if size == getattr(self, "_last_size", None):
            return
        self._last_size = size
        if self.root.winfo_ismapped():
            # 已经显示在屏幕上：改尺寸时必须显式带上当前坐标，
            # 否则 Tk 会把窗口挪回默认位置（实测会跳到屏幕左上角）。
            self.root.geometry(
                f"{self._win_w}x{height}+{self.root.winfo_x()}+{self.root.winfo_y()}"
            )
        else:
            self.root.geometry(f"{self._win_w}x{height}")

    def _sync_capture_width(self) -> None:
        """让「开始截屏」的右边缘与「点击录制」的右边缘对齐。

        基准是**热键行的自然宽度**（热键行的右边缘就是内容区右边界），所以
        `主按钮 = 热键行宽 − 设置按钮 − 间距`。主人 2026-10-10 明确要求这两条右边缘
        线重合。

        ⚠️ 不能用 `pack(fill="x")` —— Canvas 的 fill 只拉伸控件框，里面的圆角底图是
        按 `winfo_reqwidth()` 画的、不跟着变，结果就是"左边有底、右边空白"。
        """
        s = self.scale
        self.root.update_idletasks()
        row_w = self._hotkey_row.winfo_reqwidth()
        gap = int(12 * s)
        settings = int(56 * s)
        self.capture_button.set_fixed_width(max(int(140 * s), row_w - settings - gap))

    # ---------- 构建 ----------

    def _build_header(self, parent: tk.Misc) -> None:
        """品牌行：logo + 名称 + 版本徽章 + 状态行。

        ⚠️ 2026-10-10 主人要求删掉原来右上角那个「✓ 已在后台运行…」反馈徽章 ——
        它跟品牌行并排显得空旷，那条启动提示本身也没什么信息量。操作反馈改由状态行
        承担（见 `log()`）。
        """
        s = self.scale
        row = tk.Frame(parent, bg=theme.N0)
        row.pack(fill="x")
        self._header_row = row

        #: ⚠️ 2026-10-10 主人要求"适当放大 logo"：40 → 56 逻辑（+40%）。
        #: 它不承担"对齐"职责 —— 那是由 `_fit()` 按内容定宽 + 版本徽章贴右共同保证的。
        photo = self._brand_icon(int(56 * s))
        if photo is not None:
            tk.Label(row, image=photo, bd=0, bg=theme.N0).pack(
                side="left", padx=(0, int(14 * s))
            )

        column = tk.Frame(row, bg=theme.N0)
        column.pack(side="left", fill="x", expand=True)

        # ⚠️ name_row 必须 fill="x"、徽章 side="right" —— 这样版本徽章的右边缘才会
        #    落在品牌行右边缘上（主人 2026-10-10 要求它与下方按键的右边缘对齐）。
        name_row = tk.Frame(column, bg=theme.N0)
        name_row.pack(anchor="w", fill="x")
        tk.Label(
            name_row, text=APP_TITLE, font=theme.FONT_HERO, bg=theme.N0, fg=theme.N900
        ).pack(side="left")
        # 版本号用浅绿徽章（参考图里就是这个语言），不再是灰字
        self.version_badge = widgets.Badge(
            name_row, f"v{__version__}", tone="brand", dot=False, scale=s
        )
        self.version_badge.pack(side="right", pady=(int(4 * s), 0))

        status_row = tk.Frame(column, bg=theme.N0)
        status_row.pack(anchor="w", pady=(int(7 * s), 0))
        self._status_dot = tk.Label(
            status_row, text="●", font=theme.FONT_TIP, bg=theme.N0, fg=theme.G500
        )
        self._status_dot.pack(side="left", padx=(0, int(6 * s)))
        self._status_label = tk.Label(
            status_row, text="已就绪", font=FONT, bg=theme.N0, fg=theme.N700
        )
        self._status_label.pack(side="left")
        self._status_hint = tk.Label(
            status_row, text="", font=FONT, bg=theme.N0, fg=theme.N500
        )
        self._status_hint.pack(side="left")

    def _brand_icon(self, size: int):
        """品牌图标（复用 assets 里的应用图标）。

        ⚠️ 主人 2026-10-10 明确要求：**不换 logo**。参考图里那个方括号图标只是
        参考稿的示意，实际程序继续用应用自己的图标。
        """
        try:
            source = icons.tray_image()
        except Exception:  # noqa: BLE001 - 图标缺失不该挡住窗口
            return None
        if source is None:
            return None
        image = source.resize((size, size), Image.LANCZOS)
        self._brand_photo = ImageTk.PhotoImage(image, master=self.root)
        return self._brand_photo

    def _build_hotkey_row(self, parent: tk.Misc) -> None:
        s = self.scale
        row = tk.Frame(parent, bg=theme.N0)
        row.pack(fill="x", pady=(int(30 * s), 0))
        self._hotkey_row = row

        tk.Label(row, text="全局热键", font=FONT, bg=theme.N0, fg=theme.N700).pack(
            side="left", padx=(0, int(12 * s))
        )

        self.var_hotkey = tk.StringVar(value=self.cfg.get("hotkey", "ctrl+alt+s"))
        # 热键**不是输入框**：键帽只负责"显示要按什么"，真正进入录制要点「点击录制」
        # （键帽本身也可点，两条入口同一件事 —— 参考图里两者并存）。
        self.hotkey_caps = widgets.HotkeyCaps(
            row, self.var_hotkey.get(), self._record_hotkey, scale=s
        )
        self.hotkey_caps.pack(side="left")

        self.record_button = widgets.RoundButton(
            row,
            "点击录制",
            self._record_hotkey,
            variant="secondary",
            font=FONT,
            pad_x=16,
            height=int(38 * s),
            scale=s,
        )
        # ⚠️ 2026-10-10 主人要求：紧挨在键帽右边，不再贴到行的最右端
        #    （贴右端会在中间留一大片空当，正是他要消掉的"空处"）。
        self.record_button.pack(side="left", padx=(int(10 * s), 0))

    def _build_actions(self, parent: tk.Misc) -> None:
        s = self.scale
        row = tk.Frame(parent, bg=theme.N0)
        row.pack(fill="x", pady=(int(26 * s), 0))
        self._actions_row = row

        self.capture_button = widgets.RoundButton(
            row,
            "开始截屏",
            self.on_capture,
            variant="brand",
            icon="capture",
            icon_size=20,
            font=theme.FONT_BUTTON,
            height=int(44 * s),
            scale=s,
        )
        self.capture_button.pack(side="left")

        self.settings_button = widgets.RoundButton(
            row,
            "",
            self.on_open_settings,
            variant="secondary",
            icon="settings",
            icon_size=20,
            width=int(56 * s),
            height=int(44 * s),
            scale=s,
            tooltip="设置",
        )
        self.settings_button.pack(side="left", padx=(int(12 * s), 0))
        if self.on_open_settings is None:
            self.settings_button.set_enabled(False)
    def _sync_hotkey_button(self) -> None:
        self.hotkey_caps.set_text(self.var_hotkey.get())

    def _record_hotkey(self) -> None:
        """点键帽或「点击录制」→ 进入录制：主人直接按组合键，不用手打。"""
        if self._recording:
            return
        self._recording = True
        self._hotkey_before = self.var_hotkey.get()
        self.var_hotkey.set("请按组合键…")
        self._sync_hotkey_button()
        self.record_button.set_variant("brand")
        self.record_button.set_text("按下组合键")
        # ⚠️ 先注销全局热键再录：不然主人按到**当前**那套组合时，程序会立刻开始
        #    截屏（整屏遮罩盖上来），录制框反而收不到按键。
        if self.on_suspend_hotkey is not None:
            self.on_suspend_hotkey()
        self.root.bind("<KeyPress>", self._on_record_key)
        self.root.focus_force()
    def _on_record_key(self, event: tk.Event) -> str:
        if event.keysym.lower() == "escape":
            self._finish_record(None)  # Esc = 取消录制
            return "break"
        combo = combo_from_event(event)
        if combo is None:
            return "break"  # 只按了修饰键，继续等真正的按键
        self._finish_record(combo)
        return "break"

    def _finish_record(self, combo: str | None) -> None:
        """结束录制。`combo=None` 表示取消。"""
        self._recording = False
        self.root.unbind("<KeyPress>")
        self.record_button.set_variant("secondary")
        self.record_button.set_text("点击录制")
        cancelled = combo is None
        self.var_hotkey.set(self._hotkey_before if cancelled else combo)
        self._sync_hotkey_button()
        # 录制开始时注销过热键，这里无论取消还是改成功都要注册回去
        self._save_hotkey()
        if cancelled:
            self.log("已取消录制，热键未改动")
    def _save_hotkey(self) -> None:
        hotkey = self.var_hotkey.get().strip() or "ctrl+alt+s"
        self.cfg["hotkey"] = hotkey
        self.on_save_settings(self.cfg)
        self.log(f"热键已保存：{hotkey}")

    def set_hotkey_status(self, text: str, *, tone: str = "ok") -> None:
        """更新品牌行下的状态行（`tone` 取 ok / idle / warn）。

        正常态下 `text` 是 "<组合> 已就绪"，这里只留"已就绪"三个字，把组合交给后面
        那句「· 按 <组合> 开始」—— 参考图的第二行正是这个结构。

        ⚠️ 会**取消** `log()` 排下的恢复任务：外部显式设状态时，不该被那条定时器
        覆盖回去。
        """
        self._cancel_status_restore()
        if tone == "ok" and text.endswith("已就绪"):
            self._status_dot.configure(fg=theme.G500)
            self._status_label.configure(text="已就绪", fg=theme.N700)
            self._status_hint.configure(
                text=" · 按 %s 开始" % _pretty_hotkey(self.var_hotkey.get())
            )
        else:
            color = {"warn": "#F59E0B", "idle": theme.N300}.get(tone, theme.G500)
            self._status_dot.configure(fg=color)
            self._status_label.configure(
                text=text, fg="#B45309" if tone == "warn" else theme.N700
            )
            self._status_hint.configure(text="")
        self._fit()

    #: 反馈在状态行停留的时长（毫秒），到点自动恢复成热键状态
    LOG_HOLD_MS = 4000

    def log(self, text: str) -> None:
        """操作反馈 → 状态行（临时顶掉「已就绪 · 按 … 开始」，几秒后自动恢复）。

        改造前这里写的是品牌行右上角的徽章；主人 2026-10-10 反馈那个徽章占地方、
        跟品牌行并排显得空旷，所以反馈回到状态行内显示。⚠️ 过长的文本按**像素宽度**
        截断，完整内容仍然只写进 app.log。
        """
        message = text.strip()
        if message:
            limit = int(self.STATUS_W * self.scale)
            while message and self._status_font.measure(message) > limit:
                message = message[:-1]
            if message != text.strip():
                message = message.rstrip() + "…"
            warn = "⚠" in text or "失败" in text or "错误" in text
            self._status_dot.configure(fg="#F59E0B" if warn else theme.G500)
            self._status_label.configure(
                text=message, fg="#B45309" if warn else theme.N700
            )
            self._status_hint.configure(text="")
            self._schedule_status_restore()
        self._fit()

    def _schedule_status_restore(self) -> None:
        self._cancel_status_restore()
        self._restore_job = self.root.after(self.LOG_HOLD_MS, self._restore_status)

    def _cancel_status_restore(self) -> None:
        job = self._restore_job
        if job is not None:
            self._restore_job = None
            try:
                self.root.after_cancel(job)
            except (tk.TclError, ValueError):
                pass

    def _restore_status(self) -> None:
        self._restore_job = None
        self.set_hotkey_status(f"{self.var_hotkey.get()} 已就绪")

    def refresh_history(self) -> None:
        """历史记录仍会写入磁盘，只是界面不再展示。"""
