"""开机自启（写注册表 Run 键）。

位置：`HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` —— 只影响**当前
用户**，不需要管理员权限，也不碰任何系统级设置，卸载时删掉这个值即可。

⚠️ 命令行必须按运行形态分别拼：
    打包后（PyInstaller）→ `sys.executable` 就是 exe 本身；
    开发态（`py -3 main.py`）→ 必须显式带上 main.py 的绝对路径，而且**要挑
    pythonw.exe**：用 python.exe 会在每次开机时弹一个黑色控制台窗口。
⚠️ 路径含空格必须加引号，否则 Windows 会在第一个空格处截断命令行。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: 注册表位置
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
#: 值名（任务管理器 →「启动」标签里显示的就是它）
VALUE_NAME = "ScreenshotTranslator"


def _script_path() -> Path:
    """被启动的 main.py 绝对路径。

    ⚠️ 优先按**包的位置**推导（本文件在 `sctool/` 下，项目根就是它的上上级），
    而不是 `sys.argv[0]` —— argv[0] 只反映"这一次是谁启动的"，从测试脚本或
    第三方启动器进来时会指向别的 .py，写进注册表就成了开机启动一个测试脚本
    （实测踩到过：从探针脚本跑，自启命令指向了探针自己）。
    """
    candidate = Path(__file__).resolve().parent.parent / "main.py"
    if candidate.is_file():
        return candidate
    if sys.argv and sys.argv[0].lower().endswith(".py"):
        return Path(sys.argv[0]).resolve()
    return candidate


def command() -> str:
    """当前形态下的自启命令行（含必要的引号）。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'

    exe = Path(sys.executable)
    for name in ("pythonw.exe", "python.exe"):
        candidate = exe.with_name(name)
        if candidate.is_file():
            exe = candidate
            break
    return f'"{exe}" "{_script_path()}"'


def is_enabled() -> bool:
    """注册表里有没有这个自启项。"""
    try:
        import winreg
    except ImportError:  # 非 Windows
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def set_enabled(flag: bool) -> bool:
    """打开 / 关闭自启，返回**实际**结果（失败时回读注册表，不谎报成功）。"""
    try:
        import winreg
    except ImportError:
        return False

    try:
        if flag:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(
                    key, VALUE_NAME, 0, winreg.REG_SZ, command()
                )
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
    except OSError:
        pass
    return is_enabled()
