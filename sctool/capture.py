"""截屏基础能力：抓屏、DPI 适配、裁剪。

框选与标注界面在 overlay.py。

⚠️ DPI 适配是核心难点。本机是 2880×1800 屏、**200% 缩放**。进程若不声明
DPI 感知，Windows 会把窗口坐标"虚拟化"（逻辑像素 = 物理像素 / 2），导致
框选区域与实际截取区域严重错位。必须在创建任何 Tk 窗口之前调用
`enable_dpi_awareness()`。
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

import mss
from PIL import Image

_dpi_state: str | None = None


def enable_dpi_awareness() -> str:
    """声明进程为 per-monitor DPI aware。返回状态描述（供日志）。"""
    global _dpi_state
    if _dpi_state is not None:
        return _dpi_state

    try:
        # PROCESS_PER_MONITOR_DPI_AWARE_V2 = 2
        hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)
        if hr == 0:
            _dpi_state = "per-monitor-v2"
            return _dpi_state
        if hr == 0x80070005:  # E_ACCESSDENIED：已被清单或先前调用设定
            _dpi_state = "already-set"
            return _dpi_state
    except (AttributeError, OSError):
        pass

    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            _dpi_state = "system-aware"
            return _dpi_state
    except (AttributeError, OSError):
        pass

    _dpi_state = "failed"
    return _dpi_state


def primary_scale() -> float:
    """主显示器的缩放比例（1.0 = 100%）。"""
    try:
        dc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, dc)
        return dpi / 96.0
    except (AttributeError, OSError):
        return 1.0


@dataclass
class ScreenShot:
    """一张全屏截图（物理像素）及其在虚拟桌面中的位置。"""

    image: Image.Image
    origin: tuple[int, int]

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


def grab_all() -> ScreenShot:
    """抓取整个虚拟桌面（所有显示器拼接）。

    ⚠️ 用 `raw.raw`（底层 bytearray）而不是 `raw.bgra`：后者是个 property，
    每次访问都 `bytes(...)` 复制一份 20MB（2880×1800×4 字节），实测多花 4.3ms。
    两者内容完全相同，只是少一次拷贝。
    """
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        raw = sct.grab(monitor)
        image = Image.frombytes("RGB", raw.size, raw.raw, "raw", "BGRX")
        return ScreenShot(image=image, origin=(monitor["left"], monitor["top"]))


def crop(shot: ScreenShot, box: tuple[int, int, int, int]) -> Image.Image:
    """按框选坐标裁剪（坐标基于截图自身像素）。"""
    x1, y1, x2, y2 = box
    x1, x2 = sorted((max(0, x1), min(shot.image.width, x2)))
    y1, y2 = sorted((max(0, y1), min(shot.image.height, y2)))
    return shot.image.crop((x1, y1, x2, y2))
