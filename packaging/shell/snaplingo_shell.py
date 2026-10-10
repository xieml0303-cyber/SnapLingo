"""SnapLingo 空壳程序（Shell）。

用途：仅用于验证「安装 / 卸载流程与安装器界面」，**不含任何截图 / OCR / 翻译功能**。
      接入真实程序时，把 PyInstaller 的入口换回项目根的 ../main.py 即可，安装器脚本不用改。

启动方式：
    SnapLingo.exe                        正常启动（显示极简窗口）
    SnapLingo.exe --set-autostart on     由安装器调用：写开机自启注册表项
    SnapLingo.exe --set-autostart off    由卸载器调用：删开机自启注册表项

设计说明：
  - 窗口做成**无边框 + 圆角**，与安装器保持同一套视觉语言（品牌绿 + 细线 + 圆角）。
  - 圆角在 Windows 11 走 DWM（平滑），Win10 退 SetWindowRgn（锯齿）—— 与安装器同策略。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import tkinter as tk

APP_TITLE = "SnapLingo"
APP_SUBTITLE = "截图 · 识别 · 翻译"
SHELL_VERSION = "0.1.0-shell"

# 品牌色（取自 assets/icon.svg）
BRAND_GREEN = "#0CAF76"
BRAND_GREEN_DEEP = "#089B68"
BRAND_GREEN_SOFT = "#5FD3AC"
INK = "#2F3133"

# 开机自启：与 sctool/autostart.py 保持一致的值名
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "ScreenshotTranslator"


def set_autostart(enable: bool) -> int:
    """写 / 删 HKCU 的开机自启项，返回进程退出码。

    真实 SnapLingo 的逻辑在 sctool/autostart.py；空壳这里做等价实现，
    保证安装器调用 `--set-autostart on` 时行为一致（写 HKCU\\...\\Run）。
    """
    import winreg

    # 打包后 sys.executable 就是 SnapLingo.exe；源码运行时退回脚本自身
    exe = sys.executable if getattr(sys, "frozen", False) else __file__
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(key, AUTOSTART_VALUE, 0, winreg.REG_SZ, f'"{exe}"')
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_VALUE)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        print(f"设置开机自启失败: {exc}", file=sys.stderr)
        return 1
    return 0


class ShellWindow(tk.Tk):
    """极简无边框窗口：顶部一条可拖动标题栏 + 中间字标 + 右下关闭按钮。"""

    W, H = 460, 300
    RADIUS = 18

    def __init__(self) -> None:
        super().__init__()
        self.overrideredirect(True)  # 去掉系统标题栏与边框
        self.configure(bg=BRAND_GREEN)
        self.resizable(False, False)
        self._center_on_screen()
        self._apply_rounded_corners()
        self._build_widgets()
        self._bind_drag_and_keys()

    # ---------- 窗口外观 ----------

    def _center_on_screen(self) -> None:
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - self.W) // 2
        y = (sh - self.H) // 2
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _apply_rounded_corners(self) -> None:
        """圆角：Win11 优先用 DWM（平滑 + 系统阴影），Win10 退到区域裁剪（有锯齿）。"""
        hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
        self._hwnd = hwnd

        # --- Win11: DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2 ---
        try:
            pref = ctypes.c_int(2)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_uint(33),
                ctypes.byref(pref), ctypes.sizeof(pref),
            )
        except (AttributeError, OSError):
            pass

        # --- Win10 兜底：CreateRoundRectRgn + SetWindowRgn ---
        try:
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, self.W + 1, self.H + 1,
                self.RADIUS * 2, self.RADIUS * 2,
            )
            ctypes.windll.user32.SetWindowRgn(ctypes.c_void_p(hwnd), rgn, True)
        except (AttributeError, OSError):
            pass

    def _build_widgets(self) -> None:
        # 顶部细标题栏（同时充当拖动把手）
        bar = tk.Frame(self, bg=BRAND_GREEN_DEEP, height=38)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        tk.Label(
            bar, text="●", bg=BRAND_GREEN_DEEP, fg=BRAND_GREEN_SOFT,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(14, 6))

        tk.Label(
            bar, text=APP_TITLE, bg=BRAND_GREEN_DEEP, fg="#FFFFFF",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")

        close = tk.Label(
            bar, text="✕", bg=BRAND_GREEN_DEEP, fg="#D9F5EA",
            font=("Microsoft YaHei UI", 11), cursor="hand2",
        )
        close.pack(side="right", padx=12)
        close.bind("<Button-1>", lambda _e: self._quit())
        close.bind("<Enter>", lambda _e: close.configure(bg="#E8556D", fg="#FFFFFF"))
        close.bind("<Leave>", lambda _e: close.configure(bg=BRAND_GREEN_DEEP, fg="#D9F5EA"))

        # 主体：字标
        body = tk.Frame(self, bg=BRAND_GREEN)
        body.pack(fill="both", expand=True)

        tk.Label(
            body, text=APP_TITLE, bg=BRAND_GREEN, fg="#FFFFFF",
            font=("Microsoft YaHei UI", 26, "bold"),
        ).pack(pady=(38, 2))

        tk.Label(
            body, text=APP_SUBTITLE, bg=BRAND_GREEN, fg="#CFF0E4",
            font=("Microsoft YaHei UI", 10),
        ).pack()

        tk.Label(
            body, text=f"空壳程序 v{SHELL_VERSION}（仅用于验证安装/卸载流程）",
            bg=BRAND_GREEN, fg=BRAND_GREEN_SOFT,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="bottom", pady=14)

        # 拖动把手：标题栏 + 主体空白处都能拖
        self._drag_handles = (bar, body)

    def _bind_drag_and_keys(self) -> None:
        for widget in self._drag_handles:
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._do_drag)
        # 无边框窗口没有系统菜单，Esc 要自己实现
        self.bind("<Escape>", lambda _e: self._quit())

    # ---------- 拖动 ----------

    def _start_drag(self, event) -> None:
        self._drag_origin = (event.x_root, event.y_root)
        self._win_origin = (self.winfo_x(), self.winfo_y())

    def _do_drag(self, event) -> None:
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        self.geometry(f"+{self._win_origin[0] + dx}+{self._win_origin[1] + dy}")

    def _quit(self) -> None:
        self.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="SnapLingo 空壳程序")
    parser.add_argument(
        "--set-autostart", choices=["on", "off"], default=None,
        help="写/删开机自启项（供安装器与卸载器调用）",
    )
    parser.add_argument("--version", action="store_true", help="打印版本后退出")
    args, _unknown = parser.parse_known_args()

    if args.version:
        print(f"{APP_TITLE} {SHELL_VERSION}")
        return 0

    if args.set_autostart is not None:
        return set_autostart(args.set_autostart == "on")

    ShellWindow().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
