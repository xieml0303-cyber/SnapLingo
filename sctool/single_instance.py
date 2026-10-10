"""单实例保护。

⚠️ 这个坑很隐蔽：如果上一个实例还在跑，它占着全局热键，新启动的实例
注册热键会失败——用户按热键时触发的仍然是**旧代码**，表现为
"我明明改了代码/重启了，怎么还是老样子"。

做法：用 pid 文件记录当前实例；启动时若发现旧实例仍在运行，先结束它，
保证「双击启动 = 一定跑最新代码」。

⚠️ 2026-10-08 二次踩坑（就是上面那条症状的真凶）：这里原来用 `tasklist` 解析
文本来判断"这个 PID 还是不是 Python 进程"，而 `subprocess.run` 漏写了
`capture_output=True`，`result.stdout` 是 `None` —— 启动时直接
`AttributeError` 崩掉。表现是「双击 启动.bat 没反应」，而**旧实例还在跑旧代码**，
主人按热键触发的自然是老行为，于是认定"没修好"。

现在改用 Win32 API 直接取进程映像路径，不解析命令行文本，没有编码/解析这类
问题；`main.py` 也把整段单实例保护包进 try —— **它出任何问题都不许挡住启动**。
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from . import paths

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001

#: 这些映像名才算"我们自己人"，避免 PID 复用误杀别的程序。
#: ⚠️ `snaplingo.exe` 必须在列：打包后（PyInstaller）进程映像就是它。只列
#:    `python*.exe` 的话，`replace_previous()` 会认为"旧实例不是我们"，**单实例
#:    保护直接失效** —— 表现为双击两次起两个实例、按一次热键弹两个遮罩
#:    （旧实例占着全局热键，新实例注册失败，触发的还是旧代码）。
#:    运行时还会补上"当前进程自己的 exe 名"，这样 exe 被改名也不会漏。
OWN_IMAGES = {"python.exe", "pythonw.exe", "py.exe", "pyw.exe", "snaplingo.exe"}


def _own_images() -> set[str]:
    """`OWN_IMAGES` + 当前进程自身的 exe 名（打包后就是 `SnapLingo.exe`）。"""
    names = set(OWN_IMAGES)
    try:
        names.add(Path(sys.executable).name.lower())
    except Exception:  # noqa: BLE001
        pass
    return names

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_kernel32.TerminateProcess.restype = wintypes.BOOL
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.GetProcessTimes.restype = wintypes.BOOL
_kernel32.GetProcessTimes.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
]


def _pid_file() -> Path:
    return paths.data_dir() / "app.pid"


def _process_image(pid: int) -> str | None:
    """取进程的可执行文件全路径；进程不存在或没权限就返回 None。"""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return None
        return buffer.value
    finally:
        _kernel32.CloseHandle(handle)


def _process_start(pid: int) -> int | None:
    """取进程创建时间（FILETIME 合成一个整数）；拿不到就返回 None。

    ⚠️ 这个值在**同一个 PID 被复用**时一定会变 —— 它是"这个 PID 还是当初
    那个进程吗"的唯一可靠判据。见 `_is_own_process` 的说明。
    """
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not _kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        _kernel32.CloseHandle(handle)


def _read_pid_file(path: Path) -> tuple[int, int | None]:
    """解析 pid 文件 → (pid, 创建时间或 None)。

    ⚠️ 两种格式都要认：新格式 `"<pid> <创建时间>"`，旧格式 `"<pid>"`。
    旧文件（本改动之前写下的）没有第二段，此时返回 None，调用方退回
    "只比映像名"的行为 —— 保证升级到本版本后**不会因为读不懂旧文件而失去
    单实例保护**。
    """
    parts = path.read_text(encoding="utf-8").strip().split()
    if not parts:
        raise ValueError("空的 pid 文件")
    pid = int(parts[0])
    start = int(parts[1]) if len(parts) > 1 else None
    return pid, start


def _is_own_process(pid: int, expected_start: int | None = None) -> bool:
    """确认该 PID 确实是"我们自己"（Python 或打包后的 `SnapLingo.exe`）。

    ⚠️⚠️ 光比映像名是不够的：PID 会被系统**复用**。若 pid 文件里的 PID 已经
    被分配给另一个恰好也叫 `python.exe` / `py.exe` 的无关程序，只比名字就会
    认错，接着 `TerminateProcess` 把人家**强杀**（无提示、不可逆）。
    所以 pid 文件里一并记下**进程创建时间**，对得上才认。
    `expected_start` 为 None（旧格式文件 / 直接调用）时退回只比映像名。
    """
    image = _process_image(pid)
    if not image:
        return False
    if Path(image).name.lower() not in _own_images():
        return False
    if expected_start is not None:
        actual = _process_start(pid)
        if actual is None or actual != expected_start:
            return False
    return True


def replace_previous() -> int | None:
    """结束上一个实例（如果还活着）。返回被结束的 PID。"""
    pid_file = _pid_file()
    if not pid_file.is_file():
        return None

    try:
        old_pid, old_start = _read_pid_file(pid_file)
    except (OSError, ValueError):
        return None

    if old_pid == os.getpid() or not _is_own_process(old_pid, old_start):
        return None

    handle = _kernel32.OpenProcess(PROCESS_TERMINATE, False, old_pid)
    if not handle:
        return None
    try:
        _kernel32.TerminateProcess(handle, 0)
    finally:
        _kernel32.CloseHandle(handle)

    # 等它**真的**消失再继续：两个实例同时活着的话，两边都会装全局热键钩子，
    # 按一下热键会弹出两个遮罩。最多等 2 秒。
    for _ in range(20):
        if _process_image(old_pid) is None:
            break
        time.sleep(0.1)
    return old_pid


def claim() -> None:
    """登记自己的 PID（+ 创建时间，供下次启动校验）。"""
    try:
        start = _process_start(os.getpid())
        text = "%d %d" % (os.getpid(), start) if start is not None else str(os.getpid())
        _pid_file().write_text(text, encoding="utf-8")
    except OSError:
        pass


def release() -> None:
    """退出时清理（只清理属于自己的那条记录）。"""
    try:
        pid_file = _pid_file()
        if pid_file.is_file():
            pid, _ = _read_pid_file(pid_file)
            if pid == os.getpid():
                pid_file.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
