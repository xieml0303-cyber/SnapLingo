"""全局热键（keyboard 库）。

⚠️ 三个已知坑：
  1. keyboard 的回调运行在它自己的线程里，**不能直接碰 tkinter**。
     调用方必须用 `root.after(0, ...)` 把工作抛回主线程（见 app.py）。
  2. 目标窗口若以管理员权限运行，非管理员进程的热键可能收不到。
  3. 火绒等杀软会拦截全局键盘钩子，需要把本程序加入白名单。
"""

from __future__ import annotations

from typing import Callable

import keyboard

_handles: list = []


def normalize(hotkey: str) -> str:
    """把 'Ctrl+Alt+S' 规整为 keyboard 库认识的 'ctrl+alt+s'。"""
    parts = [part.strip().lower() for part in hotkey.replace(" ", "").split("+")]
    return "+".join(part for part in parts if part)


def register(hotkey: str, callback: Callable[[], None]) -> str:
    """注册热键，返回规整后的热键字符串。"""
    combo = normalize(hotkey)
    if not combo:
        raise ValueError("热键不能为空")
    _handles.append(keyboard.add_hotkey(combo, callback, suppress=False))
    return combo


def unregister_all() -> None:
    """注销所有热键并卸下钩子（退出时务必调用）。"""
    for handle in _handles:
        try:
            keyboard.remove_hotkey(handle)
        except (KeyError, ValueError):
            pass
    _handles.clear()
    try:
        keyboard.unhook_all()
    except Exception:  # noqa: BLE001 - 卸载失败不该影响退出
        pass
