"""配置读写：JSON 存于 %LOCALAPPDATA%\\ScreenshotTranslator\\config.json。"""

from __future__ import annotations

import json
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "hotkey": "ctrl+alt+s",
    "ocr_engine": "rapidocr",  # rapidocr | windows
    "translate": {
        #: offline | online | auto。默认「自动」：先用本地模型，本地不可用才转在线。
        "mode": "auto",
        "offline_pair": "",  # ""=按文本自动判断 | en_zh | zh_en
        #: 在线服务商：`openai`=任何 OpenAI 兼容接口（默认）| `youdao`=有道智云
        "online_provider": "openai",
        # ---- OpenAI 兼容（online_provider == "openai"）----
        #: 接口地址，填到 `/v1` 为止（如 http://127.0.0.1:7863/v1）
        "online_base_url": "",
        #: 模型名。**原样传给上游**，可含空格（如 "model group"）
        "online_model": "",
        #: API Key。本地网关通常可留空。
        "online_api_key": "",
        # ---- 有道智云（online_provider == "youdao"）----
        "online_app_key": "",
        "online_app_secret": "",
    },
    #: 保存目录。留空 = `~/Pictures/Screenshots`。
    #: ⚠️ 2026-10-08 之前这条是**静默失效**的：`paths.default_save_dir()` 根本不读它。
    "save_dir": "",
    #: OCR 完成后自动把原文写进剪贴板。
    #: ⚠️ 同样曾经是死字段（定义了但全项目零引用），现在已接上。
    "auto_copy_text": True,
    "show_tray": True,
    #: 开机自启。**实际状态以注册表为准**，这里只记用户最后一次的意图，
    #: 界面初始化时要读注册表而不是读它（用户可能在任务管理器里手动禁用了）。
    "autostart": False,
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """用 override 覆盖 base，嵌套字典逐层合并（避免旧配置缺字段）。"""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load() -> dict[str, Any]:
    path = paths.config_file()
    if not path.exists():
        return json.loads(json.dumps(DEFAULTS))
    try:
        with open(path, "r", encoding="utf-8") as fh:
            user_cfg = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULTS))
    return _deep_merge(DEFAULTS, user_cfg)


def save(cfg: dict[str, Any]) -> None:
    with open(paths.config_file(), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)
