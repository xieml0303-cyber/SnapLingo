"""应用图标资源 + 任务栏身份。

图标由主人的 SVG 渲染而来，**源是 `assets/icon.svg`**（2026-10-09 纳入仓库；
此前生成脚本把源硬编码在下载目录，一改名就没法重渲染），产物（各档 PNG + `.ico`）
也在 `assets/`。生成脚本：`.workbuddy/probe/make_icon.py` —— 本机没有能解析
SVG path 的 Python 库，所以借 Chrome 无头模式渲染。

对外三个入口：
    claim_taskbar_identity() → 声明 AppUserModelID（**必须在建窗口前调**）
    tray_image()             → PIL.Image，给 pystray
    apply_tk_icon()          → 给 Tk 窗口设标题栏 / 任务栏图标
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from pathlib import Path

from PIL import Image

#: 任务栏身份。Windows 按它给任务栏按钮分组、取图标。
APP_USER_MODEL_ID = "Wrok.ScreenshotTool"

#: `iconphoto` 退路用的 PNG 尺寸（只在 .ico 不可用时才走这条路）
TK_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

# ---- Win32 常量 ----
SM_CXICON, SM_CYICON = 11, 12
SM_CXSMICON, SM_CYSMICON = 49, 50
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1

#: 已加载的 HICON 缓存。⚠️ WM_SETICON 的 HICON 由调用方负责释放，窗口销毁时
#: 系统**不会**帮你回收；不缓存的话每次重设图标都会漏掉两个 HICON。
_HICON_CACHE: dict[tuple[str, int, int], int] = {}


def asset_dir() -> Path:
    """assets 目录。

    兼容 PyInstaller 打包：资源会被解到 `sys._MEIPASS`，那时不能按 `__file__` 找。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def claim_taskbar_identity(app_id: str = APP_USER_MODEL_ID) -> bool:
    """给进程一个明确的 AppUserModelID。

    ⚠️ Windows 任务栏按钮的图标**不是"窗口图标优先"**：进程没声明 AppUserModelID
    时，系统按**可执行文件路径**推断 —— 而我们是 `pythonw.exe` 跑脚本，于是任务栏
    一直显示 Python 的图标，跟窗口图标怎么设都对不上
    （主人 2026-10-08 反馈"底栏图标还是旧的"就是这个原因）。

    必须在**创建任何窗口之前**调用。
    """
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        return True
    except (AttributeError, OSError):
        return False


def tray_image() -> Image.Image | None:
    """托盘图标。读不到返回 None，由调用方决定怎么兜底。"""
    try:
        return Image.open(asset_dir() / "icon.png").convert("RGBA")
    except (OSError, ValueError):
        return None


def _metric(index: int) -> int:
    try:
        return int(ctypes.windll.user32.GetSystemMetrics(index))
    except (AttributeError, OSError):
        return 0


def _load_hicon(path: Path, cx: int, cy: int) -> int:
    """从 .ico 里按**指定像素尺寸**取一个 HICON（带缓存）。"""
    if cx <= 0 or cy <= 0:
        return 0
    key = (str(path), cx, cy)
    cached = _HICON_CACHE.get(key)
    if cached:
        return cached

    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.LoadImageW.restype = ctypes.c_void_p
    handle = user32.LoadImageW(
        None, str(path), IMAGE_ICON, cx, cy, LR_LOADFROMFILE
    )
    handle = int(handle or 0)
    if handle:
        _HICON_CACHE[key] = handle
    return handle


def _set_exact_icons(win: tk.Misc, ico: Path) -> bool:
    """按系统**要求的尺寸**分别设置 ICON_SMALL / ICON_BIG。

    ⚠️ 这就是清晰度的关键：Tk 的 `iconbitmap` 只会加载**一个** HICON（按
    `SM_CXICON` = 32×32）并把它同时设给大小两档 —— 实测
    `ICON_BIG=32x32  ICON_SMALL=32x32` 是**同一个句柄**。可标题栏要的是
    16×16，Windows 只能把 32 缩一半，糊就是这么来的。

    这里改成：各按各的尺寸从 .ico 里取对应那一档，1:1 命中，不经过任何缩放。
    """
    hwnd = int(win.frame(), 16)
    if not hwnd:
        return False

    pairs = (
        (ICON_SMALL, _metric(SM_CXSMICON), _metric(SM_CYSMICON)),
        (ICON_BIG, _metric(SM_CXICON), _metric(SM_CYICON)),
    )
    user32 = ctypes.windll.user32
    user32.SendMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.SendMessageW.restype = ctypes.c_void_p

    done = False
    for which, cx, cy in pairs:
        handle = _load_hicon(ico, cx, cy)
        if handle:
            user32.SendMessageW(hwnd, WM_SETICON, which, handle)
            done = True
    return done


def _apply_png_fallback(win: tk.Misc) -> bool:
    """`.ico` 不可用时的退路：用 PNG 列表。"""
    photos: list[tk.PhotoImage] | None = getattr(win, "_app_icon_photos", None)
    try:
        if photos is None:
            photos = []
            for size in TK_SIZES:
                path = asset_dir() / f"icon_{size}.png"
                if path.exists():
                    photos.append(tk.PhotoImage(master=win, file=str(path)))
            setattr(win, "_app_icon_photos", photos)
        if not photos:
            return False
        win.iconphoto(True, *photos)
        return True
    except (tk.TclError, OSError):
        return False


def apply_tk_icon(win: tk.Misc) -> bool:
    """给窗口设图标（标题栏 + 任务栏 + Alt+Tab）。

    两步走：

    1. `iconbitmap(default=...)` —— 把默认图标挂上，这样**之后新建的 Toplevel**
       （结果窗口等）至少有个图标；
    2. `_set_exact_icons()` —— 再用 Win32 按系统要求的尺寸精确修正**本窗口**的
       大小两档图标（见该函数的说明，清晰度全靠这一步）。

    **幂等**，可以放心在每次窗口被映射（deiconify）时重设一遍：窗口 `withdraw()`
    时 Tk 会销毁底层 wrapper，重建之后不补设，标题栏左侧就是一片空白。
    """
    ico = asset_dir() / "icon.ico"
    if not ico.exists():
        return _apply_png_fallback(win)

    ok = False
    try:
        win.iconbitmap(default=str(ico))
        ok = True
    except tk.TclError:
        pass
    try:
        ok = _set_exact_icons(win, ico) or ok
    except (tk.TclError, AttributeError, OSError, ValueError):
        pass
    return ok
