"""主程序编排：热键 → 框选 → 选择操作 → 执行。

线程模型：
    tkinter 只能在主线程操作。keyboard 的热键回调、OCR、翻译都在别的线程，
    统一用 `root.after(0, ...)` 把结果抛回主线程。
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Any, Callable

from PIL import Image

from . import (
    capture,
    clipboard,
    config,
    hotkey,
    icons,
    models,
    ocr_engine,
    overlay,
    paths,
    settings_window,
    storage,
    theme,
    translator,
    tray,
    ui,
    widgets,
)


class App:
    def __init__(self) -> None:
        capture.enable_dpi_awareness()
        # ⚠️ 必须在建任何窗口之前：给进程一个明确的 AppUserModelID，
        # 否则 Windows 任务栏按 `pythonw.exe` 取图标，显示的是 Python 的图标，
        # 跟窗口图标怎么设都对不上（主人反馈"底栏图标还是旧的"）。
        icons.claim_taskbar_identity()
        self.cfg = config.load()
        # ⚠️ "是不是首次运行"必须在写任何日志**之前**判断 —— app.log 一旦被创建，
        # 这台机器就再也算不上"全新安装"了。
        # 判据用"数据目录里有没有运行痕迹"，而不是单看 config.json：本机实测
        # config.json 只在点过「保存热键」之后才存在，用它当判据会把用了一阵子的
        # 老机器误判成全新安装，又弹一次窗口。
        self._first_run = not (
            (paths.data_dir() / "app.log").exists() or paths.config_file().exists()
        )
        self.root = tk.Tk()
        # 标题栏 / 任务栏图标。`iconphoto(True, ...)` 设的是**应用默认图标**，
        # 之后创建的所有 Toplevel（结果窗口等）都会自动带上，不用逐个设置。
        #
        # ⚠️ 光设一次不够：窗口 `withdraw()` 时 Tk 会把底层 wrapper 销毁，
        # `deiconify()` 重建之后图标不一定跟得上（实测：不补设，标题栏左侧就是
        # 一片空白）。所以再挂一个 <Map> 绑定，每次窗口被映射时补设一次。
        # `apply_tk_icon` 是幂等的，重复调用不会重复建 PhotoImage。
        icons.apply_tk_icon(self.root)
        self.root.bind("<Map>", lambda _e: icons.apply_tk_icon(self.root), add="+")
        self._busy = False
        self._ocr_engine = None
        #: 遮罩是否开着。开着的时候结果窗口要置顶，否则会被整屏遮罩盖住。
        self._overlay_active = False
        #: 当前的遮罩实例（便于后续操作与排查）
        self._overlay: overlay.ScreenshotOverlay | None = None
        #: 热键线程置位、主线程消费（见 _on_hotkey）
        self._hotkey_pending = False
        #: 当前的结果窗口（便于后续操作与排查）
        self._result_window: ui.ResultWindow | None = None
        #: 当前打开着的设置窗口（同时只允许一个）
        self._settings: settings_window.SettingsWindow | None = None
        #: 托盘。它起不来的话"关闭"按钮要退化成"退出"，免得窗口藏了再也找不回来。
        self.tray: tray.Tray | None = None
        self._tray_ok = False
        #: 截屏前主窗口露着没有 —— 截屏完要还原成原样，
        #: 不能把躲在托盘里的主窗口又弹出来。
        self._window_was_visible = True

        self.panel = ui.ControlPanel(
            self.root,
            self.cfg,
            on_capture=self.request_capture,
            on_save_settings=self.apply_settings,
            on_quit=self.quit,
            # 录制热键期间先注销全局热键，否则按到当前组合会直接开始截屏
            on_suspend_hotkey=hotkey.unregister_all,
            on_open_settings=self.open_settings,
        )
        # ❌ 不再是"退出"，而是收进托盘（主人 2026-10-08 要求）
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)
        self._start_tray()
        self._register_hotkey()
        self._poll_hotkey()
        self._warn_missing_models()
        self._apply_startup_visibility()
        # 预热遮罩素材（卡片 / 工具栏 / 字体度量）：让"程序启动后第一次按热键"
        # 也走缓存快路径 —— 实测冷启动 303ms → 热 154ms。放 after 里不占用启动
        # 时间，失败也不影响使用。
        self.root.after(400, self._prewarm_overlay)

    def _prewarm_overlay(self) -> None:
        """预热遮罩素材。失败只记日志，绝不影响启动。"""
        try:
            overlay.ScreenshotOverlay.prewarm(self.root)
        except Exception as exc:  # noqa: BLE001
            self._log(f"遮罩预热失败（不影响使用）：{type(exc).__name__}: {exc}")
        else:
            self._log("遮罩素材已预热")

    # ---------- 托盘与窗口显隐 ----------

    def _start_tray(self) -> None:
        """起系统托盘。

        ⚠️ 托盘的回调跑在 pystray 自己的线程里，而 tkinter 不是线程安全的 ——
        所以这里全部包一层 `after(0, ...)`，把工作抛回主线程。
        """
        if not self.cfg.get("show_tray", True):
            self._log("配置里关掉了托盘（show_tray=False），「关闭」按钮 = 退出")
            return
        self.tray = tray.Tray(
            on_capture=lambda: self.root.after(0, self.request_capture),
            on_show=lambda: self.root.after(0, self.show_window),
            on_quit=lambda: self.root.after(0, self.quit),
        )
        try:
            self.tray.start()
        except Exception as exc:  # noqa: BLE001 - 托盘只是锦上添花，绝不能挡住启动
            self._log(f"托盘启动失败：{type(exc).__name__}: {exc}")
            return
        self._tray_ok = self.tray.ok
        self._log(f"托盘已启动（可用={self._tray_ok}）")

    def _apply_startup_visibility(self) -> None:
        """只有**首次**运行才把主窗口亮出来，之后一律静默驻留托盘。

        主人 2026-10-08 要求："只有首次打开时才出现，后续都不要自主弹出来了"。

        判据是**数据目录里有没有运行痕迹**（app.log / config.json）。
        这样对已经用过的机器**立刻生效** —— 主人下次启动就不会再看到窗口自己
        冒出来了，不用先去改什么标记；而真正全新安装的用户仍然能看到一次。
        想再看到主窗口：右键托盘图标 → 「显示主窗口」。
        """
        if not self._first_run:
            self.root.withdraw()
            # ⚠️ 2026-10-10 主人要求删掉这条提示 —— 它原来显示在状态行/徽章上，
            #    既占地方又没什么信息量（托盘图标本身就在那儿）。
            self._log("非首次运行：主窗口不弹出，直接驻留托盘")
            return
        self._log("首次运行：显示主窗口，并落地配置文件")
        try:
            # 把配置写下来，顺便让数据目录有个明确的配置文件
            config.save(self.cfg)
        except OSError as exc:
            self._log(f"首次运行写配置失败：{exc}")

    def hide_to_tray(self) -> None:
        """点 ❌ → 收进托盘，不退出程序。"""
        if not self._tray_ok:
            # 没有托盘还藏起来，窗口就再也叫不回来了 —— 老老实实退出
            self._log("托盘不可用，「关闭」退化为退出")
            self.quit()
            return
        self.root.withdraw()
        self.panel.log("已最小化到托盘（右键托盘图标 → 退出）")
        self._log("已最小化到托盘")

    def show_window(self) -> None:
        """从托盘里把主窗口叫回来。"""
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass

    # ---------- 热键 ----------

    def _register_hotkey(self) -> None:
        hotkey.unregister_all()
        try:
            combo = hotkey.register(self.cfg["hotkey"], self._on_hotkey)
        except Exception as exc:  # noqa: BLE001
            self.panel.set_hotkey_status(f"热键注册失败：{exc}", tone="warn")
            return
        # 状态胶囊只放用户真正关心的信息（热键本身）。数据目录挪进了设置窗口的
        # 「关于 / 维护」—— 改造前它挤在同一行里，把关键信息淹了。
        self.panel.set_hotkey_status(f"{combo} 已就绪")

    def _on_hotkey(self) -> None:
        # ⚠️ keyboard 的回调跑在它自己的线程里，而 tkinter 不是线程安全的：
        # 跨线程直接调 root.after 并不保证生效（曾经出现过"按热键没反应"）。
        # 这里只置一个标志，由主线程的轮询去消费，稳妥。
        self._hotkey_pending = True

    def _poll_hotkey(self) -> None:
        if self._hotkey_pending:
            self._hotkey_pending = False
            self.request_capture()
        # 采样间隔 = 热键按下后最长要等多久才被主线程消费。60ms 时手感上已经
        # 能觉出一点粘滞（实测在总延迟里稳定占 0~60ms），压到 15ms —— 空回调
        # 的 CPU 开销可以忽略，而最坏等待直接砍掉 3/4。
        self.root.after(15, self._poll_hotkey)

    def _warn_missing_models(self) -> None:
        missing = [pair for pair in self._needed_pairs() if not models.is_installed(pair)]
        if missing:
            # 改造前这条提示写的是"请点「下载离线模型」"，可**那个按钮根本不存在**
            # ——`download_models()` 是个没有任何界面入口的孤儿方法。现在设置窗口
            # 里有真的下载入口了，文案才配得上现实。
            self.panel.log(
                f"⚠️ 离线模型 {'/'.join(missing)} 未安装，"
                f"请在「设置」里下载，或把翻译模式改为「在线」"
            )

    def _configured_pair(self) -> str:
        return self.cfg.get("translate", {}).get("offline_pair", "")

    def _needed_pairs(self) -> list[str]:
        """自动判断模式下中英两个方向都要备好。"""
        pair = self._configured_pair()
        return ["en_zh", "zh_en"] if not pair else [pair]

    # ---------- 截图流程 ----------

    def request_capture(self) -> None:
        if self._busy:
            return
        self._busy = True
        # 记下主窗口当前露着没有：截屏前要把它藏起来（免得被截进画面），
        # 截完再还原 —— 本来就躲在托盘里的，就让它继续躲着，别自己弹出来。
        self._window_was_visible = bool(self.root.winfo_viewable())
        if not self._window_was_visible:
            # ⚠️ 主窗口本来就藏在托盘里（这是常态），屏幕上一个像素都不用等 ——
            # 直接抓屏。改造前这里**无条件** `after(200)`，白等 200ms 才动手，
            # 是"按热键 → 遮罩出现"总延迟里最大的一笔（实测 200/550ms）。
            self._capture_once()
            return
        self.root.withdraw()
        # 只有主窗口真的露着时才需要等它从屏幕上消失：`withdraw()` 之后 DWM
        # 还要一两帧才重绘完，200ms 是留够余量的保守值。这条路只在首次运行、
        # 或用户刚从托盘调出主窗口时才会走到。
        self.root.after(200, self._capture_once)

    def _capture_once(self) -> None:
        try:
            shot = capture.grab_all()
            self._overlay_active = True
            self._overlay = overlay.ScreenshotOverlay(
                self.root, shot, on_action=self._on_overlay_action
            )
            result = self._overlay.run()
        except Exception as exc:  # noqa: BLE001
            self._overlay_active = False
            self._restore_window()
            self._busy = False
            messagebox.showerror("截图失败", str(exc), parent=self.root)
            return

        self._overlay_active = False
        self._restore_window()
        self._busy = False
        if self._result_window is not None:
            # 遮罩关了，结果窗口不必再压在所有窗口之上；但要抢回一次可见性，
            # 否则可能被别的窗口盖住 —— 主人刚截完图却看不到结果，太别扭了。
            self._result_window.set_topmost(False)
            self._result_window.raise_window()
        if result is None:
            return

        image, action = result
        self._handle_action(image, action)

    def _restore_window(self) -> None:
        """截屏结束，把主窗口还原成截屏前的样子（本来就藏着的就继续藏着）。"""
        if self._window_was_visible:
            self.root.deiconify()

    def _close_result_window(self) -> None:
        """收掉当前结果窗口（已经关掉的话就当无事发生）。"""
        window = self._result_window
        self._result_window = None
        if window is None:
            return
        try:
            window.win.destroy()
        except tk.TclError:
            pass

    def _on_overlay_action(self, action: str, image: Image.Image) -> None:
        """遮罩工具栏上的「识」「译」：先把结果窗口立起来，遮罩随即退出框选。

        点「识」或「译」就意味着"我要看结果了"，遮罩留着也没用 —— 主人要求
        调出结果窗口后自动退出截屏框选。要看译文，改在结果窗口里点左侧「译文」标签。
        """
        self._start_ocr(image, then_translate=(action == "translate"))

    def _handle_action(self, image: Image.Image, action: str) -> None:
        if action == "copy":
            try:
                clipboard.copy_image(image)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("复制失败", str(exc), parent=self.root)
                return
            storage.add_history(image)
            self.panel.refresh_history()
            self.panel.log("已复制到剪贴板")
        elif action == "save":
            self._save_image_only(image)
        elif action == "pin":
            self._pin_image(image)
        elif action == "ocr":
            self._start_ocr(image, then_translate=False)
        elif action == "translate":
            self._start_ocr(image, then_translate=True)

    def _pin_image(self, image: Image.Image) -> None:
        """把图片钉在屏幕上：置顶、可拖动、悬停浮出工具条、双击或 Esc 关闭。

        改造前是一张无边框裸图 + 1px 黑线，**唯一的关闭方式是双击** —— 而界面上
        没有任何文字提示这件事，用起来全靠猜。现在悬停会浮出迷你工具条
        （复制 / 保存 / 透明度 / 关闭），双击与 Esc 也仍然有效。

        ⚠️ 圆角外的区域靠 `-transparentcolor` 抠成透明，所以圆角图必须用
        `antialias=False` 的硬边版本 —— 抗锯齿的半透明边缘抠不干净，会留一圈杂色。
        """
        scale = theme.scale(self.root)
        card, _pad = theme.framed_image(
            image,
            theme.pxf(scale, theme.RADIUS_MD),
            outline=theme.N300,
            outline_width=max(1, int(round(scale))),
            antialias=False,
        )
        photo = theme.photo(card, key=("pin", image.size, scale))

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        magic = widgets.MAGIC
        try:
            win.configure(bg=magic)
            win.attributes("-transparentcolor", magic)
            canvas_bg = magic
        except tk.TclError:
            win.configure(bg=theme.N0)
            canvas_bg = theme.N0

        holder = tk.Canvas(
            win,
            width=image.width,
            height=image.height,
            highlightthickness=0,
            bd=0,
            bg=canvas_bg,
        )
        holder.pack()
        holder.create_image(0, 0, anchor="nw", image=photo)
        holder.image = photo  # 保住引用，否则会被 GC 掉

        # ---- 悬停浮出的迷你工具条 ----
        toolbar = tk.Frame(win, bg=theme.D900)
        alpha_levels = (1.0, 0.75, 0.5)
        state = {"alpha": 0}
        pending: dict[str, str | None] = {"job": None}

        def close(_event: tk.Event | None = None) -> None:
            try:
                win.destroy()
            except tk.TclError:
                pass

        def do_copy() -> None:
            try:
                clipboard.copy_image(image)
            except Exception as exc:  # noqa: BLE001
                self.panel.log(f"复制失败：{exc}")
                return
            self.panel.log("已复制到剪贴板")

        def do_save() -> None:
            path = filedialog.asksaveasfilename(
                parent=win,
                title="保存图片",
                defaultextension=".png",
                filetypes=[("PNG 图片", "*.png"), ("JPEG 图片", "*.jpg")],
                initialfile=f"截图-{storage.timestamp_name()}",
                initialdir=str(storage.paths.default_save_dir()),
            )
            if not path:
                return
            try:
                image.save(path)
            except OSError as exc:
                self.panel.log(f"保存失败：{exc}")
                return
            self.panel.log(f"已保存：{path}")

        def cycle_alpha() -> None:
            state["alpha"] = (state["alpha"] + 1) % len(alpha_levels)
            try:
                win.attributes("-alpha", alpha_levels[state["alpha"]])
            except tk.TclError:
                pass
            self.panel.log(f"钉图透明度 {int(alpha_levels[state['alpha']] * 100)}%")

        widgets.IconButton(
            toolbar, "copy", do_copy, size=18, pad=7, tooltip="复制", scale=scale
        ).pack(side="left")
        widgets.IconButton(
            toolbar, "save", do_save, size=18, pad=7, tooltip="保存为文件", scale=scale
        ).pack(side="left")
        widgets.IconButton(
            toolbar,
            "opacity",
            cycle_alpha,
            size=18,
            pad=7,
            tooltip="切换透明度",
            scale=scale,
        ).pack(side="left")
        widgets.IconButton(
            toolbar,
            "close",
            close,
            size=18,
            pad=7,
            fg=theme.D400,
            fg_hover=theme.R500,
            tooltip="关闭",
            scale=scale,
        ).pack(side="left")

        def show_toolbar(_event: tk.Event | None = None) -> None:
            job = pending["job"]
            if job is not None:
                try:
                    win.after_cancel(job)
                except (tk.TclError, ValueError):
                    pass
                pending["job"] = None
            toolbar.place(relx=0.5, y=theme.pxf(scale, 8), anchor="n")

        def hide_toolbar(_event: tk.Event | None = None) -> None:
            # 延迟隐藏：鼠标从图片挪到工具条上时会先触发图片的 Leave，
            # 不留这个缓冲的话工具条会"还没点就没了"。
            def do_hide() -> None:
                pending["job"] = None
                try:
                    toolbar.place_forget()
                except tk.TclError:
                    pass

            pending["job"] = win.after(400, do_hide)

        drag = {"x": 0, "y": 0}

        def on_press(event: tk.Event) -> None:
            drag["x"], drag["y"] = event.x, event.y

        def on_drag(event: tk.Event) -> None:
            win.geometry(f"+{event.x_root - drag['x']}+{event.y_root - drag['y']}")

        holder.bind("<Button-1>", on_press)
        holder.bind("<B1-Motion>", on_drag)
        holder.bind("<Double-Button-1>", close)
        holder.bind("<Enter>", show_toolbar)
        holder.bind("<Leave>", hide_toolbar)
        toolbar.bind("<Enter>", show_toolbar)
        toolbar.bind("<Leave>", hide_toolbar)
        win.bind("<Escape>", close)

        # 摆到鼠标右下角，并夹在屏幕内（原实现直接 +12，图一大就跑到屏幕外了）
        margin = 12
        x = min(
            win.winfo_pointerx() + margin,
            win.winfo_screenwidth() - image.width - margin,
        )
        y = min(
            win.winfo_pointery() + margin,
            win.winfo_screenheight() - image.height - margin,
        )
        win.geometry(f"+{max(0, x)}+{max(0, y)}")

        storage.add_history(image)
        self.panel.refresh_history()
        self.panel.log("已钉在屏幕（悬停出工具条，双击或 Esc 关闭）")

    def _save_image_only(self, image: Image.Image) -> None:
        path = storage.save_image(image)
        storage.add_history(image)
        self.panel.refresh_history()
        self.panel.log(f"已保存：{path}")

    # ---------- OCR ----------

    def _get_engine(self):
        if self._ocr_engine is None:
            name = self.cfg.get("ocr_engine", "rapidocr")
            self._ocr_engine = ocr_engine.create_engine(name)
        return self._ocr_engine

    def _start_ocr(
        self,
        image: Image.Image,
        *,
        then_translate: bool,
    ) -> None:
        # 遮罩上可以连着点「识」「译」，先收掉上一个结果窗口，别越堆越多
        self._close_result_window()

        # entry 在 OCR 完成后才有，用可变容器让闭包能拿到
        holder: dict[str, storage.HistoryEntry | None] = {"entry": None}
        window = ui.ResultWindow(
            self.root,
            image,
            on_translate=lambda: self._translate_in(window, holder["entry"]),
            topmost=self._overlay_active,
            on_notice=self._log,  # 保存图片成功不弹窗，只留一条日志
        )
        window.set_loading_text("识别中")
        self._result_window = window
        self.panel.log("正在识别文字…")
        self._log(f"OCR 开始：图 {image.size}，then_translate={then_translate}")

        def work() -> str:
            lines = self._get_engine().recognize(image)
            return ocr_engine.lines_to_text(lines)

        def done(text: str | None, error: Exception | None) -> None:
            if error is not None:
                self._log(f"OCR 失败：{type(error).__name__}: {error}")
                window.set_text(f"识别失败：{error}")
                self.panel.log(f"识别失败：{error}")
                return
            window.set_text(text or "（未识别到文字）")
            # 读回校验：万一设置成功但界面没显示，这里能抓到
            self._log(
                f"OCR 完成：识别 {len(text or '')} 字，界面读回 "
                f"{len(window.get_text())} 字"
            )
            self.panel.log("识别完成")
            holder["entry"] = storage.add_history(image, text=text or "")
            self.panel.refresh_history()
            if text and self.cfg.get("auto_copy_text", True):
                self._auto_copy_text(window, text)
            if then_translate:
                self._translate_in(window, holder["entry"])

        self._run_async(work, done)

    def _auto_copy_text(self, window: ui.ResultWindow, text: str) -> None:
        """OCR 完成后自动把原文写进剪贴板。

        ⚠️ 配置项 `auto_copy_text` 改造前**全项目零引用** —— 字段定义了、默认值
        也写着 True，却没有任何一行代码读它。现在才真正接上。
        """
        try:
            import pyperclip

            pyperclip.copy(text)
        except Exception:  # noqa: BLE001 - 自动复制失败不该影响主流程
            return
        widgets.Toast.show(window.win, "原文已自动复制到剪贴板", kind="info")

    # ---------- 翻译 ----------

    def _translate_in(
        self, window: ui.ResultWindow, entry: storage.HistoryEntry | None
    ) -> None:
        text = window.get_text()
        self._log(f"翻译请求：读回 {len(text)} 字，entry={entry.id if entry else None}")

        if "识别中" in text:
            widgets.Toast.show(window.win, "文字识别还没完成，请稍等片刻", kind="warn")
            return
        if not text.strip():
            widgets.Toast.show(window.win, "没有可翻译的文字", kind="warn")
            return

        window.set_translation_loading()
        self.panel.log("正在翻译…")
        cfg = self.cfg

        def work():
            return translator.TranslationService(cfg).translate(text)

        def done(result, error) -> None:
            if error is not None:
                self._log(f"翻译失败：{type(error).__name__}: {error}")
                # ok=False：这不算"翻译完成"，主人再点一次「译文」还能重试
                window.set_translation(f"翻译失败：{error}", ok=False)
                self.panel.log(f"翻译失败：{error}")
                return
            window.set_translation(result.text)
            self._log(
                f"翻译成功（{result.provider} {result.source_lang}->{result.target_lang}）："
                f"{len(result.text)} 字"
            )
            self.panel.log(f"翻译完成（{result.provider}）")
            if entry is not None:
                storage.update_translation(entry.id, result.text)
                self.panel.refresh_history()

        self._run_async(work, done)

    # ---------- 模型 ----------

    def download_models(
        self,
        pair: str,
        progress: Callable[[int, int], None] | None = None,
        done: Callable[[bool, str], None] | None = None,
    ) -> None:
        """下载离线模型（由设置窗口调用）。

        ⚠️ 改造前这个方法**在界面上没有任何入口** —— 而启动警告却写着
        "请点「下载离线模型」"，用户照着找是找不到那个按钮的。现在设置窗口里
        有真的入口，并且能显示**真实百分比**（`models.download()` 自带
        `progress(已下载, 总字节)` 回调）。
        """
        if models.is_installed(pair):
            if done is not None:
                done(True, "已就绪")
            return

        self.panel.log(f"正在下载离线模型 {pair}…")

        def safe_progress(downloaded: int, total: int) -> None:
            if progress is None:
                return
            # ⚠️ 进度回调来自后台线程，必须抛回主线程才能碰界面
            self.root.after(0, lambda: progress(downloaded, total))

        def work() -> str:
            return str(models.ensure_installed(pair, progress=safe_progress))

        def finish(result: str | None, error: Exception | None) -> None:
            if error is not None:
                self.panel.log(f"模型 {pair} 下载失败")
                self._log(f"模型下载失败：{type(error).__name__}: {error}")
                if done is not None:
                    done(False, str(error))
                return
            self.panel.log(f"模型 {pair} 已就绪")
            self._log(f"模型 {pair} 已就绪：{result}")
            if done is not None:
                done(True, result or "")

        self._run_async(work, finish)

    # ---------- 设置窗口 ----------

    def open_settings(self) -> None:
        """打开设置窗口（模态）。已经开着就把它提到前面，不重复开。"""
        existing = self._settings
        if existing is not None:
            try:
                existing.win.lift()
                existing.win.focus_force()
                return
            except tk.TclError:
                self._settings = None

        window = settings_window.SettingsWindow(
            self.root,
            self.cfg,
            on_save=self.apply_settings,
            on_download=self.download_models,
            on_clear_history=self.panel.refresh_history,
        )
        self._settings = window

        def on_destroy(event: tk.Event) -> None:
            # ⚠️ <Destroy> 会从子控件冒泡上来，必须确认是窗口本身才清引用
            if event.widget is window.win:
                self._settings = None

        window.win.bind("<Destroy>", on_destroy, add="+")

    # ---------- 杂项 ----------

    def _run_async(
        self,
        work: Callable[[], Any],
        done: Callable[[Any, Exception | None], None],
    ) -> None:
        """在后台线程跑 work，再把结果抛回主线程交给 done。"""

        def runner() -> None:
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda err=exc: done(None, err))
            else:
                self.root.after(0, lambda value=result: done(value, None))

        threading.Thread(target=runner, daemon=True).start()

    def _log(self, message: str) -> None:
        """把关键事件写进 app.log，用于排查偶发问题（pythonw 下没有控制台）。"""
        try:
            with open(paths.log_file(), "a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
        except OSError:
            pass

    def apply_settings(self, cfg: dict) -> None:
        self.cfg = cfg
        config.save(cfg)
        self._ocr_engine = None  # 引擎可能换了，下次重建
        self._register_hotkey()

    def quit(self) -> None:
        hotkey.unregister_all()
        if self.tray is not None:
            self.tray.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()
