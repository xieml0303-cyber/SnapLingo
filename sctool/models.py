"""离线翻译模型管理（Argos / OpenNMT 的 CT2 模型）。

`.argosmodel` 其实就是个 zip，解压后结构：

    metadata.json
    model/
        config.json
        model.bin              <- ctranslate2 模型
        shared_vocabulary.json
    sentencepiece.model        <- 分词器
    stanza/...                 <- 句子分割模型，我们用不上（自己按标点切句），跳过以省 ~50MB

本模块只做「下载 + 解压 + 定位」，不做推理——推理在 translator.py，
用 ctranslate2 + sentencepiece 直接加载，不依赖 argostranslate 库
（那个库会拖起 torch/spacy/stanza，且 import 时会创建 ~/.local 目录，
在本机实测直接 PermissionError 崩溃）。
"""

from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import paths

INDEX_URL = (
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
)

#: 支持的语言对 -> (源语言, 目标语言)
PAIRS: dict[str, tuple[str, str]] = {
    "en_zh": ("en", "zh"),
    "zh_en": ("zh", "en"),
}

_SKIP_PREFIXES = ("stanza/",)


class ModelNotReady(RuntimeError):
    """模型尚未下载。"""


def pair_dir(pair: str) -> Path:
    return paths.models_dir() / pair


def is_installed(pair: str) -> bool:
    """模型文件是否齐全。"""
    root = pair_dir(pair)
    return (root / "model" / "model.bin").is_file() and (
        root / "sentencepiece.model"
    ).is_file()


def installed_pairs() -> list[str]:
    return [pair for pair in PAIRS if is_installed(pair)]


def find_download_url(pair: str, timeout: int = 30) -> str:
    """从官方索引里找出该语言对的下载地址。"""
    if pair not in PAIRS:
        raise ValueError(f"不支持的语言对：{pair}")
    from_code, to_code = PAIRS[pair]

    with urllib.request.urlopen(INDEX_URL, timeout=timeout) as resp:
        index = json.load(resp)

    for entry in index:
        if entry.get("from_code") == from_code and entry.get("to_code") == to_code:
            for link in entry.get("links", []):
                if link.startswith("https://"):
                    return link
    raise ModelNotReady(f"索引中找不到 {from_code} -> {to_code} 的模型")


def download(
    pair: str,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """下载并解压模型，返回模型目录。

    progress(已下载字节, 总字节) 用于进度展示；总字节未知时为 0。
    """
    dest = pair_dir(pair)
    paths.assert_ascii_path(dest)

    url = find_download_url(pair)
    archive = paths.models_dir() / f"{pair}.argosmodel"

    request = urllib.request.Request(url, headers={"User-Agent": "ScreenshotTranslator"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(archive, "wb") as fh:
            while chunk := resp.read(1024 * 256):
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)

    _extract(archive, dest)
    archive.unlink(missing_ok=True)
    return dest


def _extract(archive: Path, dest: Path) -> None:
    """解压模型包，跳过 stanza（省空间），并防御 zip 目录穿越。"""
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()

    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/") or name.startswith(_SKIP_PREFIXES):
                continue
            if name in {"README.md", "metadata.json"}:
                continue

            target = (dest / name).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise RuntimeError(f"压缩包路径越界，疑似恶意文件：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())


def ensure_installed(
    pair: str,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """确保模型就绪，缺则下载。"""
    if is_installed(pair):
        return pair_dir(pair)
    return download(pair, progress=progress)
