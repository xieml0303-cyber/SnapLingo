"""独立设置窗口。

主面板刻意保持极简（主人 2026-10-08 的决定："只保留全局热键与开始截屏"），
所以配置项集中到这个模态窗口里。

这里同时把**几处断掉的线**接上 —— 改造前它们只存在于 config.json，界面上一个
入口都没有，用户只能手改 JSON：

    1. `ocr_engine`     OCR 引擎选择
    2. `translate.*`    翻译模式 / 离线语言对 / 在线密钥
    3. `save_dir`       保存目录。⚠️ 这是最坑的一处：`paths.default_save_dir()`
                        改造前**根本不读这个配置**，写了也完全没用（静默失效）
    4. 离线模型         安装状态 + **带真百分比**的下载进度。
                        `app.download_models()` 原本是个孤儿方法，界面上没有任何
                        入口调用它，可启动警告却写着"请点「下载离线模型」"
    5. `auto_copy_text` 字段定义了但全项目零引用，这里接成真功能
    6. 开机自启         新功能，写 HKCU 的 Run 键（默认关，用户主动打开）
    7. 关于 / 维护      版本、数据目录、日志、清空历史
"""

from __future__ import annotations

import copy
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from . import APP_TITLE, __version__, autostart, icons, models, paths, storage, theme, widgets

#: 选项值 → 界面文案（顺序必须一一对应）
OCR_VALUES = ("rapidocr", "windows")
OCR_LABELS = ("RapidOCR（推荐）", "Windows 内置")
MODE_VALUES = ("offline", "online", "auto")
MODE_LABELS = ("离线", "在线", "自动")
PAIR_VALUES = ("", "en_zh", "zh_en")
PAIR_LABELS = ("自动判断", "英 → 中", "中 → 英")
PROVIDER_VALUES = ("youdao", "openai")
PROVIDER_LABELS = ("有道智云", "OpenAI 兼容")


def _index_of(values: tuple, current) -> int:
    try:
        return values.index(current)
    except ValueError:
        return 0


class SettingsWindow:
    """模态设置窗口。改动只在点「保存」时提交。"""

    def __init__(
        self,
        parent: tk.Misc,
        cfg: dict,
        *,
        on_save: Callable[[dict], None],
        on_download: Callable[[str, Callable, Callable], None] | None = None,
        on_clear_history: Callable[[], None] | None = None,
    ) -> None:
        self.parent = parent
        #: 改动先落在副本上，点「保存」才回写
        self.cfg = copy.deepcopy(cfg)
        self.on_save = on_save
        self.on_download = on_download
        self.on_clear_history = on_clear_history
        self.scale = theme.scale(parent)
        s = self.scale
        self._s = s

        self._model_badges: dict[str, widgets.Badge] = {}
        self._model_bars: dict[str, widgets.ProgressBar] = {}

        win = tk.Toplevel(parent)
        self.win = win
        win.title(f"{APP_TITLE} · 设置")
        icons.apply_tk_icon(win)
        win.configure(bg=theme.N50)
        win.resizable(False, False)
        try:
            win.transient(parent)
        except tk.TclError:
            pass

        # ⚠️ 底部按钮栏**必须最先 pack 并贴底**。Tk 按 pack 顺序分配空间，最后
        #    pack 的 widget 在窗口偏矮时会被挤成 0 高 —— 表现就是"保存/取消按钮
        #    凭空消失"（README #11 记录过这个坑，结果窗口那边也是这么处理的）。
        self._build_footer()

        # 内容区放进可滚动容器：这台机器是 1920×1080，设置项排下来会超过屏幕高度，
        # 不滚动的话底部的「关于 / 维护」区会被裁掉。
        outer = tk.Frame(win, bg=theme.N50)
        outer.pack(fill="both", expand=True)
        scroll_canvas = tk.Canvas(outer, highlightthickness=0, bd=0, bg=theme.N50)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)
        self._scroll_canvas = scroll_canvas

        self.body = tk.Frame(scroll_canvas, bg=theme.N50)
        self._body_window = scroll_canvas.create_window(
            (0, 0), anchor="nw", window=self.body
        )
        self.body.bind(
            "<Configure>",
            lambda _e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")),
        )
        scroll_canvas.bind(
            "<Configure>",
            lambda e: scroll_canvas.itemconfigure(self._body_window, width=e.width),
        )
        # ⚠️ 滚轮事件要绑在**窗口**上而不是 bind_all：事件会从鼠标下的控件沿
        #    bindtags 冒泡到 toplevel，这样滚轮在任何子控件上都能滚动，又不会
        #    像 bind_all 那样污染其它窗口。
        win.bind("<MouseWheel>", self._on_wheel)

        self._build_recognition()
        self._build_models()
        self._build_storage()
        self._build_startup()
        self._build_about()

        # ⚠️ 窗口尺寸不能再用 `win.winfo_reqheight()` —— body 挂进可滚动 Canvas
        #    之后，Canvas 的请求高度是它的默认值（300），跟内容无关，照抄会让
        #    设置窗口变成一个矮条。所以这里按**内容实测高度 + 按钮栏**来算。
        self.body.update_idletasks()
        content_h = self.body.winfo_reqheight()
        footer_h = self._footer.winfo_reqheight()
        left, top, right, bottom = self._work_area()
        avail_h = max(theme.pxf(s, 320), bottom - top - theme.pxf(s, 40))
        width = max(theme.pxf(s, 560), self.body.winfo_reqwidth() + theme.pxf(s, 40))
        height = max(theme.pxf(s, 320), min(content_h + footer_h + theme.pxf(s, 10), avail_h))
        x = left + ((right - left) - width) // 2
        y = top + ((bottom - top) - height) // 2
        win.geometry(f"{width}x{height}+{max(left, x)}+{max(top, y)}")

        win.bind("<Escape>", lambda _e: self.win.destroy())
        try:
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()

    def _on_wheel(self, event: tk.Event) -> None:
        canvas = getattr(self, "_scroll_canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        except tk.TclError:
            pass

    # ---------- 布局辅助 ----------

    def _work_area(self) -> tuple[int, int, int, int]:
        try:
            import ctypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            rect = RECT()
            if ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(rect), 0
            ):
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:  # noqa: BLE001
            pass
        return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    def _section(self, title: str) -> tk.Frame:
        """分区标题 + 分隔线，返回给行用的 grid 容器。

        ⚠️ 左右内边距要在这里补：body 现在挂在可滚动 Canvas 里、宽度被拉满，
        不再由外层 Frame 的 padx 提供留白。
        """
        s = self._s
        side = theme.pxf(s, 18)
        tk.Label(
            self.body,
            text=title,
            font=theme.FONT_EMPH,
            bg=theme.N50,
            fg=theme.N900,
            anchor="w",
        ).pack(fill="x", padx=side, pady=(theme.pxf(s, 14), theme.pxf(s, 4)))
        tk.Frame(self.body, bg=theme.N200, height=1).pack(fill="x", padx=side)
        grid = tk.Frame(self.body, bg=theme.N50)
        grid.pack(fill="x", padx=side, pady=(theme.pxf(s, 8), 0))
        grid.columnconfigure(1, weight=1)
        return grid

    def _row(self, grid: tk.Frame, index: int, label: str) -> tk.Frame:
        s = self._s
        label_widget = tk.Label(
            grid,
            text=label,
            font=theme.FONT_BODY,
            bg=theme.N50,
            fg=theme.N700,
            anchor="w",
        )
        label_widget.grid(
            row=index, column=0, sticky="w",
            padx=(0, theme.pxf(s, 14)), pady=(0, theme.pxf(s, 8)),
        )
        cell = tk.Frame(grid, bg=theme.N50)
        cell.grid(row=index, column=1, sticky="w", pady=(0, theme.pxf(s, 8)))
        #: 记下整行的两个 widget，供 `_apply_provider_visibility()` 动态显隐。
        #: `grid_remove()` 会记住原位置，恢复时直接 `grid()` 就行。
        if not hasattr(grid, "_row_widgets"):
            grid._row_widgets = {}
        grid._row_widgets[index] = (label_widget, cell)
        return cell

    def _hint(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
            anchor="w",
        ).pack(side="left", padx=(theme.pxf(self._s, 8), 0))

    # ---------- 分区：识别与翻译 ----------

    def _build_recognition(self) -> None:
        s = self._s
        grid = self._section("识别与翻译")
        section = self.cfg.get("translate", {})

        cell = self._row(grid, 0, "OCR 引擎")
        self.ocr_seg = widgets.SegmentedControl(
            cell,
            list(OCR_LABELS),
            value=_index_of(OCR_VALUES, self.cfg.get("ocr_engine", "rapidocr")),
            scale=s,
        )
        self.ocr_seg.pack(side="left")

        cell = self._row(grid, 1, "翻译模式")
        self.mode_seg = widgets.SegmentedControl(
            cell,
            list(MODE_LABELS),
            value=_index_of(MODE_VALUES, section.get("mode", "offline")),
            scale=s,
        )
        self.mode_seg.pack(side="left")
        self._hint(cell, "自动 = 先本地、本地不可用再走在线")

        cell = self._row(grid, 2, "离线语言对")
        self.pair_seg = widgets.SegmentedControl(
            cell,
            list(PAIR_LABELS),
            value=_index_of(PAIR_VALUES, section.get("offline_pair", "")),
            scale=s,
        )
        self.pair_seg.pack(side="left")

        # ---- 在线服务商：决定下面显示哪一组字段 ----
        cell = self._row(grid, 3, "在线服务商")
        self.provider_seg = widgets.SegmentedControl(
            cell,
            list(PROVIDER_LABELS),
            self._on_provider_change,
            value=_index_of(PROVIDER_VALUES, section.get("online_provider", "openai")),
            scale=s,
        )
        self.provider_seg.pack(side="left")
        self._hint(cell, "仅「在线 / 自动」模式需要")

        # ---- OpenAI 兼容那一组（行 4~6）----
        cell = self._row(grid, 4, "接口地址")
        self.baseurl_var = tk.StringVar(value=section.get("online_base_url", ""))
        widgets.Entry(cell, textvariable=self.baseurl_var, width=260, scale=s).pack(side="left")
        self._hint(cell, "如 http://127.0.0.1:7863/v1")

        cell = self._row(grid, 5, "模型")
        self.model_var = tk.StringVar(value=section.get("online_model", ""))
        widgets.Entry(cell, textvariable=self.model_var, width=260, scale=s).pack(side="left")
        self._hint(cell, "原样传给上游，如 model group")

        cell = self._row(grid, 6, "API Key")
        self.apikey_var = tk.StringVar(value=section.get("online_api_key", ""))
        widgets.Entry(cell, textvariable=self.apikey_var, width=260, scale=s).pack(side="left")
        self._hint(cell, "本地网关通常可留空")

        # ---- 有道智云那一组（行 7~8）----
        cell = self._row(grid, 7, "有道 AppKey")
        self.youdao_key_var = tk.StringVar(value=section.get("online_app_key", ""))
        widgets.Entry(cell, textvariable=self.youdao_key_var, width=260, scale=s).pack(side="left")

        cell = self._row(grid, 8, "有道 AppSecret")
        self.youdao_secret_var = tk.StringVar(value=section.get("online_app_secret", ""))
        widgets.Entry(cell, textvariable=self.youdao_secret_var, width=260, scale=s).pack(side="left")

        self._recognition_grid = grid
        self._apply_provider_visibility(self.provider_seg.value)

    #: 行号 → 属于哪一组（切换在线服务商时决定显示谁）
    _OPENAI_ROWS = (4, 5, 6)
    _YOUDAO_ROWS = (7, 8)

    def _on_provider_change(self, index: int) -> None:
        self._apply_provider_visibility(index)

    def _apply_provider_visibility(self, index: int) -> None:
        """只显示当前服务商自己的字段。

        选「OpenAI 兼容」就藏掉有道的 AppKey/AppSecret；选「有道智云」就藏掉
        接口地址 / 模型 / API Key —— 免得两套字段混排，让人不知道该填哪几个。
        """
        rows = getattr(self._recognition_grid, "_row_widgets", {})
        is_openai = PROVIDER_VALUES[index] == "openai"
        for row_index in self._OPENAI_ROWS:
            self._toggle_row(rows, row_index, is_openai)
        for row_index in self._YOUDAO_ROWS:
            self._toggle_row(rows, row_index, not is_openai)

    @staticmethod
    def _toggle_row(rows: dict, index: int, visible: bool) -> None:
        pair = rows.get(index)
        if not pair:
            return
        label, cell = pair
        if visible:
            label.grid()
            cell.grid()
        else:
            label.grid_remove()
            cell.grid_remove()

    # ---------- 分区：离线模型 ----------

    def _build_models(self) -> None:
        s = self._s
        grid = self._section("离线模型")
        for index, pair in enumerate(models.PAIRS):
            installed = models.is_installed(pair)
            source, target = models.PAIRS[pair]
            cell = self._row(grid, index, f"{source} → {target}")
            badge = widgets.Badge(
                cell,
                "已安装" if installed else "未安装",
                tone="ok" if installed else "idle",
                scale=s,
            )
            badge.pack(side="left")
            self._model_badges[pair] = badge

            button = widgets.RoundButton(
                cell,
                "下载",
                lambda p=pair: self._download(p),
                variant="secondary",
                pad_x=12,
                pad_y=5,
                scale=s,
            )
            button.pack(side="left", padx=(theme.pxf(s, 8), 0))
            if self.on_download is None:
                button.set_enabled(False)

            bar = widgets.ProgressBar(cell, width=110, height=6, scale=s)
            bar.pack(side="left", padx=(theme.pxf(s, 10), 0))
            self._model_bars[pair] = bar

        tip = tk.Label(
            self.body,
            text="离线模型来自 Argos 官方索引，按需下载，只保留推理所需的模型与分词器。",
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
            anchor="w",
            wraplength=theme.pxf(s, 480),
            justify="left",
        )
        tip.pack(fill="x", padx=theme.pxf(s, 18), pady=(theme.pxf(s, 6), 0))

    def _download(self, pair: str) -> None:
        """下载模型，进度条走**真实百分比**。

        `models.download()` 自带 `progress(已下载, 总字节)` 回调，所以这里不是
        "转圈等待"，而是真进度。⚠️ 回调来自后台线程，app 那边会包一层
        `root.after` 抛回主线程。
        """
        if self.on_download is None:
            return
        badge = self._model_badges[pair]
        bar = self._model_bars[pair]
        badge.set("下载中…", tone="warn")
        bar.set(0.0)

        def progress(done: int, total: int) -> None:
            if total > 0:
                ratio = done / total
                bar.set(ratio)
                badge.set(f"下载中 {int(ratio * 100)}%", tone="warn")
            else:
                badge.set("下载中…", tone="warn")

        def finished(ok: bool, message: str) -> None:
            if ok:
                badge.set("已安装", tone="ok")
                bar.set(1.0)
                widgets.Toast.show(self.win, f"模型 {pair} 已就绪", kind="success")
            else:
                badge.set("下载失败", tone="warn")
                bar.set(0.0)
                widgets.Toast.show(self.win, f"下载失败：{message}", kind="error")

        self.on_download(pair, progress, finished)

    # ---------- 分区：保存与剪贴板 ----------

    def _build_storage(self) -> None:
        s = self._s
        grid = self._section("保存与剪贴板")

        cell = self._row(grid, 0, "保存目录")
        self.dir_var = tk.StringVar(value=self.cfg.get("save_dir", ""))
        widgets.Entry(cell, textvariable=self.dir_var, width=250, scale=s).pack(side="left")
        widgets.IconButton(
            cell,
            "folder",
            self._choose_dir,
            size=18,
            pad=7,
            fg=theme.N500,
            fg_hover=theme.N700,
            bg_hover=theme.N100,
            tooltip="选择目录",
            scale=s,
        ).pack(side="left", padx=(theme.pxf(s, 6), 0))
        widgets.IconButton(
            cell,
            "external",
            self._open_save_dir,
            size=18,
            pad=7,
            fg=theme.N500,
            fg_hover=theme.N700,
            bg_hover=theme.N100,
            tooltip="在资源管理器中打开",
            scale=s,
        ).pack(side="left", padx=(theme.pxf(s, 2), 0))

        tip = tk.Label(
            self.body,
            text="留空则存到「图片 / Screenshots」。",
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
            anchor="w",
            wraplength=theme.pxf(s, 480),
            justify="left",
        )
        tip.pack(fill="x", padx=theme.pxf(s, 18), pady=(theme.pxf(s, 2), 0))

        cell = self._row(grid, 1, "自动复制原文")
        self.autocopy_var = tk.BooleanVar(value=bool(self.cfg.get("auto_copy_text", True)))
        widgets.Switch(cell, self.autocopy_var, scale=s).pack(side="left")
        self._hint(cell, "识别完成后把原文写入剪贴板")

    def _choose_dir(self) -> None:
        current = self.dir_var.get().strip() or str(paths.default_save_dir())
        chosen = filedialog.askdirectory(
            parent=self.win, title="选择保存目录", initialdir=current
        )
        if chosen:
            self.dir_var.set(chosen)

    def _open_save_dir(self) -> None:
        self._open_path(self.dir_var.get().strip() or str(paths.default_save_dir()))

    # ---------- 分区：启动与托盘 ----------

    def _build_startup(self) -> None:
        s = self._s
        grid = self._section("启动与托盘")

        cell = self._row(grid, 0, "开机自启")
        # ⚠️ 以**注册表为准**初始化，不信 config —— 用户可能在任务管理器里手动
        #    禁用了启动项，那时 config 里还写着 true，显示出来就是假的。
        self.autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        self.autostart_switch = widgets.Switch(
            cell, self.autostart_var, self._toggle_autostart, scale=s
        )
        self.autostart_switch.pack(side="left")
        self._hint(cell, "写当前用户的 Run 键，不需要管理员权限")

        cell = self._row(grid, 1, "托盘常驻")
        self.tray_var = tk.BooleanVar(value=bool(self.cfg.get("show_tray", True)))
        widgets.Switch(cell, self.tray_var, scale=s).pack(side="left")
        self._hint(cell, "关闭后「关闭窗口」= 退出程序（重启生效）")

    def _toggle_autostart(self, flag: bool) -> None:
        """开机自启是**即时生效**的（直接写注册表），不走 draft。"""
        actual = autostart.set_enabled(flag)
        if actual != flag:
            # 写注册表被拒（组策略、杀软）：把开关拨回去，绝不谎报成功
            self.autostart_var.set(actual)
            self.autostart_switch.refresh()
            widgets.Toast.show(self.win, "开机自启设置失败（可能被安全软件拦截）", kind="error")
            return
        self.cfg["autostart"] = actual
        widgets.Toast.show(
            self.win, "已开启开机自启" if actual else "已关闭开机自启", kind="success"
        )

    # ---------- 分区：关于 / 维护 ----------

    def _build_about(self) -> None:
        s = self._s
        grid = self._section("关于 / 维护")

        cell = self._row(grid, 0, "版本")
        tk.Label(
            cell,
            text=f"{APP_TITLE} v{__version__}",
            font=theme.FONT_BODY,
            bg=theme.N50,
            fg=theme.N700,
        ).pack(side="left")
        tk.Label(
            cell,
            text="视觉体系：纯 tkinter + PIL 预渲染自绘",
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
        ).pack(side="left", padx=(theme.pxf(s, 10), 0))

        cell = self._row(grid, 1, "数据目录")
        widgets.RoundButton(
            cell,
            "打开",
            lambda: self._open_path(paths.data_dir()),
            variant="secondary",
            icon="folder",
            pad_x=12,
            pad_y=5,
            scale=s,
        ).pack(side="left")
        tk.Label(
            cell,
            text=str(paths.data_dir()),
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
        ).pack(side="left", padx=(theme.pxf(s, 8), 0))

        cell = self._row(grid, 2, "运行日志")
        widgets.RoundButton(
            cell,
            "打开",
            lambda: self._open_path(paths.log_file()),
            variant="secondary",
            icon="log",
            pad_x=12,
            pad_y=5,
            scale=s,
        ).pack(side="left")
        tk.Label(
            cell,
            text="程序没有控制台窗口，排错请看这里",
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
        ).pack(side="left", padx=(theme.pxf(s, 8), 0))

        cell = self._row(grid, 3, "历史记录")
        widgets.RoundButton(
            cell,
            "清空历史",
            self._clear_history,
            variant="danger",
            icon="trash",
            pad_x=12,
            pad_y=5,
            scale=s,
        ).pack(side="left")
        tk.Label(
            cell,
            text="删除历史截图与索引（不可恢复）",
            font=theme.FONT_TIP,
            bg=theme.N50,
            fg=theme.N500,
        ).pack(side="left", padx=(theme.pxf(s, 8), 0))

        # 滚动区底部留白，别让最后一行贴着按钮栏
        tk.Frame(self.body, bg=theme.N50, height=theme.pxf(s, 18)).pack(fill="x")

    def _clear_history(self) -> None:
        # 不可逆操作：原生确认框是合适的（这类中断正是我们想要的）
        if not messagebox.askyesno(
            "清空历史记录",
            "将删除全部历史截图与索引，且无法恢复。\n确定继续吗？",
            parent=self.win,
            icon="warning",
        ):
            return
        try:
            storage.clear_history()
        except OSError as exc:
            widgets.Toast.show(self.win, f"清空失败：{exc}", kind="error")
            return
        if self.on_clear_history is not None:
            self.on_clear_history()
        widgets.Toast.show(self.win, "历史记录已清空", kind="success")

    def _open_path(self, target) -> None:
        try:
            os.startfile(str(target))  # noqa: S606 - Windows 专用，正是我们要的
        except (OSError, AttributeError):
            widgets.Toast.show(self.win, "打开失败", kind="error")

    # ---------- 底部 ----------

    def _build_footer(self) -> None:
        s = self._s
        footer = tk.Frame(self.win, bg=theme.N50)
        self._footer = footer
        footer.pack(side="bottom", fill="x", padx=theme.pxf(s, 18), pady=theme.pxf(s, 14))
        widgets.RoundButton(
            footer, "保存", self._save, variant="primary", pad_x=24, scale=s
        ).pack(side="right")
        widgets.RoundButton(
            footer, "取消", self.win.destroy, variant="ghost", pad_x=18, scale=s
        ).pack(side="right", padx=(0, theme.pxf(s, 8)))

    def _save(self) -> None:
        """把 draft 写回 cfg 并交给 app。"""
        self.cfg["ocr_engine"] = OCR_VALUES[self.ocr_seg.value]
        section = self.cfg.setdefault("translate", {})
        section["mode"] = MODE_VALUES[self.mode_seg.value]
        section["offline_pair"] = PAIR_VALUES[self.pair_seg.value]
        section["online_provider"] = PROVIDER_VALUES[self.provider_seg.value]
        section["online_base_url"] = self.baseurl_var.get().strip()
        section["online_model"] = self.model_var.get().strip()
        section["online_api_key"] = self.apikey_var.get().strip()
        section["online_app_key"] = self.youdao_key_var.get().strip()
        section["online_app_secret"] = self.youdao_secret_var.get().strip()
        self.cfg["save_dir"] = self.dir_var.get().strip()
        self.cfg["auto_copy_text"] = bool(self.autocopy_var.get())
        self.cfg["show_tray"] = bool(self.tray_var.get())
        self.on_save(self.cfg)
        self.win.destroy()
