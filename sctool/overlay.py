"""全屏截图遮罩：框选（含放大镜/坐标/色值）→ 定格标注编辑。

两个阶段：
    selecting  拖拽框选；鼠标处显示放大镜 + 坐标 + 色值；默认整屏选中
    editing    选区定格，浮出工具栏；可标注（矩形/椭圆/箭头/画笔/马赛克/文字/表情）

坐标约定：Canvas 坐标 == 截图的物理像素坐标（因为遮罩窗口 1:1 铺满屏幕），
所以标注坐标直接可用；存进 Annotation 时转成"选区相对坐标"，方便裁剪后渲染。

⚠️ 视觉层的核心约束（改造时定的，别推翻）：**工具栏与所有浮层一律用 Canvas
   item 绘制，不用任何子 widget**。原因是遮罩窗口对全屏 `grab_set()`，子 Toplevel
   根本收不到鼠标事件（工具栏会点不动）；而 `tk.Frame` 又做不出圆角（直角色块
   盖在截图上很突兀）。画在 Canvas 上则两全：圆角图自带 alpha，圆角之外的像素
   自然透出下面的暗化截图。代价是命中测试得自己算 —— 见 `_bar_hit`。
"""

from __future__ import annotations

import ctypes
import math
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import capture, iconlib, theme

# ---------- 视觉常量（尺寸一律 @1x，用前过 theme.pxf）----------

#: 选区边框 / 手柄
ACCENT = theme.G500
#: 自动检测到的窗口高亮（虚线，与用户拖出来的绿色实线区分开）
HOT_ACCENT = theme.B500
HANDLE_RADIUS = 5
HANDLE_RING = 1.5
MIN_SELECTION = 6
#: 判定"这是一次单击（要吸附窗口）而不是拖拽框选"的位移容差（物理像素）。
#: 鼠标手抖一两像素很正常，容差太小会让"点一下选窗口"变得很难点中。
SNAP_CLICK_TOLERANCE = 4

#: 遮罩底图的变暗系数（选区外的部分压到原亮度的多少）。
#: ⚠️ 用 `Image.point` 查表而不是 `ImageEnhance.Brightness`：两者结果逐像素一致
#: （`ImageEnhance` 内部就是 `point(lambda x: x * factor)`），但整屏 2880×1800
#: 上实测 33.5ms → 12.0ms —— point 只建一次 256 项 LUT，不逐像素回 Python。
DIM_FACTOR = 0.45
#: ⚠️ PIL 的 `point` 要求 LUT 按**每个 band** 给全 —— RGB 图要 768 项，只给 256
#: 会直接抛 `ValueError: wrong number of lut entries`（实测踩到）。`grab_all()`
#: 固定产出 "RGB"，所以这里就按 3 个 band 展开好。
_DIM_LUT = [int(v * DIM_FACTOR) for v in range(256)] * 3

#: 工具栏
BAR_BTN = 30  # 按钮边长
BAR_ICON = 19  # 图标边长
#: 色卡（palette）专用：它是个半圆，视觉高度只有满格的一半，按 19px 画出来比
#: 邻居"轻"一大截、中间那格的颜色也小到看不清 —— 所以放大到 24px（按钮 30px 塞得下）。
BAR_ICON_WIDE = 24
BAR_PAD = 5  # 卡片内边距
BAR_GAP = 7  # 分组之间的空隙（分隔线两侧各一半）
BAR_RADIUS = theme.RADIUS_MD
BAR_HOVER_RADIUS = theme.RADIUS_SM
#: 工具栏与选区之间的间距
BAR_OFFSET = 10
#: 「识」「译」这一组的衬底。比工具栏底（D900）亮一档、带蓝调 ——
#: 主人要求这两个字醒目，光靠字色在一排图标里不够跳，垫一块底色才能一眼定位。
ACTION_GROUP_BG = "#2A3547"

#: 放大镜
MAG_SIZE = 160  # 放大镜显示边长
MAG_SRC = 20  # 放大镜取样边长（8 倍）
MAG_ZOOM = MAG_SIZE // MAG_SRC
MAG_PAD = 10  # 放大镜面板内边距
MAG_SWATCH = 14  # 色值前面的小色块边长
MAG_SWATCH_GAP = 8  # 色块与色值文字的间距
MAG_HINT_FG = theme.D400  # 提示行：次要信息用灰，与主信息拉开层次
MAG_HINT_OK = theme.G500  # 复制成功的反馈色

#: 拖动中刷新亮版图的最小间隔（秒），约 30fps。
#: 实测整屏 2880×1800 重建一次 ~19ms，这个间隔既跟手又给老机器留了余量。
REGION_REFRESH_INTERVAL = 0.03
#: 窗口高亮的检测间隔（秒）。Z-order 遍历一次约 1~3ms，节流到 ~16fps 足够跟手。
HOT_CHECK_INTERVAL = 0.06
#: 工具栏按钮的悬停提示延迟（毫秒）。与 widgets.Tooltip 保持一致：
#: 鼠标快速划过一排图标时不该一路冒气泡。
TIP_DELAY_MS = 420

#: 标注默认样式
ANNO_COLORS = (
    "#FF3B30",  # 红（默认）
    "#FF9500",  # 橙
    "#FFCC00",  # 黄
    "#22C55E",  # 绿
    "#2F6FD0",  # 蓝
    "#AF52DE",  # 紫
    "#1F2225",  # 近黑
    "#FFFFFF",  # 白
)
ANNO_WIDTHS = (2, 3, 5)
ANNO_FONT_SIZE = 22

FONT_UI = theme.FONT_BODY
FONT_SMALL = theme.FONT_TIP

#: 标注工具：(键, 图标名, 提示)
#: ⚠️ 这里**没有**「表情」了 —— 主人 2026-10-08 要求删掉（用不上，白占一格）。
TOOLS = (
    ("rect", "rect", "矩形"),
    ("ellipse", "ellipse", "椭圆"),
    ("arrow", "arrow", "箭头"),
    ("pen", "pen", "画笔"),
    ("mosaic", "mosaic", "马赛克"),
    ("text", "text", "文字"),
)
#: 样式（影响标注外观）
STYLES = (("palette", "palette", "标注颜色"), ("stroke", "stroke", "线宽"))
#: 业务动作。⚠️ 这两项主人 2026-10-08 明确要求**保留汉字**（「译」「识」）：
#: "它们是软件的主要功能，用字更醒目"。所以它们不走进 iconlib 的自绘图标通道，
#: 而是走工具栏里的"文字通道" —— 见 `_build_toolbar` 与 `ACTION_KEYS`。
ACTIONS = (("translate", "译", "翻译"), ("ocr", "识", "提取文字"))
#: 系统动作
SYSTEM = (
    ("undo", "undo", "撤销"),
    ("save", "save", "保存到文件"),
    ("pin", "pin", "钉在屏幕"),
    ("copy", "copy", "复制到剪贴板"),
    ("close", "close", "取消（Esc）"),
    ("confirm", "confirm", "完成并复制（Enter）"),
)

TOOL_KEYS = {key for key, _, _ in TOOLS}
#: 走"文字通道"的按钮：保留汉字，不走自绘图标
ACTION_KEYS = {key for key, _, _ in ACTIONS}
#: 汉字在按钮里的垂直微调（@1x）。汉字的视觉重心比字体 em 框中心略低，
#: 不往上挪一点会显得"往下坐"。
ACTION_TEXT_NUDGE = 1
#: 工具栏分组（组间画分隔线）
BAR_GROUPS = (TOOLS + STYLES, ACTIONS, SYSTEM)

#: 弹出面板的过渡动画（滑出 + 淡入淡出）。节奏参考 `widgets.Toast` 的 alpha 淡入：
#: 7 帧 × 16ms ≈ 112ms —— 够快不拖沓，又能看清"滑出来"的过程。
POPUP_ANIM_STEPS = 7
POPUP_ANIM_INTERVAL = 16
#: 起始位置相对最终位置的纵向偏移（逻辑像素）：面板从贴近按钮处滑到最终位置
POPUP_ANIM_SHIFT = 12
#: 走「滑出 + 淡入」这套动画的弹出面板。只有整块合成成一张 PIL 图的才做得到
#: （Canvas item 没有 alpha，见 `_animate_popup`）—— 调色板与线宽面板都是。
_ANIMATED_POPUPS = frozenset({"palette", "stroke"})

#: 点「取消」/「完成」后的**退场动画**：**功能栏渐隐**（工具栏 + 底部提示条）。
#: ⚠️ 帧数别贪多：每帧要为 2 个图层各建一张 PhotoImage（建图开销 + 18ms 延时，
#:    实测每帧约 25~30ms）。8 帧的**帧延时之和**是 144ms，但算上建图与收尾销毁，
#:    实机测到的"遮罩消失耗时"是 **0.33~0.39s** —— 够看清"渐隐"又不拖沓。
#: （曾有一版"选区浮雕（凹陷 / 凸出）"，主人 2026-10-09 反馈效果不佳，已移除。）
FINISH_ANIM_STEPS = 8
FINISH_ANIM_INTERVAL = 18

#: 各阶段的底部提示
HINT_SELECTING = "拖拽框选 · Enter 完成 · Esc 取消"
HINT_EDITING = "点图标选工具 · Enter 完成 · Esc 取消"


@dataclass
class Annotation:
    kind: str  # rect | ellipse | arrow | pen | mosaic | text
    coords: object  # 依 kind 而定，见 render_annotations
    color: str = ANNO_COLORS[0]
    width: int = ANNO_WIDTHS[1]
    text: str = ""
    size: int = ANNO_FONT_SIZE


# ---------- 渲染（把标注烧进图像）----------


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", size)
    except OSError:
        return ImageFont.load_default()


def _text_ink_offset(font: ImageFont.FreeTypeFont, text: str) -> int:
    """文字**墨迹**顶部相对 PIL 锚点（ascender 线）往下偏了多少像素。

    PIL 的默认锚点是 `"la"` = 左边缘 + ascender 顶，而中文字形的实际墨迹顶部
    还在 ascender 下面几个像素（22px 的微软雅黑实测差 4px）。照默认画，文字就会
    比用户点的位置**低一点点** —— 主人 2026-10-08 反馈的"文字位置偏移"就是这个。
    渲染时把这个偏移减掉，墨迹左上角正好落在用户点击处。
    """
    if not text:
        return 0
    try:
        return int(font.getbbox(text)[1])
    except (OSError, ValueError):
        return 0


def _draw_arrow(draw: ImageDraw.ImageDraw, start, end, color: str, width: int) -> None:
    draw.line([start, end], fill=color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    head = max(12, width * 5)
    for delta in (math.radians(155), math.radians(-155)):
        tip = (
            end[0] + head * math.cos(angle + delta),
            end[1] + head * math.sin(angle + delta),
        )
        draw.line([end, tip], fill=color, width=width)


def _apply_mosaic(image: Image.Image, box) -> None:
    x1, y1, x2, y2 = (int(v) for v in box)
    x1, x2 = sorted((max(0, x1), min(image.width, x2)))
    y1, y2 = sorted((max(0, y1), min(image.height, y2)))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    region = image.crop((x1, y1, x2, y2))
    block = 10
    small = region.resize(
        (max(1, region.width // block), max(1, region.height // block)), Image.NEAREST
    )
    image.paste(small.resize(region.size, Image.NEAREST), (x1, y1))


def render_annotations(image: Image.Image, annotations: list[Annotation]) -> Image.Image:
    """返回带标注的新图（原图不动）。"""
    out = image.copy()
    draw = ImageDraw.Draw(out)

    for anno in annotations:
        if anno.kind == "rect":
            draw.rectangle(anno.coords, outline=anno.color, width=anno.width)
        elif anno.kind == "ellipse":
            draw.ellipse(anno.coords, outline=anno.color, width=anno.width)
        elif anno.kind == "arrow":
            _draw_arrow(draw, anno.coords[0], anno.coords[1], anno.color, anno.width)
        elif anno.kind == "pen":
            points = list(anno.coords)
            if len(points) >= 2:
                draw.line(points, fill=anno.color, width=anno.width, joint="curve")
        elif anno.kind == "mosaic":
            _apply_mosaic(out, anno.coords)
        elif anno.kind == "text":
            font = _font(anno.size)
            # 减掉墨迹偏移，让文字墨迹的左上角正好落在用户点击处（见 _text_ink_offset）
            draw.text(
                (anno.coords[0], anno.coords[1] - _text_ink_offset(font, anno.text)),
                anno.text,
                fill=anno.color,
                font=font,
            )
    return out


# ---------- 遮罩窗口 ----------


class ScreenshotOverlay:
    """全屏遮罩：框选 + 标注，最后返回 (成品图, 动作)。"""

    def __init__(
        self,
        master: tk.Misc,
        shot: capture.ScreenShot,
        on_action=None,
    ) -> None:
        self.master = master
        self.shot = shot
        #: 「识」「译」不关闭遮罩，而是把 (动作, 选区图) 交给 app 处理，
        #: 这样用户可以连续点「先识后译」——工具栏不会消失。
        self.on_action = on_action
        self.width, self.height = shot.size
        self.origin = shot.origin

        self.state = "selecting"
        self.box: tuple[int, int, int, int] = (0, 0, self.width, self.height)
        self.annotations: list[Annotation] = []
        self.tool: str | None = None
        self.action: str | None = None

        #: 标注样式（调色板 / 线宽面板改的就是它们）
        self.anno_color = ANNO_COLORS[0]
        self.anno_width = ANNO_WIDTHS[1]

        self._win: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        self._scale = theme.scale(master)

        self._base_photo: ImageTk.PhotoImage | None = None
        self._region_photo: ImageTk.PhotoImage | None = None
        self._mag_photo: ImageTk.PhotoImage | None = None

        self._drag_anchor: tuple[int, int] | None = None
        self._anno_start: tuple[int, int] | None = None
        self._pen_points: list[tuple[int, int]] = []
        #: 拖拽中 / 输入中的临时标注。**它本身就是最终标注**（走同一套 PIL 渲染），
        #: 松手时原样落进 `annotations` —— 预览与成品因此逐像素一致。
        #: 改造前预览是 Tk Canvas item、成品是 PIL，两套描边语义不同，
        #: "完成瞬间"标注会跳 1~2px（主人反馈的"完成后位置会偏移一点点"）。
        self._pending: Annotation | None = None
        self._cursor_color = "#000000"
        self._last_region_update = 0.0
        #: 亮版图是否已「激活」= 当前选区是用户明确选出来的，值得显示。
        #: 初始的「整屏默认选中」不算 —— 给它刷亮版会让整屏都变亮，遮罩就白做了。
        self._region_active = False
        #: 编辑阶段拖动整个选区时记录 (鼠标起点, 起始框)
        self._move_origin: tuple[tuple[int, int], tuple[int, int, int, int]] | None = None
        #: 正在拖拽的角手柄索引（0 左上 / 1 右上 / 2 左下 / 3 右下）
        self._resize_handle: int | None = None

        #: 工具栏：整体 bbox + 每个按钮的 bbox（命中测试用，全部是物理像素）
        self._bar_box: tuple[int, int, int, int] | None = None
        self._bar_buttons: dict[str, tuple[int, int, int, int]] = {}
        self._bar_hover: str | None = None
        #: key → 悬停提示文案（来自 TOOLS/STYLES/ACTIONS/SYSTEM 的第三元）
        self._bar_tips: dict[str, str] = {}
        #: 提示气泡的延迟任务与当前待显示的按钮
        self._bar_tip_job: str | None = None
        self._bar_tip_key: str | None = None
        self._bar_x = 0
        self._bar_y = 0
        self._bar_size: tuple[int, int] = (0, 0)
        #: 每个格子有两种绘制通道：图标 item 与文字 item，同一时刻只亮一个。
        #: 「识」「译」走文字通道（保留汉字），其余走 iconlib 的图标通道。
        self._bar_icon_ids: dict[str, int] = {}
        self._bar_text_ids: dict[str, int] = {}
        self._bar_active_ids: dict[str, int] = {}
        #: key → (kind, value, color, hover_color)，kind 取 "icon" / "text"
        self._bar_visuals: dict[str, tuple[str, str, str, str]] = {}
        #: 工具栏当前是否显示。⚠️ 必须显式记这个状态：工具栏的 item 在构建时就
        #: 全建好了，若不区分"显示中"，初始状态下图标会**漏在屏幕左上角**
        #: （item 建出来就是 normal，而那时还没 place 过）。
        self._bar_visible = False
        self._bar_group_id: int | None = None
        self._bar_group_box = (0, 0)

        #: 自动检测到的窗口高亮
        self._hot_hwnd = 0
        self._hot_rect: tuple[int, int, int, int] | None = None
        self._last_hot_check = 0.0
        #: 高亮窗口的内容高光图（贴在暗化底图之上，让"将要选中的窗口"直接亮起来）
        self._hot_photo = None
        #: 按下左键时的落点与当时高亮的窗口 —— 用来区分"单击吸附"与"拖拽框选"
        self._press_at: tuple[int, int] | None = None
        self._press_hot: tuple[int, int, int, int] | None = None

        #: 弹出面板（调色板 / 线宽 / 文字输入）
        self._popup: str | None = None
        self._popup_boxes: list[tuple[tuple[int, int, int, int], object]] = []
        #: 面板的过渡动画：当前任务句柄 + 合成图/位置（收回动画要复用同一张图）
        self._popup_job: str | None = None
        self._popup_board: Image.Image | None = None
        self._popup_item: int | None = None
        self._popup_origin: tuple[int, int] = (0, 0)
        #: 面板开在工具栏下方？（决定滑出方向）
        self._popup_below = True
        #: 合成图的内容签名 —— 参与动画帧的缓存键，必须涵盖影响画面的状态
        #: （调色板→当前色、线宽→当前档），否则换选中项后会命中旧帧。
        self._popup_sig: tuple | None = None

        #: 退场动画（点「取消」/「完成」）：防重入标志 + 当前任务句柄。
        #: 动画期间再点一次就**立刻结束**（不磨蹭），见 `_finish`。
        self._finishing = False
        self._finish_job: str | None = None
        self._text_entry: tk.Entry | None = None
        self._text_anchor: tuple[int, int] | None = None

        # canvas item ids
        self._shade_ids: list[int] = []
        self._rect_id: int | None = None
        self._handle_ids: list[int] = []
        self._region_id: int | None = None
        self._mag_ids: dict[str, int] = {}
        self._mag_pad = 0

    # ---------- 生命周期 ----------

    def _build(self) -> None:
        """建遮罩窗口 + 画布 + 全部 Canvas item + 绑事件。

        ⚠️ 只构建，**不显示、不抢焦点、不进事件循环** —— 这样 `prewarm()` 能借它
        把素材算好；窗口是否映射由 Tk 在 idle 时才决定，这里没有 `update()`，
        所以调用方只要在 `update()` 之前 `withdraw()` 就绝不会闪出来。
        """
        win = tk.Toplevel(self.master)
        self._win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{self.width}x{self.height}+{self.origin[0]}+{self.origin[1]}")

        canvas = tk.Canvas(
            win,
            width=self.width,
            height=self.height,
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(fill="both", expand=True)
        self._canvas = canvas

        self._build_canvas_items()
        self._build_toolbar()
        self._build_hint()

        canvas.bind("<Button-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_motion)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_hover)
        canvas.bind("<Leave>", lambda _e: self._on_leave())

        win.bind("<Escape>", lambda _e: self._on_escape())
        win.bind("<Return>", lambda _e: self._on_enter())
        win.bind("<Control-c>", lambda _e: self._copy_color())

    def run(self) -> tuple[Image.Image, str] | None:
        capture.enable_dpi_awareness()
        self._build()
        win = self._win
        canvas = self._canvas
        assert win is not None and canvas is not None

        canvas.focus_set()
        win.focus_force()
        try:
            win.grab_set()
        except tk.TclError:
            pass

        self._draw_selection(*self.box)
        self.master.wait_window(win)

        if self.action is None:
            return None
        return self._current_region(), self.action

    @staticmethod
    def prewarm(master: tk.Misc) -> None:
        """预热遮罩素材：把卡片、工具栏、字体度量先算一遍，填满缓存。

        遮罩里与截图内容无关的那部分（放大镜卡片、工具栏底图与图标、提示条）
        首次构建要 ~150ms —— 不预热的话，"程序启动后第一次按热键"就要多等这么久
        （实测 303ms vs 之后的 154ms）。启动时后台做一次，此后每次按热键都走快路径。

        ⚠️ 窗口建好**立刻 withdraw**，从不真正显示、也不抢焦点；失败不影响使用。
        """
        shot = capture.grab_all()
        ov = ScreenshotOverlay(master, shot)
        ov._build()
        win = ov._win
        assert win is not None
        try:
            win.withdraw()
            win.update_idletasks()
        finally:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _build_canvas_items(self) -> None:
        canvas = self._canvas
        assert canvas is not None

        # 底层：整屏「变暗版」，平滑无图案。
        #
        # ⚠️ 这里刻意**不用** stipple 网点做半透明：8×8 的规则网点平铺在屏幕上
        # 会与显示器像素阵列发生干涉（摩尔纹），手机拍照/录像时呈现为彩色
        # （偏紫）条纹。用户反馈过"截屏时边缘出现紫色条纹"，即为此。
        # 改用「整屏变暗 + 选区贴原图」的聚光灯方案，完全没有规则图案。
        dim = self.shot.image.point(_DIM_LUT)
        self._base_photo = ImageTk.PhotoImage(dim)
        canvas.create_image(0, 0, anchor="nw", image=self._base_photo, tags="shade")

        # 自动检测到的窗口高亮：**内容高光**层。位置很讲究 —— 必须在暗化底图
        # 之后、选区亮版之前：高亮窗口的内容要亮起来，但仍比"用户已选中的区域"
        # 低一层。⚠️ 它单独用 `hotregion` 这个 tag：虚线框那组 `hot` 每帧都在
        # delete 后重建，混在一起会把这个 item 一并删掉。
        self._hot_region_id = canvas.create_image(
            0, 0, anchor="nw", state="hidden", tags="hotregion"
        )

        # 选区：原图裁剪（亮），盖在变暗层之上
        self._region_id = canvas.create_image(
            0, 0, anchor="nw", state="hidden", tags="region"
        )

        self._rect_id = canvas.create_rectangle(
            0, 0, 0, 0, outline=ACCENT, width=2, state="hidden", tags="sel"
        )
        # 圆形手柄 + 白描边（原来是 8×8 纯方块，硬邦邦的）
        self._handle_ids = [
            canvas.create_oval(
                0,
                0,
                0,
                0,
                fill=ACCENT,
                outline="#FFFFFF",
                width=max(1, int(round(HANDLE_RING * self._scale))),
                state="hidden",
                tags="sel",
            )
            for _ in range(4)
        ]
        # 尺寸标签：圆角深色胶囊（原来是裸白字，压在浅色背景上直接看不见）。
        # 胶囊宽度随文字变，所以每次重绘时整块重建 —— 见 _draw_size_badge。
        self._build_magnifier_items()

    def _build_magnifier_items(self) -> None:
        """放大镜面板：圆角卡片 + 阴影（有阴影就必须记下 pad 并全程抵消）。"""
        canvas = self._canvas
        assert canvas is not None

        # ⚠️ 行距与面板宽度都必须按**实测字体度量**算，不能写死像素。
        # Tk 的 pt 字号会随系统 DPI 缩放（本机 200%，9pt 实际行高 31px），
        # 曾经写死 16px 行距，三行文字叠成一坨（主人 2026-10-08 截图反馈）。
        #
        # 宽度按**最坏情况**算一次后固定：坐标位数、色值文本都会变，
        # 若每帧按当前文本重算，面板会随鼠标移动忽宽忽窄地跳。
        self._mag_font = tkfont.Font(font=FONT_SMALL)
        self._mag_line_h = self._mag_font.metrics("linespace")
        s = self._scale
        pad = theme.pxf(s, MAG_PAD)
        swatch = theme.pxf(s, MAG_SWATCH)
        gap = theme.pxf(s, MAG_SWATCH_GAP)
        content_w = max(
            self._mag_font.measure(f"坐标 {self.width}, {self.height}"),
            self._mag_font.measure("按 Ctrl+C 复制色值"),
            self._mag_font.measure("已复制 #ffffff"),
            swatch + gap + self._mag_font.measure("色值 #ffffff"),
        )
        self._mag_panel_w = max(theme.pxf(s, MAG_SIZE) + pad * 2, content_w + pad * 2)
        self._mag_panel_h = (
            theme.pxf(s, MAG_SIZE) + pad * 3 + self._mag_line_h * 3
        )

        card, shadow_pad = theme.flat_image(
            self._mag_panel_w,
            self._mag_panel_h,
            radius=theme.pxf(s, theme.RADIUS_LG),
            fill=theme.D900,
            outline=theme.D_SEP,
            outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
            shadow=theme.SHADOW_DARK,
        )
        self._mag_pad = shadow_pad
        self._mag_ids["bg"] = canvas.create_image(
            0, 0, anchor="nw", image=theme.photo(card, key=("mag", self._mag_panel_w, self._mag_panel_h, s)), state="hidden", tags="mag"
        )
        self._mag_ids["img"] = canvas.create_image(
            0, 0, anchor="nw", state="hidden", tags="mag"
        )
        self._mag_ids["swatch"] = canvas.create_image(
            0, 0, anchor="nw", state="hidden", tags="mag"
        )
        for key in ("xy", "color", "hint"):
            self._mag_ids[key] = canvas.create_text(
                0,
                0,
                anchor="nw",
                fill=theme.D100,
                font=FONT_SMALL,
                text="",
                state="hidden",
                tags="mag",
            )
        canvas.itemconfigure(self._mag_ids["hint"], fill=MAG_HINT_FG)

    # ---------- 工具栏 ----------
    #
    # 整条工具栏就是一组 Canvas item：一张圆角深色卡片 + 一排图标 + 若干分隔线。
    # 悬停底是另一张圆角图（预先建好、默认 hidden），鼠标划过时切换显示。

    def _build_toolbar(self) -> None:
        canvas = self._canvas
        assert canvas is not None
        s = self._scale

        btn = theme.pxf(s, BAR_BTN)
        pad = theme.pxf(s, BAR_PAD)
        gap = theme.pxf(s, BAR_GAP)
        sep_w = theme.pxf(s, theme.STROKE_HAIRLINE)

        total_w = pad * 2 + sum(len(group) * btn for group in BAR_GROUPS) + (
            len(BAR_GROUPS) - 1
        ) * (sep_w + gap * 2)
        total_h = pad * 2 + btn
        self._bar_size = (total_w, total_h)

        card = theme.rounded_image(
            total_w,
            total_h,
            theme.pxf(s, BAR_RADIUS),
            theme.D900,
            theme.D_SEP,
            theme.pxf(s, theme.STROKE_HAIRLINE),
        )
        self._bar_card_photo = theme.photo(
            card, key=("bar", total_w, total_h, s)
        )

        # 悬停底：一张圆角图，靠移动它的坐标来"跟着"鼠标所在的按钮
        hover_side = btn - theme.pxf(s, 4)
        self._bar_hover_photo = theme.rounded_photo(
            canvas,
            hover_side,
            hover_side,
            radius=theme.pxf(s, BAR_HOVER_RADIUS),
            fill=theme.D800,
            key=("barhover", hover_side, s),
        )
        self._bar_hover_id = canvas.create_image(
            0, 0, anchor="nw", image=self._bar_hover_photo, state="hidden", tags="bar"
        )
        self._bar_card_id = canvas.create_image(
            0, 0, anchor="nw", image=self._bar_card_photo, state="hidden", tags="bar"
        )

        # 逐个按钮：算 bbox → 画图标 → 建悬停底/激活底
        x = pad
        nudge = theme.pxf(s, ACTION_TEXT_NUDGE)
        self._bar_buttons.clear()
        self._bar_icon_ids.clear()
        self._bar_text_ids.clear()
        self._bar_active_ids.clear()
        self._bar_visuals.clear()
        self._bar_tips.clear()
        for index, group in enumerate(BAR_GROUPS):
            for key, value, tip in group:
                box = (x, pad, x + btn, pad + btn)
                self._bar_buttons[key] = box
                self._bar_tips[key] = tip
                color, hover_color = self._button_colors(key)
                cx, cy = x + btn / 2, pad + btn / 2
                is_text = key in ACTION_KEYS
                self._bar_visuals[key] = (
                    "text" if is_text else "icon",
                    value,
                    color,
                    hover_color,
                )
                # 两个通道都建出来，**初始一律 hidden** —— 显示与否由
                # `_bar_visible` 统一控制（见 _paint_bar_item）。
                self._bar_icon_ids[key] = canvas.create_image(
                    cx, cy, anchor="center", state="hidden", tags="bar"
                )
                if not is_text:
                    canvas.itemconfigure(
                        self._bar_icon_ids[key],
                        image=self._bar_icon_photo(canvas, value, color),
                    )
                self._bar_text_ids[key] = canvas.create_text(
                    cx,
                    cy - nudge,
                    anchor="center",
                    text=value if is_text else "",
                    font=theme.FONT_ACTION,
                    fill=color,
                    state="hidden",
                    tags="bar",
                )
                # 激活底（当前工具）
                active_side = btn - theme.pxf(s, 4)
                active_photo = theme.rounded_photo(
                    canvas,
                    active_side,
                    active_side,
                    radius=theme.pxf(s, BAR_HOVER_RADIUS),
                    fill=theme.B500,
                    key=("baractive", active_side, s),
                )
                self._bar_active_ids[key] = canvas.create_image(
                    x + btn / 2,
                    pad + btn / 2,
                    anchor="center",
                    image=active_photo,
                    state="hidden",
                    tags="bar",
                )
                x += btn
            if index < len(BAR_GROUPS) - 1:
                x += gap
                canvas.create_line(
                    x,
                    pad + theme.pxf(s, 6),
                    x,
                    total_h - pad - theme.pxf(s, 6),
                    fill=theme.D_SEP,
                    width=sep_w,
                    tags="bar",
                )
                x += gap + sep_w

        self._build_action_group(pad, s)
        self._stack_bar_items()
        self._refresh_tool_highlight()

    def _build_action_group(self, pad: int, s: float) -> None:
        """给「识」「译」垫一块淡蓝衬底。

        主人要求这两个字醒目。单靠字色在一排图标里不够跳 —— 垫一块比工具栏底
        亮一档的蓝调底色，视线一眼就能落上去，同时和"激活态（蓝底白字）"区分得开。
        """
        canvas = self._canvas
        if canvas is None:
            return
        boxes = [
            self._bar_buttons[key]
            for key in ("translate", "ocr")
            if key in self._bar_buttons
        ]
        if not boxes:
            return
        inset = theme.pxf(s, 3)
        gx1 = min(box[0] for box in boxes) - inset
        gy1 = min(box[1] for box in boxes) - inset
        gx2 = max(box[2] for box in boxes) + inset
        gy2 = max(box[3] for box in boxes) + inset
        gw, gh = gx2 - gx1, gy2 - gy1
        self._bar_group_box = (gx1, gy1)
        self._bar_group_id = canvas.create_image(
            gx1,
            gy1,
            anchor="nw",
            image=theme.rounded_photo(
                canvas,
                gw,
                gh,
                radius=theme.pxf(s, BAR_HOVER_RADIUS + 1),
                fill=ACTION_GROUP_BG,
                key=("bargroup", gw, gh, s),
            ),
            tags="bar",
        )
        _ = pad

    def _stack_bar_items(self) -> None:
        """排工具栏的层次（自下而上）：卡片 → 衬底 → 悬停底 → 激活底 → 图标/文字。

        ⚠️ 两个坑，都踩过：
          1. 不能用 `tag_lower(card)` 把卡片压到底 —— 那会把它降到**暗化底图之下**，
             整条工具栏直接消失（截图里只剩选区框）。
          2. 不能靠创建顺序碰运气 —— 悬停底比卡片先创建，不显式抬高就会被卡片
             盖住，表现是"鼠标划过工具栏没有任何反馈"。
        所以这里统一按期望顺序依次 `tag_raise`（无参照物 = 抬到最顶）。
        """
        canvas = self._canvas
        if canvas is None:
            return
        canvas.tag_raise(self._bar_card_id)
        if self._bar_group_id is not None:
            canvas.tag_raise(self._bar_group_id)
        canvas.tag_raise(self._bar_hover_id)
        for key in self._bar_buttons:
            canvas.tag_raise(self._bar_active_ids[key])
        for key in self._bar_buttons:
            canvas.tag_raise(self._bar_icon_ids[key])
            canvas.tag_raise(self._bar_text_ids[key])
        # 分隔线没有单独引用，最后按 tag 整体抬一次（tag_raise 保持相对顺序，
        # 不会打乱上面刚排好的组内层次）
        canvas.tag_raise("bar")

    @staticmethod
    def _button_colors(key: str) -> tuple[str, str]:
        """(常态色, 悬停色)。"""
        if key == "close":
            return theme.D400, theme.R500
        if key == "confirm":
            return theme.G500, "#FFFFFF"
        if key in ACTION_KEYS:
            # 「识」「译」用品牌浅蓝：在一排灰白图标里，这两个是软件的主要功能，
            # 靠颜色把它们"提"出来（主人要求醒目）。又不会被误认成激活态 ——
            # 激活态是"蓝底 + 白字"，与这里明显不同。
            return theme.B300, "#FFFFFF"
        return theme.D100, "#FFFFFF"

    def _place_toolbar(self) -> None:
        """工具栏贴在选区**下方** 10px；下方放不下就翻到上方。"""
        canvas = self._canvas
        if canvas is None:
            return
        total_w, total_h = self._bar_size
        x1, y1, _x2, y2 = self.box
        offset = theme.pxf(self._scale, BAR_OFFSET)

        x = min(max(0, x1), max(0, self.width - total_w))
        y = y2 + offset
        if y + total_h > self.height:
            y = max(0, y1 - total_h - offset)
        self._bar_x, self._bar_y = x, y
        self._bar_box = (x, y, x + total_w, y + total_h)
        canvas.coords(self._bar_card_id, x, y)
        if self._bar_group_id is not None:
            canvas.coords(
                self._bar_group_id, x + self._bar_group_box[0], y + self._bar_group_box[1]
            )
        canvas.itemconfigure(self._bar_card_id, state="normal")
        nudge = theme.pxf(self._scale, ACTION_TEXT_NUDGE)
        for key, box in self._bar_buttons.items():
            bx = x + box[0]
            by = y + box[1]
            cx = bx + (box[2] - box[0]) / 2
            cy = by + (box[3] - box[1]) / 2
            canvas.coords(self._bar_icon_ids[key], cx, cy)
            canvas.coords(self._bar_text_ids[key], cx, cy - nudge)
            canvas.coords(self._bar_active_ids[key], cx, cy)

    def _bar_hit(self, x: int, y: int) -> str | None:
        """点 (x, y) 命中哪个工具栏按钮？命中测试自己算 —— 见模块头的说明。"""
        if self._bar_box is None:
            return None
        bx1, by1, bx2, by2 = self._bar_box
        if not (bx1 <= x <= bx2 and by1 <= y <= by2):
            return None
        for key, (ax1, ay1, ax2, ay2) in self._bar_buttons.items():
            if bx1 + ax1 <= x <= bx1 + ax2 and by1 + ay1 <= y <= by1 + ay2:
                return key
        return None

    def _inside_bar(self, x: int, y: int) -> bool:
        if self._bar_box is None:
            return False
        bx1, by1, bx2, by2 = self._bar_box
        return bx1 <= x <= bx2 and by1 <= y <= by2

    def _set_bar_hover(self, key: str | None) -> None:
        prev = self._bar_hover
        if key == prev:
            return
        canvas = self._canvas
        if canvas is None:
            return
        self._bar_hover = key
        # ⚠️ 必须先把**上一个**按钮刷回常态色。漏掉这一步，按钮被划过一次之后
        #    就永远停在悬停色上 —— 「译」「识」的悬停色是白色、常态是品牌浅蓝，
        #    于是表现为"鼠标划过后字色一直常驻白色"
        #    （主人 2026-10-08 反馈）。图标按钮其实也中了同一招，只是白与浅灰
        #    差别太小、肉眼没看出来。
        if prev is not None:
            self._paint_bar_item(prev, hovered=False)
        self._schedule_bar_tip(key)
        if key is None:
            canvas.itemconfigure(self._bar_hover_id, state="hidden")
            return
        ax1, ay1, _ax2, _ay2 = self._bar_buttons[key]
        canvas.coords(
            self._bar_hover_id,
            self._bar_x + ax1 + theme.pxf(self._scale, 2),
            self._bar_y + ay1 + theme.pxf(self._scale, 2),
        )
        canvas.itemconfigure(self._bar_hover_id, state="normal")
        self._paint_bar_item(key, hovered=True)

    # ---------- 工具栏悬停提示 ----------

    def _schedule_bar_tip(self, key: str | None) -> None:
        """安排/取消悬停提示。鼠标快速划过一排图标时不该一路冒气泡，所以延迟显示。"""
        win = self._win
        if self._bar_tip_job is not None:
            try:
                win.after_cancel(self._bar_tip_job)
            except (tk.TclError, AttributeError):
                pass
            self._bar_tip_job = None
        self._hide_bar_tip()
        if key is None or win is None:
            return
        self._bar_tip_key = key
        try:
            self._bar_tip_job = win.after(TIP_DELAY_MS, self._show_bar_tip)
        except tk.TclError:
            self._bar_tip_job = None

    def _show_bar_tip(self) -> None:
        """画出提示气泡：圆角深色胶囊，贴在按钮上方；上方放不下就翻到工具栏下面。"""
        self._bar_tip_job = None
        key = self._bar_tip_key
        canvas = self._canvas
        if (
            key is None
            or canvas is None
            or not self._bar_visible
            or self._bar_box is None
            or self._bar_hover != key
        ):
            return
        text = self._bar_tips.get(key)
        if not text or key not in self._bar_buttons:
            return

        s = self._scale
        font = tkfont.Font(font=FONT_SMALL)
        pad_x = theme.pxf(s, 10)
        pad_y = theme.pxf(s, 5)
        w = font.measure(text) + pad_x * 2
        h = font.metrics("linespace") + pad_y * 2

        bx1, _by1, bx2, _by2 = self._bar_buttons[key]
        cx = self._bar_x + (bx1 + bx2) / 2
        x = min(max(0, cx - w / 2), max(0, self.width - w))
        y = self._bar_y - h - theme.pxf(s, 8)
        if y < 0:
            y = self._bar_y + self._bar_size[1] + theme.pxf(s, 8)

        canvas.delete("bartip")
        card, shadow_pad = theme.flat_image(
            w,
            h,
            radius=theme.pxf(s, theme.RADIUS_SM),
            fill=theme.D900,
            outline=theme.D_SEP,
            outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
            shadow=theme.SHADOW_DARK,
        )
        canvas.create_image(
            x - shadow_pad,
            y - shadow_pad,
            anchor="nw",
            image=theme.photo(card, key=("bartip", w, h, s)),
            tags="bartip",
        )
        canvas.create_text(
            x + w / 2,
            y + h / 2,
            text=text,
            font=FONT_SMALL,
            fill="#FFFFFF",
            tags="bartip",
        )

    def _hide_bar_tip(self) -> None:
        self._bar_tip_key = None
        canvas = self._canvas
        if canvas is not None:
            try:
                canvas.delete("bartip")
            except tk.TclError:
                # 窗口已经销毁了。提示气泡的延迟任务是 `after` 排的，
                # 遮罩关掉时它可能还没跑 —— 这里兜一下，别让回调炸在销毁之后。
                pass

    def _bar_icon_photo(self, canvas: tk.Canvas, value: str, tint: str):
        """工具栏图标的 PhotoImage。

        色卡（`palette`）有两处特殊（见 `iconlib._palette` 与 `_ACCENT_ICONS`）：
          1. 额外带上**当前标注色** —— 它中间那格要实时显示当前颜色；
          2. **画得比别的图标大一圈**（19 → 24）：色卡是个半圆，视觉高度只有满格的
             一半，按同样的 19px 画出来会比邻居"轻"一大截，中间那格的颜色也小到
             看不清（主人 2026-10-08 实测反馈："图标不是半圆、而且过小，实时颜色
             不够显眼"）。
        """
        if value == "palette":
            return iconlib.icon_photo(
                canvas,
                value,
                tint,
                theme.pxf(self._scale, BAR_ICON_WIDE),
                accent=self.anno_color,
            )
        return iconlib.icon_photo(canvas, value, tint, theme.pxf(self._scale, BAR_ICON))

    def _paint_bar_item(self, key: str, *, hovered: bool = False) -> None:
        """按「激活 > 悬停 > 常态」的优先级重刷这一格。

        图标项与文字项（「识」「译」）共用同一套优先级，只是落到不同的 canvas
        item 上：图标项刷 image，文字项刷 text/fill，另一个通道隐藏。
        """
        canvas = self._canvas
        if canvas is None:
            return
        # ⚠️ 退场动画期间一律不刷：那时工具栏已由"抓屏位图"接管（原 item 已删除），
        #    任何一次重刷都会把它点亮（见 `_on_hover` 的说明）。
        if self._finishing:
            return
        kind, value, color, hover_color = self._bar_visuals[key]
        if self.tool == key:
            # 蓝底上必须用白色 —— 浅灰压在品牌蓝上对比度不够
            tint = "#FFFFFF"
        elif hovered:
            tint = hover_color
        else:
            tint = color

        if kind == "icon":
            canvas.itemconfigure(
                self._bar_icon_ids[key],
                image=self._bar_icon_photo(canvas, value, tint),
                state="normal" if self._bar_visible else "hidden",
            )
            canvas.itemconfigure(self._bar_text_ids[key], state="hidden")
        else:
            canvas.itemconfigure(self._bar_icon_ids[key], state="hidden")
            canvas.itemconfigure(
                self._bar_text_ids[key],
                text=value,
                fill=tint,
                state="normal" if self._bar_visible else "hidden",
            )

    def _refresh_tool_highlight(self) -> None:
        """把当前工具那格点亮（并刷新所有格子的颜色）。"""
        canvas = self._canvas
        if canvas is None:
            return
        for key, item in self._bar_active_ids.items():
            canvas.itemconfigure(
                item, state="normal" if (self.tool == key) else "hidden"
            )
            self._paint_bar_item(key, hovered=(self._bar_hover == key))

    def _hide_toolbar(self) -> None:
        """整条隐藏。⚠️ 必须按 tag 一刀切 —— 分隔线与衬底也是 `bar` 组的 item，
        逐个隐藏按钮而漏掉它们的话，退出编辑态后屏幕上会留下几根竖线和一块蓝底。"""
        canvas = self._canvas
        if canvas is None:
            return
        self._bar_visible = False
        canvas.itemconfigure("bar", state="hidden")
        self._bar_box = None
        self._bar_hover = None
        # 提示气泡不在 `bar` 这个 tag 组里（它是独立重建的），得单独收掉
        self._schedule_bar_tip(None)

    def _show_toolbar(self) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        self._bar_visible = True
        # 分隔线与衬底只有 tag、没有单独引用，先整体点亮；随后 `_paint_bar_item`
        # 会把每个按钮格子的"备用通道"重新压回 hidden。
        canvas.itemconfigure("bar", state="normal")
        canvas.itemconfigure(self._bar_hover_id, state="hidden")
        self._bar_hover = None
        for key in self._bar_visuals:
            self._paint_bar_item(key, hovered=False)
        self._place_toolbar()
        self._refresh_tool_highlight()

    # ---------- 底部提示条 ----------

    def _build_hint(self) -> None:
        self._set_hint(HINT_SELECTING)

    def _set_hint(self, text: str) -> None:
        """重建底部提示条。

        ⚠️ 必须**整条重画**而不是只改文字：胶囊宽度是按文字量出来的，
        只改文本会让文字溢出胶囊（第一版就是这么写的）。
        """
        canvas = self._canvas
        if canvas is None:
            return
        canvas.delete("hint")
        s = self._scale
        font = tkfont.Font(font=FONT_SMALL)
        w = font.measure(text) + theme.pxf(s, 32)
        h = font.metrics("linespace") + theme.pxf(s, 14)
        x = (self.width - w) // 2
        y = self.height - h - theme.pxf(s, 28)
        card = theme.rounded_image(
            w, h, h // 2, theme.D900, theme.D_SEP, theme.pxf(s, theme.STROKE_HAIRLINE)
        )
        canvas.create_image(
            x,
            y,
            anchor="nw",
            image=theme.photo(card, key=("hint", w, h, s)),
            tags="hint",
        )
        canvas.create_text(
            x + w / 2,
            y + h / 2,
            text=text,
            font=FONT_SMALL,
            fill=theme.D400,
            tags="hint",
        )

    # ---------- 弹出面板（调色板 / 线宽 / 文字输入）----------

    def _close_popup(self, *, animated: bool = False) -> None:
        """收起弹出面板。

        `animated=True` 时，调色板 / 线宽会走一遍**滑回 + 淡出**（与弹出对称）；
        其余情况立即删除 —— 打开别的面板前清场、退出遮罩等场景不该有动画。
        """
        canvas = self._canvas
        closing = self._popup
        self._popup = None
        self._popup_boxes = []
        if self._text_entry is not None:
            try:
                self._text_entry.destroy()
            except tk.TclError:
                pass
            self._text_entry = None
        if canvas is not None:
            if (
                animated
                and closing in _ANIMATED_POPUPS
                and self._popup_board is not None
            ):
                # item 由动画收尾自己删（见 `_animate_popup`）
                self._animate_popup(appearing=False)
            else:
                self._cancel_popup_anim()
                canvas.delete("popup")
        self._popup_board = None
        self._popup_item = None
        self._popup_sig = None
        # 文字是"边打边预览"的（见 _preview_text）：收面板时预览得一起收掉，
        # 否则按 Esc 取消输入后，选区上会留着一份没落笔的文字。
        if self._pending is not None:
            self._pending = None
            self._refresh_region()

    def _cancel_popup_anim(self) -> None:
        """取消进行中的面板过渡动画（连点开合时避免两个动画打架）。"""
        job = self._popup_job
        self._popup_job = None
        canvas = self._canvas
        if job is None or canvas is None:
            return
        try:
            canvas.after_cancel(job)
        except (tk.TclError, ValueError):
            pass

    def _animate_popup(self, *, appearing: bool) -> None:
        """面板的过渡动画：**位移 + alpha 淡入淡出**。

        ⚠️ 为什么整块要合成一张 PIL 图：Tk 的 Canvas item **没有 alpha 通道**，
           想淡入淡出只能逐帧换一张带不同 alpha 的位图；若色块仍是独立 item，
           它们会各淡各的、和卡片对不齐。所以 `_open_palette` / `_open_strokes`
           先把卡片 + 内容 + 选中环合成好，这里只负责逐帧 `putalpha` + 挪位置。
        ⚠️ 每帧 `theme.photo` 的缓存键刻意不含 `id(board)` —— 用
           (帧号, 方向, 面板签名) 就够唯一，否则每次开合都往那个"永不回收"的
           缓存里塞新条目。签名由 `_open_*` 给出，必须涵盖所有影响画面的状态
           （调色板→当前色、线宽→当前档），否则换了选中项会命中旧帧。
        """
        canvas = self._canvas
        board = self._popup_board
        item = self._popup_item
        if canvas is None or board is None or item is None:
            return
        self._cancel_popup_anim()
        s = self._scale
        shift = theme.pxf(s, POPUP_ANIM_SHIFT)
        # 面板总是"从按钮那一侧滑出来"：开在下方 → 起点更靠上（贴着工具栏边缘，
        # 向下滑到落点）；开在上方（兜底）→ 起点更靠下，向上滑。
        # ⚠️ 这里的符号原本写反了（起点落在更远处，看着像"从屏幕外浮上来"），
        #    与上面这句设计意图相反 —— 已修正。
        direction = -1 if self._popup_below else 1
        ox, oy = self._popup_origin
        base_alpha = board.getchannel("A")
        tail = (board.width, board.height, s, self._popup_sig)

        def frame(index: int) -> None:
            cv = self._canvas
            if cv is None:
                return
            ratio = index / POPUP_ANIM_STEPS
            alpha = ratio if appearing else 1.0 - ratio
            offset = direction * shift * (1.0 - ratio if appearing else ratio)
            img = board.copy()
            img.putalpha(base_alpha.point(lambda v: int(v * alpha)))
            try:
                cv.itemconfigure(
                    item,
                    image=theme.photo(img, key=("popupanim", index, appearing, tail)),
                )
                cv.coords(item, ox, oy + offset)
            except tk.TclError:
                return
            if index >= POPUP_ANIM_STEPS:
                # 收尾：job 已跑完，清掉引用，免得 `_cancel_popup_anim` 拿着一个
                # 已执行的 id 去 after_cancel（TclError 虽被吞掉，但留着是脏状态）。
                self._popup_job = None
                if not appearing:
                    try:
                        cv.delete(item)
                    except tk.TclError:
                        pass
                return
            self._popup_job = cv.after(POPUP_ANIM_INTERVAL, lambda: frame(index + 1))

        frame(0)

    def _popup_anchor(self, key: str, w: int, h: int) -> tuple[int, int, bool]:
        """弹出面板的落点：**横向对齐按钮中心，开在工具栏正下方**。

        调色板和线宽面板共用（两个面板行为一致，只是内容不同）。
        下方放不下（工具栏贴着屏幕底部）就翻到上方 —— 返回的 `below` 会决定
        `_animate_popup` 的滑出方向，翻上去时方向也跟着反过来。
        """
        s = self._scale
        btn = self._bar_buttons.get(key)
        anchor_x = self._bar_x + (btn[0] + btn[2]) / 2 if btn else self._bar_x + w / 2
        x = int(round(anchor_x - w / 2))
        x = min(max(0, x), max(0, self.width - w))
        gap = theme.pxf(s, 8)
        below = self._bar_y + self._bar_size[1] + gap
        if below + h <= self.height:
            return x, below, True
        return x, self._bar_y - h - gap, False

    def _open_palette(self) -> None:
        """调色板：一排圆形色块。**从色卡按钮下方滑出 + 淡入**（见 `_animate_popup`）。"""
        self._close_popup()
        # 面板和提示气泡会撞在一起 —— 开面板就先收气泡
        self._schedule_bar_tip(None)
        canvas = self._canvas
        if canvas is None:
            return
        s = self._scale
        cell = theme.pxf(s, 34)
        pad = theme.pxf(s, 10)
        radius = theme.pxf(s, theme.RADIUS_LG)
        w = pad * 2 + cell * len(ANNO_COLORS)
        h = pad * 2 + cell

        x, y, self._popup_below = self._popup_anchor("palette", w, h)

        # 整块合成一张图（卡片 + 色块 + 选中环）—— 动画要整块一起淡，理由见 `_animate_popup`
        board, shadow_pad = theme.flat_image(
            w, h, radius, theme.D900, outline=theme.D_SEP,
            outline_width=theme.pxf(s, theme.STROKE_HAIRLINE), shadow=theme.SHADOW_DARK,
        )
        dot = theme.pxf(s, 22)
        draw = ImageDraw.Draw(board)
        for index, color in enumerate(ANNO_COLORS):
            cx = shadow_pad + pad + cell * index + cell / 2
            cy = shadow_pad + pad + cell / 2
            swatch = theme.rounded_image(dot, dot, radius=dot // 2, fill=color)
            board.alpha_composite(swatch, (int(cx - dot / 2), int(cy - dot / 2)))
            if color == self.anno_color:
                ring = dot + theme.pxf(s, 8)
                draw.ellipse(
                    (cx - ring / 2, cy - ring / 2, cx + ring / 2, cy + ring / 2),
                    outline=theme.B500,
                    width=theme.pxf(s, 2),
                )
            self._popup_boxes.append(
                (
                    (
                        x + pad + cell * index,
                        y + pad,
                        x + pad + cell * (index + 1),
                        y + pad + cell,
                    ),
                    color,
                )
            )

        self._popup_board = board
        self._popup_sig = ("palette", self.anno_color)
        self._popup_origin = (x - shadow_pad, y - shadow_pad)
        self._popup_item = canvas.create_image(
            x - shadow_pad,
            y - shadow_pad,
            anchor="nw",
            image=theme.photo(board, key=("palette", w, h, s, self.anno_color)),
            tags="popup",
        )
        self._popup = "palette"
        self._animate_popup(appearing=True)

    def _open_strokes(self) -> None:
        """线宽：三档，用不同粗细的横线表示。

        **与调色板同款** —— 从「线宽」按钮下方滑出 + 淡入（见 `_animate_popup`）。
        """
        self._close_popup()
        self._schedule_bar_tip(None)
        canvas = self._canvas
        if canvas is None:
            return
        s = self._scale
        cell = theme.pxf(s, 34)
        pad = theme.pxf(s, 10)
        radius = theme.pxf(s, theme.RADIUS_LG)
        w = pad * 2 + cell * len(ANNO_WIDTHS)
        h = pad * 2 + cell

        x, y, self._popup_below = self._popup_anchor("stroke", w, h)

        # 整块合成一张图（卡片 + 三档线 + 选中环）—— 理由同调色板：动画要整块一起淡
        board, shadow_pad = theme.flat_image(
            w, h, radius, theme.D900, outline=theme.D_SEP,
            outline_width=theme.pxf(s, theme.STROKE_HAIRLINE), shadow=theme.SHADOW_DARK,
        )
        draw = ImageDraw.Draw(board)
        half = theme.pxf(s, 8)
        for index, width in enumerate(ANNO_WIDTHS):
            cx = shadow_pad + pad + cell * index + cell / 2
            cy = shadow_pad + pad + cell / 2
            line_w = max(1, int(round(width * s)))
            color = "#FFFFFF" if width == self.anno_width else theme.D400
            # ⚠️ PIL 的 `line` 端点只能是方的（没有 Tk 的 capstyle）—— 两端各补一个
            #    圆点，才和原来 `create_line(capstyle="round")` 的样子一致。
            draw.line((cx - half, cy, cx + half, cy), fill=color, width=line_w)
            cap = line_w / 2
            draw.ellipse(
                (cx - half - cap, cy - cap, cx + half + cap, cy + cap), fill=color
            )
            if width == self.anno_width:
                ring = theme.pxf(s, 28)
                draw.ellipse(
                    (cx - ring / 2, cy - ring / 2, cx + ring / 2, cy + ring / 2),
                    outline=theme.B500,
                    width=theme.pxf(s, 2),
                )
            self._popup_boxes.append(
                (
                    (
                        x + pad + cell * index,
                        y + pad,
                        x + pad + cell * (index + 1),
                        y + pad + cell,
                    ),
                    width,
                )
            )

        self._popup_board = board
        self._popup_sig = ("stroke", self.anno_width)
        self._popup_origin = (x - shadow_pad, y - shadow_pad)
        self._popup_item = canvas.create_image(
            x - shadow_pad,
            y - shadow_pad,
            anchor="nw",
            image=theme.photo(board, key=("strokes", w, h, s, self.anno_width)),
            tags="popup",
        )
        self._popup = "stroke"
        self._animate_popup(appearing=True)

    def _open_text_input(self, x: int, y: int) -> None:
        """自绘文字输入框（原来是 `simpledialog.askstring` 弹一个裸系统小窗）。"""
        self._close_popup()
        self._schedule_bar_tip(None)
        canvas = self._canvas
        assert canvas is not None
        s = self._scale
        w = theme.pxf(s, 240)
        h = theme.pxf(s, 44)
        px = min(max(theme.pxf(s, 8), x), self.width - w - theme.pxf(s, 8))
        # ⚠️ 输入框要落在**文字下方**：文字是从点击处往下写的（约 22px 高），
        #    原来只让开 14px，会压住刚打出来的预览文字。
        py = y + theme.pxf(s, 34)
        if py + h > self.height - theme.pxf(s, 8):
            py = max(theme.pxf(s, 8), y - h - theme.pxf(s, 8))

        card, shadow_pad = theme.flat_image(
            w, h, theme.pxf(s, theme.RADIUS_MD), theme.N0,
            outline=theme.N300, outline_width=theme.pxf(s, theme.STROKE_HAIRLINE),
            shadow=theme.SHADOW_FLOAT,
        )
        canvas.create_image(
            px - shadow_pad,
            py - shadow_pad,
            anchor="nw",
            image=theme.photo(card, key=("textinput", w, h, s)),
            tags="popup",
        )
        entry = tk.Entry(
            canvas,
            font=FONT_UI,
            relief="flat",
            bd=0,
            highlightthickness=0,
            bg=theme.N0,
            fg=theme.N900,
            insertbackground=theme.B500,
        )
        canvas.create_window(
            px + theme.pxf(s, 12),
            py + h / 2,
            anchor="w",
            window=entry,
            width=w - theme.pxf(s, 24),
            height=theme.pxf(s, 26),
            tags="popup",
        )
        # 边打边看：每敲一个字就把文字**按最终效果**渲染到选区上
        entry.bind("<KeyRelease>", lambda _e: self._preview_text())
        # ⚠️ 必须吃掉 Enter/Escape：遮罩窗口上也绑了这两个键，不拦的话
        #    输入文字时按回车会直接"完成并复制"。
        entry.bind("<Return>", lambda _e: (self._commit_text(), "break")[1])
        entry.bind("<Escape>", lambda _e: (self._close_popup(), "break")[1])
        entry.focus_set()
        self._text_entry = entry
        self._text_anchor = (x, y)
        self._popup = "text"

    def _preview_text(self) -> None:
        """把输入框里当前的文字渲染成临时标注（走的是和成品完全相同的渲染）。

        这样主人能实时看到文字落在哪、多大、什么颜色 —— 而不是确认之后才突然
        出现在别的地方。改造前既没有预览，文字还比点击处低 4px。
        """
        entry = self._text_entry
        anchor = self._text_anchor
        if entry is None or anchor is None:
            return
        try:
            value = entry.get()
        except tk.TclError:
            return
        ox, oy = self.box[0], self.box[1]
        self._pending = (
            Annotation(
                "text",
                (anchor[0] - ox, anchor[1] - oy),
                self.anno_color,
                self.anno_width,
                text=value,
                size=ANNO_FONT_SIZE,
            )
            if value
            else None
        )
        self._refresh_region()

    def _commit_text(self) -> None:
        entry = self._text_entry
        if entry is None:
            return
        try:
            value = entry.get()
        except tk.TclError:
            value = ""
        anchor = self._text_anchor
        # 先清掉临时标注，免得 `_close_popup` 多刷一次图（它会收掉残留的预览）
        self._pending = None
        self._close_popup()
        if value and anchor is not None:
            ox, oy = self.box[0], self.box[1]
            self.annotations.append(
                Annotation(
                    "text",
                    (anchor[0] - ox, anchor[1] - oy),
                    self.anno_color,
                    self.anno_width,
                    text=value,
                    size=ANNO_FONT_SIZE,
                )
            )
        self._refresh_region()

    def _popup_hit(self, x: int, y: int):
        """命中弹出面板里的某一项？返回该项的值。"""
        for box, value in self._popup_boxes:
            if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                return value
        return None

    # ---------- 事件分发 ----------

    def _on_press(self, event: tk.Event) -> None:
        # 弹出面板优先：点面板里的项就选中它，点面板外就收起
        if self._popup is not None:
            hit = self._popup_hit(event.x, event.y)
            if hit is not None:
                if self._popup == "palette":
                    self.anno_color = str(hit)
                    # 色卡图标中间那格显示的就是当前色 —— 选完立刻刷新它
                    self._paint_bar_item("palette", hovered=self._bar_hover == "palette")
                else:
                    self.anno_width = int(hit)
                self._close_popup(animated=True)
                self._refresh_region()
                return
            if self._popup == "text":
                # 点输入框外面 = 确认这次输入（等同按回车）
                self._commit_text()
                return
            # ⚠️ 点在**工具栏按钮**上时不要在这里收起 —— 交给下面的 `_on_bar` 按
            #    "切换"语义处理。否则会"先 close 再 open"，表现为点色卡没反应
            #    （主人 2026-10-08 反馈："再次点击色卡按钮应将其收回关闭"）。
            if self._bar_hit(event.x, event.y) is None:
                self._close_popup(animated=True)

        # 工具栏次优先
        key = self._bar_hit(event.x, event.y)
        if key is not None:
            self._on_bar(key)
            return
        if self._inside_bar(event.x, event.y):
            return

        if self.state == "selecting":
            self._drag_anchor = (event.x, event.y)
            # ⚠️ 顺序不能反：`_clear_hot()` 会把 `_hot_rect` 抹掉，所以要**先**把
            #    当时高亮的窗口存下来 —— 松手时靠它判断这次是"单击吸附窗口"
            #    还是"拖拽自由框选"。
            self._press_at = (event.x, event.y)
            self._press_hot = self._hot_rect
            self._hide_magnifier()
            self._hide_region()  # 先藏旧亮版，免得拖动时在旧位置残留一帧
            self._clear_hot()
            return

        # 编辑阶段：角手柄永远优先（不管当前选没选标注工具）
        handle = self._hit_handle(event.x, event.y)
        if handle is not None:
            self._resize_handle = handle
            self._hide_region()
            return

        if self.tool is not None:
            self._begin_annotation(event.x, event.y)
            return

        # 没选工具时：框内拖动 = 移动整个选区；框外点击 = 回到重选
        if self._inside_box(event.x, event.y):
            self._move_origin = ((event.x, event.y), self.box)
            self._hide_region()
        else:
            self._back_to_selecting()

    def _on_motion(self, event: tk.Event) -> None:
        if self.state == "selecting":
            if self._drag_anchor is not None:
                self._draw_selection(
                    self._drag_anchor[0], self._drag_anchor[1], event.x, event.y
                )
            else:
                self._update_magnifier(event.x, event.y)
            return

        if self._resize_handle is not None:
            self._resize_to(event.x, event.y)
        elif self._move_origin is not None:
            self._move_to(event.x, event.y)
        else:
            self._drag_annotation(event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        if self.state == "selecting":
            if self._drag_anchor is None:
                return
            x1, x2 = sorted((self._drag_anchor[0], event.x))
            y1, y2 = sorted((self._drag_anchor[1], event.y))
            self._drag_anchor = None
            press_at, press_hot = self._press_at, self._press_hot
            self._press_at = None
            self._press_hot = None

            # 单击（几乎没位移）+ 按下时鼠标下有高亮窗口 → 吸附到那个窗口。
            # 判在**松手**这一刻，是因为按下时还分不清"想点选窗口"还是"想拖拽
            # 框选"；判完之后两种意图互不干扰：想自由框选就拖，想整窗截图就点。
            if press_at is not None and press_hot is not None:
                moved = max(
                    abs(event.x - press_at[0]), abs(event.y - press_at[1])
                )
                if moved <= SNAP_CLICK_TOLERANCE and self._snap_to_window(press_hot):
                    return

            if x2 - x1 < MIN_SELECTION or y2 - y1 < MIN_SELECTION:
                # 误触：还原。没选过就回到「整屏变暗」的初始态 ——
                # 漏掉 else 的话，屏幕上会残留一个拖到一半的小亮块。
                self._draw_selection(*self.box)
                if self._region_active:
                    self._refresh_region()
                else:
                    self._hide_region()
                return
            self.box = (x1, y1, x2, y2)
            self._region_active = True
            self._enter_editing()
            return

        if self._resize_handle is not None:
            self._resize_handle = None
            self._after_box_change()
        elif self._move_origin is not None:
            self._move_origin = None
            self._after_box_change()
        else:
            self._commit_annotation(event.x, event.y)

    def _on_hover(self, event: tk.Event) -> None:
        # ⚠️ 退场动画期间**完全不理鼠标**：鼠标停在遮罩上时 Tk 会派发 Motion，
        #    经 `_set_bar_hover` → `_paint_bar_item` 把已经删除/隐藏的工具栏 item
        #    重新点亮 —— 表现就是"动画里功能栏根本没淡出"（这个 bug 的真凶）。
        if self._finishing:
            return
        # 工具栏悬停反馈（比选区逻辑优先）
        self._set_bar_hover(self._bar_hit(event.x, event.y))

        if self.state == "selecting":
            if self._drag_anchor is None:
                self._update_magnifier(event.x, event.y)
                self._update_hot_window(event.x, event.y)
            return

        # 编辑阶段：给出"可缩放 / 可移动"的光标提示
        canvas = self._canvas
        if canvas is None:
            return
        if self._hit_handle(event.x, event.y) is not None:
            canvas.configure(cursor="sizing")
        elif self.tool is None and self._inside_box(event.x, event.y):
            canvas.configure(cursor="fleur")
        else:
            canvas.configure(cursor="crosshair" if self.tool else "arrow")

    def _on_leave(self) -> None:
        self._hide_magnifier()
        self._set_bar_hover(None)
        self._clear_hot()

    def _on_escape(self) -> None:
        """Esc：有弹出面板就先收面板，否则**一次**直接退出整个截屏。

        改造前是三级：收面板 → 退编辑态 → 才取消截屏，于是框选完成后要按两次
        Esc 才退得掉（主人 2026-10-08 反馈）。现在编辑态不再"退一步"，一次到底。
        想重新框选的话，点选区外的空白处就行（见 `_on_press`）。
        """
        if self._popup is not None:
            self._close_popup()
            return
        self._finish(None)

    def _on_enter(self) -> None:
        if self._popup is not None:
            return
        if self.state == "selecting":
            self._enter_editing()
        else:
            self._finish("copy")

    # ---------- 窗口自动检测（框选态的"贴窗口"体验）----------

    def _update_hot_window(self, x: int, y: int) -> None:
        """鼠标下的窗口高亮。

        ⚠️ 遮罩自己是全屏置顶窗口，`WindowFromPoint` 永远只会返回遮罩本身，
        所以必须**从 Z-order 顶端往下遍历**、跳过自身，找第一个包含该点的可见
        顶层窗口。遍历一次约 1~3ms，用 `HOT_CHECK_INTERVAL` 节流。
        """
        now = time.monotonic()
        if now - self._last_hot_check < HOT_CHECK_INTERVAL:
            return
        self._last_hot_check = now

        hwnd, rect = self._window_at(x + self.origin[0], y + self.origin[1])
        if hwnd == self._hot_hwnd and rect == self._hot_rect:
            return
        self._hot_hwnd = hwnd
        self._hot_rect = rect
        self._draw_hot(rect)

    def _window_at(self, sx: int, sy: int):
        """屏幕坐标下的最上层"值得高亮"的窗口 → (hwnd, 矩形)；没有则 (0, None)。

        矩形是窗口的**可见**边界（见 `visible_frame`），不是 `GetWindowRect`
        那个含不可见阴影边的"窗口矩形"。
        """
        try:
            user32 = ctypes.windll.user32
        except (AttributeError, OSError):
            return 0, None
        try:
            dwmapi = ctypes.windll.dwmapi
        except (AttributeError, OSError):
            dwmapi = None

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        GW_HWNDNEXT = 2
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        #: DWM 的"扩展边框"= 肉眼看到的窗口边界
        DWMWA_EXTENDED_FRAME_BOUNDS = 9

        user32.GetTopWindow.restype = ctypes.c_void_p
        user32.GetWindow.restype = ctypes.c_void_p
        user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        # ⚠️ HWND 是 64 位指针。不声明 argtypes 的话 ctypes 会把它当 32 位 int 传，
        #    在 64 位进程里属于未定义行为（本机句柄值恰好都在低 32 位，才一直没炸）。
        user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT)]
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        user32.IsIconic.argtypes = [ctypes.c_void_p]
        if dwmapi is not None:
            dwmapi.DwmGetWindowAttribute.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_void_p,
                ctypes.c_uint,
            ]

        def visible_frame(handle: int):
            """窗口**可见**边界（RECT）；两次取值都失败则 None。

            ⚠️ 这是"吸附范围比窗口实际范围大了一点"的根因：Win10 起
            `GetWindowRect` 返回的窗口矩形在左、右、下各含一圈**不可见**的 DWM
            阴影边框（实测各 7px，最大化时那圈还会跑到屏幕外）。拿它当吸附范围，
            截出来的图就会多带一圈桌面。`DWMWA_EXTENDED_FRAME_BOUNDS` 给的才是
            肉眼看到的边界。DWM 不可用时退回 `GetWindowRect`。
            """
            bounds = RECT()
            if dwmapi is not None:
                try:
                    if (
                        dwmapi.DwmGetWindowAttribute(
                            ctypes.c_void_p(handle),
                            DWMWA_EXTENDED_FRAME_BOUNDS,
                            ctypes.byref(bounds),
                            ctypes.sizeof(bounds),
                        )
                        == 0
                    ):
                        return bounds
                except (AttributeError, OSError):
                    pass
            rect = RECT()
            if user32.GetWindowRect(ctypes.c_void_p(handle), ctypes.byref(rect)):
                return rect
            return None

        mine = set()
        for widget in (self._win, self.master):
            try:
                mine.add(int(widget.frame(), 16))
            except (tk.TclError, ValueError, AttributeError):
                continue

        hwnd = user32.GetTopWindow(None)
        guard = 0
        while hwnd and guard < 600:
            guard += 1
            handle = int(hwnd)
            if handle not in mine:
                if user32.IsWindowVisible(handle) and not user32.IsIconic(handle):
                    ex_style = user32.GetWindowLongW(handle, GWL_EXSTYLE)
                    if not (ex_style & WS_EX_TOOLWINDOW):
                        rect = visible_frame(handle)
                        if rect is not None:
                            if (
                                rect.right - rect.left >= 40
                                and rect.bottom - rect.top >= 40
                                and rect.left <= sx < rect.right
                                and rect.top <= sy < rect.bottom
                            ):
                                return handle, (
                                    rect.left,
                                    rect.top,
                                    rect.right,
                                    rect.bottom,
                                )
            hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)
        return 0, None

    def _draw_hot(self, rect) -> None:
        """画出"鼠标下这个窗口"：内容高光 + 蓝色虚线框 + 尺寸胶囊。

        主人 2026-10-08 要求"吸附上时内容高光" —— 只有一圈虚线时，被暗化的窗口
        内容依旧看不清，认不出"就是它"。这里把该窗口区域的原图贴回暗化底图之上，
        与选区亮版同一套做法（只靠边框区分：绿色实线 = 已选中，蓝色虚线 = 待吸附）。
        """
        canvas = self._canvas
        if canvas is None:
            return
        canvas.delete("hot")
        if rect is None:
            self._hide_hot_region()
            return
        ox, oy = self.origin
        x1, y1 = rect[0] - ox, rect[1] - oy
        x2, y2 = rect[2] - ox, rect[3] - oy
        if x2 <= 0 or y2 <= 0 or x1 >= self.width or y1 >= self.height:
            self._hide_hot_region()
            return

        # 内容高光：先夹到屏幕内再裁剪（窗口可能有一部分在屏幕外）
        cx1, cy1 = max(0, x1), max(0, y1)
        cx2, cy2 = min(self.width, x2), min(self.height, y2)
        if cx2 - cx1 >= 1 and cy2 - cy1 >= 1:
            region = self.shot.image.crop((cx1, cy1, cx2, cy2))
            # ⚠️ 同 `_refresh_region`：先把新图交给 Canvas，最后才替换 Python 侧
            #    引用。反过来的话旧 PhotoImage 会在 Canvas 仍指向它时被 GC，
            #    Tk 端图像数据随之释放，屏幕上就是一片彩色噪点。
            photo = ImageTk.PhotoImage(region)
            canvas.coords(self._hot_region_id, cx1, cy1)
            canvas.itemconfigure(self._hot_region_id, image=photo, state="normal")
            self._hot_photo = photo
        else:
            self._hide_hot_region()

        canvas.create_rectangle(
            x1, y1, x2, y2, outline=HOT_ACCENT, width=2, dash=(9, 6), tags="hot"
        )
        self._draw_size_badge(
            x1,
            y1,
            f"{x2 - x1} × {y2 - y1}",
            fill=theme.B500,
            tag="hot",
        )

    def _hide_hot_region(self) -> None:
        canvas = self._canvas
        if canvas is not None:
            canvas.itemconfigure(self._hot_region_id, state="hidden")

    def _clear_hot(self) -> None:
        canvas = self._canvas
        if canvas is not None:
            canvas.delete("hot")
        self._hide_hot_region()
        self._hot_hwnd = 0
        self._hot_rect = None

    # ---------- 选区绘制 ----------

    def _draw_size_badge(
        self,
        x: int,
        y: int,
        text: str,
        *,
        fill: str = theme.D900,
        tag: str = "sel",
    ) -> None:
        """尺寸标签：圆角胶囊 + 白字。

        改造前是**裸白字**直接压在屏幕上 —— 遇到浅色背景（白底文档、浅灰网页）
        直接看不见。现在给深色胶囊底，任何背景下都清晰。
        """
        canvas = self._canvas
        if canvas is None:
            return
        font = tkfont.Font(font=FONT_SMALL)
        s = self._scale
        pad_x = theme.pxf(s, 8)
        pad_y = theme.pxf(s, 3)
        w = font.measure(text) + pad_x * 2
        h = font.metrics("linespace") + pad_y * 2
        above = y > h + theme.pxf(s, 8)
        by = y - h - theme.pxf(s, 4) if above else y + theme.pxf(s, 4)
        bx = x
        photo = theme.rounded_photo(
            canvas,
            w,
            h,
            radius=theme.pxf(s, theme.RADIUS_SM),
            fill=fill,
            key=("badge", w, h, fill, s),
        )
        canvas.create_image(bx, by, anchor="nw", image=photo, tags=tag)
        canvas.create_text(
            bx + w / 2,
            by + h / 2,
            text=text,
            font=FONT_SMALL,
            fill="#FFFFFF",
            tags=tag,
        )

    def _draw_selection(self, ax: int, ay: int, bx: int, by: int) -> None:
        canvas = self._canvas
        assert canvas is not None
        x1, x2 = sorted((max(0, min(ax, self.width)), max(0, min(bx, self.width))))
        y1, y2 = sorted((max(0, min(ay, self.height)), max(0, min(by, self.height))))

        canvas.coords(self._rect_id, x1, y1, x2, y2)
        canvas.itemconfigure(self._rect_id, state="normal")

        radius = theme.pxf(self._scale, HANDLE_RADIUS)
        corners = ((x1, y1), (x2, y1), (x1, y2), (x2, y2))
        for index, (cx, cy) in enumerate(corners):
            canvas.coords(
                self._handle_ids[index],
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
            )
            canvas.itemconfigure(self._handle_ids[index], state="normal")

        # 尺寸标签（每次重建：胶囊宽度随文字变）
        canvas.delete("sizebadge")
        self._draw_size_badge(x1, y1, f"{x2 - x1} × {y2 - y1}", tag="sizebadge")

        # 拖动过程中实时刷新亮版图，让选区内容**即时**变亮。
        #
        # 主人 2026-10-08 要求：「框选选择时内容就高亮，而不是框选结束后才高亮」。
        # 旧实现刻意在拖拽期间不重建亮版图（只移动边框），担心"大面积图像高频重建
        # 既卡顿又出伪影"。实测证明这个担心是多余的：整屏 2880×1800 重建一次只要
        # ~19ms（crop 4ms + PhotoImage 15ms），拖拽全程单帧平均 1.8ms。
        # 这里再节流到约 30fps，兼顾老机器。
        #
        # ⚠️ 只在拖动中刷新：初始的「整屏默认选中」若也刷，整个屏幕都会变亮，
        # 遮罩就形同虚设了。
        if self._is_dragging():
            self._refresh_region((x1, y1, x2, y2), throttle=True)

    def _is_dragging(self) -> bool:
        """用户是否正拖着鼠标改变选区：框选拖拽 / 拖角手柄 / 整体平移，都算。"""
        return (
            self._drag_anchor is not None
            or self._resize_handle is not None
            or self._move_origin is not None
        )

    # ---------- 放大镜 ----------

    def _update_magnifier(self, x: int, y: int) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        if not (0 <= x < self.width and 0 <= y < self.height):
            self._hide_magnifier()
            return

        s = self._scale
        half = MAG_SRC // 2
        left = min(max(0, x - half), self.width - MAG_SRC)
        top = min(max(0, y - half), self.height - MAG_SRC)
        region = self.shot.image.crop(
            (left, top, left + MAG_SRC, top + MAG_SRC)
        ).resize((theme.pxf(s, MAG_SIZE), theme.pxf(s, MAG_SIZE)), Image.NEAREST)

        pixel = self.shot.image.getpixel((x, y))
        color = f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"
        self._cursor_color = color

        # 十字准星（画在放大图边缘，不遮中心像素）
        draw = ImageDraw.Draw(region)
        center = theme.pxf(s, MAG_SIZE) // 2
        arm = theme.pxf(s, 10)
        for points in (
            ((center, 0), (center, center - arm)),
            ((center, center + arm), (center, theme.pxf(s, MAG_SIZE))),
            ((0, center), (center - arm, center)),
            ((center + arm, center), (theme.pxf(s, MAG_SIZE), center)),
        ):
            draw.line(list(points), fill=ACCENT)

        self._mag_photo = ImageTk.PhotoImage(region)

        # 面板排版：行距 / 宽度都在 _build_magnifier_items 里按实测字体算好并固定。
        pad = theme.pxf(s, MAG_PAD)
        line_h = self._mag_line_h
        panel_w = self._mag_panel_w
        panel_h = self._mag_panel_h
        text_xy = f"坐标 {x}, {y}"
        text_color = f"色值 {color}"
        text_hint = "按 Ctrl+C 复制色值"

        px = x + theme.pxf(s, 22)
        py = y + theme.pxf(s, 22)
        if px + panel_w > self.width:
            px = x - panel_w - theme.pxf(s, 22)
        if py + panel_h > self.height:
            py = y - panel_h - theme.pxf(s, 22)
        px = max(0, px)
        py = max(0, py)

        # ⚠️ 圆角卡片是带阴影的（图上多出一圈 pad），绘制坐标要整体减掉它
        shift = self._mag_pad
        info_x = px + pad
        info_y = py + theme.pxf(s, MAG_SIZE) + pad * 2
        swatch = theme.pxf(s, MAG_SWATCH)
        swatch_gap = theme.pxf(s, MAG_SWATCH_GAP)
        color_x = info_x + swatch + swatch_gap
        # 色块垂直居中于它那一行文字：文字从行顶起画，字形只占中间一段。
        swatch_y1 = info_y + line_h + (line_h - swatch) // 2

        canvas.coords(self._mag_ids["bg"], px - shift, py - shift)
        canvas.coords(self._mag_ids["img"], px + pad, py + pad)
        canvas.itemconfigure(self._mag_ids["img"], image=self._mag_photo)
        canvas.coords(self._mag_ids["swatch"], info_x, swatch_y1)
        canvas.itemconfigure(
            self._mag_ids["swatch"], image=self._swatch_photo(color, swatch)
        )
        canvas.coords(self._mag_ids["xy"], info_x, info_y)
        canvas.itemconfigure(self._mag_ids["xy"], text=text_xy)
        canvas.coords(self._mag_ids["color"], color_x, info_y + line_h)
        canvas.itemconfigure(self._mag_ids["color"], text=text_color)
        canvas.coords(self._mag_ids["hint"], info_x, info_y + line_h * 2)
        # 重置为灰色：上一轮可能刚复制过（那时是绿的）
        canvas.itemconfigure(self._mag_ids["hint"], text=text_hint, fill=MAG_HINT_FG)

        for item in self._mag_ids.values():
            canvas.itemconfigure(item, state="normal")

    def _swatch_photo(self, color: str, size: int):
        """色值前面的小色块（圆角小方块，比裸矩形精致一点）。"""
        canvas = self._canvas
        assert canvas is not None
        return theme.rounded_photo(
            canvas, size, size, radius=theme.pxf(self._scale, 3), fill=color,
            key=("magswatch", size, color),
        )

    def _hide_magnifier(self) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        for item in self._mag_ids.values():
            canvas.itemconfigure(item, state="hidden")

    def _hide_region(self) -> None:
        if self._canvas is not None and self._region_id is not None:
            self._canvas.itemconfigure(self._region_id, state="hidden")

    def _copy_color(self) -> None:
        try:
            import pyperclip

            pyperclip.copy(self._cursor_color)
        except Exception:  # noqa: BLE001
            return
        canvas = self._canvas
        if canvas is not None:
            canvas.itemconfigure(
                self._mag_ids["hint"],
                text=f"已复制 {self._cursor_color}",
                fill=MAG_HINT_OK,
            )

    # ---------- 阶段切换 ----------

    def _snap_to_window(self, rect) -> bool:
        """把选区吸附到屏幕坐标的 `rect`（某个窗口的可见边界）并进入编辑态。

        返回 False 表示该矩形落在屏幕外或小得离谱 —— 调用方应继续走普通框选。
        """
        ox, oy = self.origin
        x1 = max(0, rect[0] - ox)
        y1 = max(0, rect[1] - oy)
        x2 = min(self.width, rect[2] - ox)
        y2 = min(self.height, rect[3] - oy)
        if x2 - x1 < MIN_SELECTION or y2 - y1 < MIN_SELECTION:
            return False
        self.box = (x1, y1, x2, y2)
        self._region_active = True
        self._draw_selection(x1, y1, x2, y2)
        self._enter_editing()
        return True

    def _enter_editing(self) -> None:
        self.state = "editing"
        self._region_active = True
        self._hide_magnifier()
        self._clear_hot()
        self._refresh_region()
        if self._region_id is not None and self._canvas is not None:
            self._canvas.itemconfigure(self._region_id, state="normal")
        self._show_toolbar()
        self._set_hint(HINT_EDITING)

    def _back_to_selecting(self) -> None:
        self.state = "selecting"
        # 选区还是上一次用户选出来的那个，亮版继续显示
        self._region_active = True
        self.annotations.clear()
        self.tool = None
        # 回到框选态，上一次的"按下落点"作废（否则可能拿旧坐标去判吸附）
        self._press_at = None
        self._press_hot = None
        self._close_popup()
        self._refresh_tool_highlight()
        self._hide_toolbar()
        self._refresh_region()
        self._set_hint(HINT_SELECTING)

    def _current_region(self) -> Image.Image:
        x1, y1, x2, y2 = self.box
        region = self.shot.image.crop((x1, y1, x2, y2))
        return render_annotations(region, self.annotations)

    def _refresh_region(
        self, box: tuple[int, int, int, int] | None = None, *, throttle: bool = False
    ) -> None:
        """重绘选区亮版（含标注）。

        throttle=True 时限制刷新频率，避免拖拽过程中反复重建大图导致卡顿。
        """
        canvas = self._canvas
        if canvas is None:
            return

        box = box or self.box
        x1, y1, x2, y2 = box
        if x2 - x1 < 1 or y2 - y1 < 1:
            return

        if throttle:
            now = time.monotonic()
            if now - self._last_region_update < REGION_REFRESH_INTERVAL:
                return
            self._last_region_update = now

        region = self.shot.image.crop(box)
        # 拖拽中 / 输入中的临时标注也要画进去 —— 它和正式标注走的是**同一套渲染**，
        # 所以"预览"就是"成品"，松手时不会有位置跳变（见 _drag_annotation）。
        annos = list(self.annotations)
        if self._pending is not None:
            annos.append(self._pending)
        if annos:
            region = render_annotations(region, annos)

        # ⚠️ 顺序至关重要：必须先把新图交给 Canvas，最后才替换 Python 侧引用。
        # 若先替换 self._region_photo，旧 PhotoImage 会在 Canvas 仍指向它时被 GC，
        # Tk 端图像数据随之释放，Canvas 就会渲染出未初始化内存 ——
        # 表现为框选时边缘出现彩色（紫）条纹。
        photo = ImageTk.PhotoImage(region)
        canvas.coords(self._region_id, x1, y1)
        canvas.itemconfigure(self._region_id, image=photo, state="normal")
        self._region_photo = photo

    # ---------- 标注 ----------

    def _inside_box(self, x: int, y: int) -> bool:
        x1, y1, x2, y2 = self.box
        return x1 <= x <= x2 and y1 <= y <= y2

    # ---------- 移动 / 缩放选区 ----------

    def _hit_handle(self, x: int, y: int, tolerance: int = 12) -> int | None:
        """命中哪个角手柄？0 左上 / 1 右上 / 2 左下 / 3 右下。"""
        x1, y1, x2, y2 = self.box
        for index, (cx, cy) in enumerate(((x1, y1), (x2, y1), (x1, y2), (x2, y2))):
            if abs(x - cx) <= tolerance and abs(y - cy) <= tolerance:
                return index
        return None

    def _resize_to(self, x: int, y: int) -> None:
        x1, y1, x2, y2 = self.box
        index = self._resize_handle
        if index == 0:
            x1, y1 = x, y
        elif index == 1:
            x2, y1 = x, y
        elif index == 2:
            x1, y2 = x, y
        elif index == 3:
            x2, y2 = x, y

        x1, x2 = sorted((max(0, min(x1, self.width)), max(0, min(x2, self.width))))
        y1, y2 = sorted((max(0, min(y1, self.height)), max(0, min(y2, self.height))))
        if x2 - x1 < MIN_SELECTION or y2 - y1 < MIN_SELECTION:
            return
        self.box = (x1, y1, x2, y2)
        self._draw_selection(*self.box)

    def _move_to(self, x: int, y: int) -> None:
        """整框平移，限制在屏幕内。"""
        assert self._move_origin is not None
        (origin_x, origin_y), (bx1, by1, bx2, by2) = self._move_origin
        width, height = bx2 - bx1, by2 - by1
        left = min(max(0, bx1 + x - origin_x), self.width - width)
        top = min(max(0, by1 + y - origin_y), self.height - height)
        self.box = (left, top, left + width, top + height)
        self._draw_selection(*self.box)

    def _after_box_change(self) -> None:
        """选区移动/缩放结束后：重绘亮版（标注会跟着走），工具栏也随之定位。"""
        self._refresh_region()
        self._place_toolbar()

    def _begin_annotation(self, x: int, y: int) -> None:
        if self.tool is None:
            if not self._inside_box(x, y):
                self._back_to_selecting()
            return
        if not self._inside_box(x, y):
            return

        if self.tool == "text":
            self._open_text_input(x, y)
            return

        self._anno_start = (x, y)
        self._pending = None
        # 让这一次拖动的**第一帧**必定刷新：`_refresh_region(throttle=True)` 是按
        # 上一次刷新时间节流的，刚提交完上一个标注时它会把第一帧吃掉，
        # 表现是"开始拖了但标注还没出现"。
        self._last_region_update = 0.0
        if self.tool == "pen":
            self._pen_points = [(x, y)]

    def _drag_annotation(self, x: int, y: int) -> None:
        """拖拽中的标注**直接用 PIL 渲染**，不再用 Tk Canvas item 画预览。

        改造前预览是 `create_rectangle / create_oval / create_line`，松手后换成
        PIL 的 `render_annotations` —— 两套描边语义不同（Tk 的描边**以路径为中心**、
        PIL 的描边**向内**），于是"完成瞬间"标注会跳 1~2px。主人反馈的
        "不管是箭头、圆圈还是文字，完成后位置会偏移一点点"就是这个。

        现在预览和成品走**同一条渲染路径**，想偏也偏不了。顺带两个收益：
        马赛克拖动时就能看到真实效果（以前只画个红框）、画笔的线宽与端点也和
        成品一致了。

        代价是拖动中每帧要重建选区亮版图 —— 实测 700×500 的选区一次约 7ms，
        配 `_refresh_region(throttle=True)` 的 30ms 节流完全够用。
        """
        if self._anno_start is None or self.tool is None:
            return
        sx, sy = self._anno_start
        x = min(max(x, self.box[0]), self.box[2])
        y = min(max(y, self.box[1]), self.box[3])
        ox, oy = self.box[0], self.box[1]

        if self.tool == "pen":
            self._pen_points.append((x, y))
            if len(self._pen_points) < 2:
                return
            coords = tuple((px - ox, py - oy) for px, py in self._pen_points)
        elif self.tool == "arrow":
            coords = ((sx - ox, sy - oy), (x - ox, y - oy))
        else:
            coords = (
                min(sx, x) - ox,
                min(sy, y) - oy,
                max(sx, x) - ox,
                max(sy, y) - oy,
            )

        self._pending = Annotation(self.tool, coords, self.anno_color, self.anno_width)
        self._refresh_region(throttle=True)

    @staticmethod
    def _is_meaningful(anno: Annotation) -> bool:
        """过滤"点一下没拖"产生的零尺寸标注。

        原逻辑只对矩形/椭圆/马赛克做了这层过滤，箭头点一下会留下一个看不见的
        退化标注（`start == end`），撤销时才会发现"多了一步"。
        """
        if anno.kind == "pen":
            return len(anno.coords) >= 2
        if anno.kind == "arrow":
            (x1, y1), (x2, y2) = anno.coords
            return abs(x2 - x1) > 2 or abs(y2 - y1) > 2
        if anno.kind == "text":
            return bool(anno.text)
        x1, y1, x2, y2 = anno.coords
        return x2 - x1 > 2 and y2 - y1 > 2

    def _commit_annotation(self, x: int, y: int) -> None:
        """松手落笔：把拖拽中的临时标注原样转成正式标注。

        `x` / `y` 现在用不上了（临时标注在 `_drag_annotation` 里已经跟着每次移动
        更新过），保留参数只是为了不动调用点。
        """
        pending = self._pending
        self._anno_start = None
        self._pen_points = []
        self._pending = None
        if pending is not None and self._is_meaningful(pending):
            self.annotations.append(pending)
        self._refresh_region()

    def _clear_preview(self) -> None:
        """丢掉拖拽中的临时标注（已落笔的标注不受影响）。"""
        self._pending = None

    # ---------- 工具栏动作 ----------

    def _on_bar(self, key: str) -> None:
        if key in TOOL_KEYS:
            self.tool = None if self.tool == key else key
            self._close_popup()
            self._refresh_tool_highlight()
            return
        if key == "palette":
            if self._popup == "palette":
                # 已打开 → 收回（带动画），实现"点击切换显隐"
                self._close_popup(animated=True)
            else:
                self._open_palette()
            return
        if key == "stroke":
            if self._popup == "stroke":
                # 已打开 → 收回（带动画），与调色板一致的"点击切换显隐"
                self._close_popup(animated=True)
            else:
                self._open_strokes()
            return
        if key == "undo":
            # 撤销不是面板开关，但面板开着时点它说明注意力已转移 —— 和"点面板外"
            # 一样收起（其余工具/动作分支也都会收，只有这里原来漏了）。
            self._close_popup(animated=True)
            if self.annotations:
                self.annotations.pop()
                self._refresh_region()
            return
        if key == "close":
            # 「取消」：带动画退场（功能栏渐隐）
            self._finish(None, animated=True)
            return
        if key == "confirm":
            # 「完成」：同上 —— 两个按钮的退场观感要一致
            self._finish("copy", animated=True)
            return
        if key in {"ocr", "translate"}:
            self._emit_action(key)
            return
        if key in {"save", "copy", "pin"}:
            self._finish(key)

    def _emit_action(self, key: str) -> None:
        """把「识」「译」交给 app，**随即退出框选**。

        点「识」或「译」就意味着"我要看结果了"，遮罩再留着也没用 ——
        主人要求：调出结果窗口后自动退出截屏框选。要看译文，改在结果窗口里点
        左侧的「译文」标签（那会自动触发翻译）。

        没有注入回调时退回旧行为（关闭遮罩并把动作带回给调用方）。

        顺序很关键：**先**让 app 把结果窗口立起来，**再**关遮罩 —— 反过来的话
        遮罩销毁时可能把刚创建的结果窗口一起带下水。
        """
        if self.on_action is None:
            self._finish(key)
            return
        try:
            self.on_action(key, self._current_region())
        finally:
            self._finish(None)

    def _finish(self, action: str | None, *, animated: bool = False) -> None:
        """收工退出。

        `animated=True`（点工具栏的「取消」/「完成」）时，先播一段**功能栏渐隐**
        （工具栏 + 底部提示条，见 `_animate_finish`）再销毁窗口；键盘
        （Esc / Enter）与其它入口保持**即时**退出 —— 键盘要的是快。

        ⚠️ `self.action` 在动画**开始前**就设好：`run()` 里 `wait_window` 返回后
           立刻读它，动画只延后了销毁时机，不影响结果。
        """
        self.action = action
        self._close_popup()
        # 提示气泡是按 420ms 延迟排的，遮罩关掉时它可能还没跑 —— 先撤掉任务，
        # 否则回调会在已销毁的 Canvas 上执行。
        self._schedule_bar_tip(None)

        win = self._win
        if win is None:
            return
        try:
            win.grab_release()
        except tk.TclError:
            pass

        # 动画进行中又点了一次（或键盘补了一刀）→ 不磨蹭，直接结束
        if not animated or self._finishing:
            self._destroy_now()
            return

        self._finishing = True
        self._animate_finish()

    def _capture_ui_layer(self, tag: str, box: tuple[float, float, float, float]):
        """抓下某个 UI 分组的**当前屏幕画面**，删掉原 item，再贴回一张位图。

        返回 `(item_id, base_image)` 供动画逐帧 `putalpha`；不可用时返回 None。

        ⚠️ 为什么不按 `_build_toolbar` 用 PIL 重画一遍：Canvas item 没有 alpha
           通道，要整块淡出只能换成位图；而重画必须复刻每一处配色与位置，
           任何一点偏差都会在动画第一帧"跳一下"。抓屏拿到的是**所见即所得**的
           像素 —— 淡出时露出的正是它自己压着的那张图，天然严丝合缝。
        ⚠️ 抓到的图必须 `convert("RGBA")`：`capture.grab_all()` 给的是 RGB，
           直接 `getchannel("A")` 会抛 ValueError。
        ⚠️ 用 **delete 而不是 `state="hidden"`**：动画期间只要还有任何一条路径
           重刷这些 item（`_on_hover` → `_set_bar_hover` → `_paint_bar_item`），
           hidden 就会被改回 normal、工具栏当场"复活"——实测为此排查了很久。
           删掉就没有"被刷回来"这回事，反正窗口紧接着就销毁、也不需要恢复。
        ⚠️ 抓屏失败就返回 None，退化成"功能栏瞬间消失"，绝不能让退场流程卡住
           —— 那样遮罩窗口会一直留在屏幕上。
        """
        canvas = self._canvas
        if canvas is None:
            return None
        x1, y1, x2, y2 = (int(v) for v in box)
        if x2 <= x1 or y2 <= y1:
            return None
        try:
            shot = capture.grab_all().image.crop((x1, y1, x2, y2)).convert("RGBA")
        except Exception:  # noqa: BLE001
            return None
        canvas.delete(tag)
        item = canvas.create_image(
            x1,
            y1,
            anchor="nw",
            image=theme.photo(shot, key=("finishfade", tag, x1, y1, x2, y2)),
            tags="finishfade",
        )
        return item, shot

    def _animate_finish(self) -> None:
        """退场动画：**功能栏渐隐**（工具栏 + 底部提示条，alpha 1 → 0）。

        ⚠️ 全程包 `try/except TclError`：窗口可能被外部销毁（例如用户按了
           Win+D），这时任何 itemconfigure / after 都会抛。
        """
        canvas = self._canvas
        if canvas is None:
            self._destroy_now()
            return

        # 工具栏按 `_bar_*` 的**确切矩形**取，不能用 `bbox("bar")` —— 实测它会把
        # 位置异常的隐藏 item 也算进去，返回 1305px 高的矩形。提示条用 bbox 即可。
        bar_box = (
            self._bar_x,
            self._bar_y,
            self._bar_x + self._bar_size[0],
            self._bar_y + self._bar_size[1],
        )
        fades = []
        for tag, box in (("bar", bar_box), ("hint", canvas.bbox("hint"))):
            if not box:
                continue
            prepared = self._capture_ui_layer(tag, box)
            if prepared is not None:
                fades.append(prepared)

        def step(index: int) -> None:
            if self._win is None:
                return
            ratio = index / FINISH_ANIM_STEPS
            try:
                for item, base in fades:
                    img = base.copy()
                    img.putalpha(
                        base.getchannel("A").point(lambda v: int(v * (1.0 - ratio)))
                    )
                    canvas.itemconfigure(
                        item, image=theme.photo(img, key=("finishfade", index, item))
                    )
            except tk.TclError:
                self._destroy_now()
                return
            if index >= FINISH_ANIM_STEPS:
                self._destroy_now()
                return
            try:
                self._finish_job = self._win.after(
                    FINISH_ANIM_INTERVAL, lambda: step(index + 1)
                )
            except tk.TclError:
                self._destroy_now()

        step(0)

    def _destroy_now(self) -> None:
        """真正销毁遮罩窗口（退场动画的终点，也是即时退出的唯一出口）。"""
        win = self._win
        self._win = None
        job = self._finish_job
        self._finish_job = None
        if win is None:
            return
        if job is not None:
            try:
                win.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        try:
            win.destroy()
        except tk.TclError:
            pass
