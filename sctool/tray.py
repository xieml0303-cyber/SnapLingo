"""系统托盘常驻（pystray）。

⚠️ 线程模型：`icon.run()` 会阻塞在自己的消息循环里，所以放在后台线程；
菜单回调也在那个线程执行，因此所有回调只做一件事——用 `root.after(0, ...)`
把工作抛回 tkinter 主线程（由 app.py 负责）。
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from . import APP_TITLE

ACCENT = (47, 111, 208, 255)
#: 托盘悬停提示显示的软件名
DEFAULT_TITLE = APP_TITLE


def _fallback_icon(size: int) -> Image.Image:
    """兜底图标：蓝底 + 白色取景框。

    只在 `assets/` 缺失时用 —— 托盘图标**没了**，比图标**不好看**严重得多，
    所以留一条退路。
    """
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        [1, 1, size - 2, size - 2], radius=max(6, size // 6), fill=ACCENT
    )
    margin = size // 5
    draw.rectangle(
        [margin, margin + size // 12, size - margin, size - margin - size // 12],
        outline="white",
        width=max(2, size // 16),
    )
    draw.line(
        [size // 2, margin, size // 2, margin + size // 10],
        fill="white",
        width=max(2, size // 16),
    )
    return image


def make_icon_image(size: int = 256) -> Image.Image:
    """托盘图标：优先用 `assets/icon.png`（主人的 SVG 渲染而来），缺失时退回兜底图。"""
    from . import icons

    image = icons.tray_image()
    if image is None:
        image = _fallback_icon(size)
    if image.size != (size, size):
        image = image.resize((size, size), Image.LANCZOS)
    return image


def write_ico(path: str | Path, sizes: tuple[int, ...] = (16, 32, 48, 64, 128, 256)) -> Path:
    """导出多尺寸 .ico（打包 exe 用）：优先直接复制 `assets/icon.ico`。"""
    from . import icons

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    built = icons.asset_dir() / "icon.ico"
    if built.exists():
        shutil.copyfile(built, target)
        return target
    make_icon_image(256).save(target, format="ICO", sizes=[(s, s) for s in sizes])
    return target


class Tray:
    """托盘图标 + 右键菜单。"""

    def __init__(
        self,
        on_capture: Callable[[], None],
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        title: str = DEFAULT_TITLE,
    ) -> None:
        self.on_capture = on_capture
        self.on_show = on_show
        self.on_quit = on_quit
        self.title = title
        self._icon = None
        self._thread: threading.Thread | None = None
        self._failed = False

    def start(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("开始截图", lambda: self.on_capture(), default=True),
            pystray.MenuItem("显示主窗口", lambda: self.on_show()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.on_quit()),
        )
        self._icon = pystray.Icon(
            "screenshot_translator", make_icon_image(), self.title, menu
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        # 等一小会儿，确认托盘真的起来了。`icon.run()` 一旦抛异常线程会立刻结束，
        # 据此就能判断失败。这个判断很关键 —— 托盘没起来、主窗口又"关到托盘"了，
        # 程序就再也找不回来（app 那边会据此退化成"关闭即退出"）。
        for _ in range(24):
            time.sleep(0.05)
            if not self._thread.is_alive():
                self._failed = True
                break
            if self._icon.visible:
                break

    def _run(self) -> None:
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001 - 线程里的异常必须自己兜，否则托盘静默消失
            self._failed = True

    @property
    def ok(self) -> bool:
        """托盘可用吗？（`start()` 返回之后这个值才有意义）"""
        return (
            self._icon is not None
            and not self._failed
            and self._thread is not None
            and self._thread.is_alive()
        )

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001 - 退出流程不该因托盘失败而中断
            pass
        self._icon = None
