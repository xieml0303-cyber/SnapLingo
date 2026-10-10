"""应用路径策略。

⚠️ 关键约束：所有交给 C++ 库（sentencepiece / ctranslate2 / onnxruntime）的路径
必须是纯 ASCII。

实测证据（2026-10-08）：把 Argos 模型放在含中文的目录
（形如 `<用户目录>\\.zcode\\截屏工具\\...`）下，sentencepiece 报
`NOT_FOUND: ...\\sentencepiece.model`，而文件确实存在——C++ 侧用窄字符 API
按系统 ANSI 代码页解析路径，中文会失败。挪到纯 ASCII 路径后立刻正常。

因此本应用的所有数据一律放 `%LOCALAPPDATA%\\ScreenshotTranslator`。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 数据目录名。⚠️ **永远不要改** —— 改了会让配置、历史、已下载的离线模型全部失联。
#: 它跟对外显示的软件名（`sctool.APP_TITLE = "截屏工具"`）是两回事：
#: 一个是磁盘上的目录，一个是给人看的名字。
APP_NAME = "ScreenshotTranslator"


def data_dir() -> Path:
    """应用数据根目录（保证纯 ASCII）。"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    """离线翻译模型目录。"""
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir() -> Path:
    """历史记录（截图 + 文本）目录。"""
    path = data_dir() / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configured_save_dir() -> Path | None:
    """用户在设置里指定的保存目录；没配 / 配坏了都返回 None。

    ⚠️ 这里**不能** `from . import config` —— config 反过来要导入本模块取路径，
    会形成循环导入。所以直接读那个 JSON，代价是几行重复代码。

    ⚠️ 用户填的路径可能是非法盘符或没权限的位置，`mkdir` 失败就当作没配，
    让调用方退回默认目录 —— 保存截图这种基础功能不该因为一条配置坏掉而不可用。
    """
    import json

    try:
        path = config_file()
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as fh:
            value = str((json.load(fh) or {}).get("save_dir", "")).strip()
    except (OSError, ValueError):
        return None
    if not value:
        return None
    try:
        candidate = Path(value).expanduser()
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        return None


def default_save_dir() -> Path:
    """默认保存目录：优先用配置里的 `save_dir`，没配才退回 `~/Pictures/Screenshots`。

    ⚠️ 改造前这个函数**完全不读配置**、硬编码 `~/Pictures/Screenshots`，于是
    config.json 里的 `save_dir` 是一条**静默失效**的死配置 —— 用户改了没有任何
    效果，也收不到任何提示（2026-10-08 排查时发现）。
    """
    base = _configured_save_dir() or (Path.home() / "Pictures" / "Screenshots")
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_file() -> Path:
    return data_dir() / "config.json"


def log_file() -> Path:
    return data_dir() / "app.log"


def is_ascii_path(path: str | Path) -> bool:
    """判断路径能否安全交给 C++ 库。"""
    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def assert_ascii_path(path: str | Path) -> None:
    """在把路径交给 C++ 库前调用，尽早暴露中文路径问题。"""
    if not is_ascii_path(path):
        raise ValueError(
            f"路径含非 ASCII 字符，C++ 库无法打开：{path}\n"
            f"请把模型/数据移到纯英文路径下。"
        )
