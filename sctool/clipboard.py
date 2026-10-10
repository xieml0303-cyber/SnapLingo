"""把 PIL 图片复制到 Windows 剪贴板（CF_DIB）。

tkinter 只能处理文本剪贴板，图片必须走 Win32 API。
"""

from __future__ import annotations

import ctypes
import io

from PIL import Image

CF_DIB = 8
GMEM_MOVEABLE = 0x0002


def copy_image(image: Image.Image) -> None:
    """把图片放进剪贴板（BMP/DIB 格式，可粘贴进 Word、微信、画图等）。"""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, "BMP")
    data = buffer.getvalue()[14:]  # 去掉 14 字节的 BMP 文件头，只留 DIB
    buffer.close()

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # ⚠️ 64 位下必须显式声明指针类型：ctypes 默认按 32 位 int 返回，
    # 会把 GlobalAlloc/GlobalLock 返回的句柄截断，导致 GlobalLock 返回 NULL
    # （表现为"剪贴板内存锁定失败"）。
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    user32.OpenClipboard.argtypes = (ctypes.c_void_p,)
    user32.OpenClipboard.restype = ctypes.c_int
    user32.EmptyClipboard.restype = ctypes.c_int
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.CloseClipboard.restype = ctypes.c_int

    if not user32.OpenClipboard(None):
        raise RuntimeError("无法打开剪贴板")
    try:
        user32.EmptyClipboard()

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise RuntimeError("剪贴板内存分配失败")
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            raise RuntimeError("剪贴板内存锁定失败")
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_DIB, handle):
            raise RuntimeError("写入剪贴板失败")
    finally:
        user32.CloseClipboard()
