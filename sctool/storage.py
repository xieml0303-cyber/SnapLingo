"""保存与历史记录。

历史目录结构（%LOCALAPPDATA%\\ScreenshotTranslator\\history\\）：
    images/20261008-101530-123.png
    index.jsonl                      每行一条 JSON 元数据
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import paths

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass
class HistoryEntry:
    id: str
    created: str
    image: str  # 相对 history/images 的文件名
    text: str = ""
    translation: str = ""


def timestamp_name(suffix: str = ".png") -> str:
    now = datetime.now()
    millis = int(time.time() * 1000) % 1000
    return now.strftime("%Y%m%d-%H%M%S") + f"-{millis:03d}" + suffix


def _images_dir() -> Path:
    path = paths.history_dir() / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_file() -> Path:
    return paths.history_dir() / "index.jsonl"


def _normalize_target(target: Path | str | None, default_name: str) -> Path:
    """把用户给的路径规整成最终文件名。"""
    if target is None:
        return paths.default_save_dir() / default_name

    path = Path(target)
    if path.is_dir():
        return path / default_name
    if path.suffix.lower() not in IMAGE_SUFFIXES and path.suffix == "":
        return path.with_suffix(Path(default_name).suffix)
    return path


def save_image(image: Image.Image, target: Path | str | None = None) -> Path:
    """保存截图，返回最终路径。"""
    path = _normalize_target(target, f"截图-{timestamp_name()}")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def save_text(text: str, target: Path | str | None = None) -> Path:
    """保存文本（默认 .txt）。"""
    if target is None:
        path = paths.default_save_dir() / f"文字-{timestamp_name('.txt')}"
    else:
        path = Path(target)
        if path.is_dir():
            path = path / f"文字-{timestamp_name('.txt')}"
        elif path.suffix == "":
            path = path.with_suffix(".txt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def add_history(
    image: Image.Image,
    text: str = "",
    translation: str = "",
) -> HistoryEntry:
    """把一次截图结果写入历史。"""
    name = timestamp_name()
    image_path = _images_dir() / name
    image.save(image_path)

    entry = HistoryEntry(
        id=name.rsplit(".", 1)[0],
        created=datetime.now().isoformat(timespec="seconds"),
        image=name,
        text=text,
        translation=translation,
    )
    with open(_index_file(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    return entry


def list_history(limit: int = 200) -> list[HistoryEntry]:
    """读取历史（最新的在前）。"""
    index = _index_file()
    if not index.is_file():
        return []

    entries: list[HistoryEntry] = []
    with open(index, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(HistoryEntry(**json.loads(raw)))
            except (json.JSONDecodeError, TypeError):
                continue  # 跳过损坏行，不让一条坏数据毁掉整份历史
    entries.reverse()
    return entries[:limit]


def image_path(entry: HistoryEntry) -> Path:
    return _images_dir() / entry.image


def update_translation(entry_id: str, translation: str) -> bool:
    """把译文补写进已存在的历史条目（OCR 完成时先建条目，翻译后再回填）。

    返回是否找到并更新了该条目。
    """
    index = _index_file()
    if not index.is_file():
        return False

    lines: list[str] = []
    found = False
    with open(index, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                lines.append(raw)  # 保留损坏行，不因一条坏数据丢整份历史
                continue
            if data.get("id") == entry_id:
                data["translation"] = translation
                found = True
            lines.append(json.dumps(data, ensure_ascii=False))

    if found:
        with open(index, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return found


def clear_history() -> None:
    """清空历史（删除图片与索引）。"""
    for item in _images_dir().glob("*"):
        item.unlink(missing_ok=True)
    _index_file().unlink(missing_ok=True)
