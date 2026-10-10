"""OCR 引擎封装。

主引擎 RapidOCR（onnxruntime）：实测中文零拆字、英文分词正确。
备选引擎 Windows 内置 OCR（winrt）：零依赖但会拆字、插空格，作为兜底。

统一产出 `TextLine` 列表，再由 `lines_to_text` 按视觉行重组为文本。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image


@dataclass
class TextLine:
    """一块识别出来的文字。"""

    text: str
    box: tuple[float, float, float, float]  # x1, y1, x2, y2
    score: float = 1.0


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> list[TextLine]:
        ...


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF  # 基本汉字
        or 0x3400 <= code <= 0x4DBF  # 扩展 A
        or 0x3000 <= code <= 0x303F  # 中文标点
        or 0xFF00 <= code <= 0xFFEF  # 全角
    )


def _join_row(texts: list[str]) -> str:
    """同一视觉行内的多块文字拼接：中文之间不加空格，其余加空格。"""
    out = ""
    for text in texts:
        if not text:
            continue
        if out and not (_is_cjk(out[-1]) and _is_cjk(text[0])):
            out += " "
        out += text
    return out


def lines_to_text(lines: list[TextLine]) -> str:
    """按视觉行重组文本：先按 y 聚类成行，行内按 x 排序。

    RapidOCR 一般已按阅读顺序返回，但多列/多块布局仍需自己排一次。
    """
    if not lines:
        return ""

    rows: list[list[TextLine]] = []
    for line in sorted(lines, key=lambda item: item.box[1]):
        center_y = (line.box[1] + line.box[3]) / 2
        height = max(line.box[3] - line.box[1], 8)

        for row in rows:
            row_center = sum((item.box[1] + item.box[3]) / 2 for item in row) / len(row)
            if abs(center_y - row_center) < height * 0.6:
                row.append(line)
                break
        else:
            rows.append([line])

    rows.sort(key=lambda row: min(item.box[1] for item in row))

    result: list[str] = []
    for row in rows:
        row.sort(key=lambda item: item.box[0])
        text = _join_row([item.text for item in row])
        if text.strip():
            result.append(text)
    return "\n".join(result)


class RapidOcrEngine:
    """RapidOCR（PaddleOCR 模型转 ONNX，CPU 推理）。"""

    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    def _lazy(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image: Image.Image) -> list[TextLine]:
        # RapidOCR 走 OpenCV，输入按 BGR 约定
        array = np.ascontiguousarray(np.asarray(image.convert("RGB"))[:, :, ::-1])
        result, _elapse = self._lazy()(array)

        lines: list[TextLine] = []
        for item in result or []:
            box, text, score = item[0], item[1], item[2]
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            lines.append(
                TextLine(
                    text=str(text),
                    box=(min(xs), min(ys), max(xs), max(ys)),
                    score=float(score),
                )
            )
        return lines


class WindowsOcrEngine:
    """Windows 内置 OCR（Windows.Media.Ocr）。中文语言包需已安装。

    实测质量弱于 RapidOCR（会拆字、中文间插空格），仅作兜底。
    """

    name = "windows"

    def __init__(self, language: str = "zh-Hans-CN") -> None:
        self.language = language
        self._engine = None

    def _lazy(self):
        if self._engine is None:
            from winrt.windows.globalization import Language
            from winrt.windows.media.ocr import OcrEngine

            self._engine = OcrEngine.try_create_from_language(Language(self.language))
            if self._engine is None:
                raise RuntimeError(
                    f"系统未安装 OCR 语言包 {self.language}，请改用 rapidocr 引擎"
                )
        return self._engine

    def recognize(self, image: Image.Image) -> list[TextLine]:
        import asyncio
        import io

        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        async def _run() -> list[TextLine]:
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="PNG")

            stream = InMemoryRandomAccessStream()
            writer = DataWriter(stream)
            writer.write_bytes(buffer.getvalue())
            await writer.store_async()
            await writer.flush_async()
            writer.detach_stream()
            stream.seek(0)

            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await self._lazy().recognize_async(bitmap)

            lines: list[TextLine] = []
            for line in result.lines:
                words = list(line.words)
                if not words:
                    continue
                left = min(word.bounding_rect.x for word in words)
                top = min(word.bounding_rect.y for word in words)
                right = max(
                    word.bounding_rect.x + word.bounding_rect.width for word in words
                )
                bottom = max(
                    word.bounding_rect.y + word.bounding_rect.height for word in words
                )
                lines.append(
                    TextLine(text=line.text, box=(left, top, right, bottom))
                )
            return lines

        return asyncio.run(_run())


def create_engine(name: str = "rapidocr") -> OcrEngine:
    """按名字创建引擎。"""
    if name == "windows":
        return WindowsOcrEngine()
    return RapidOcrEngine()
