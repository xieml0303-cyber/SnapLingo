"""翻译：轻量离线（ctranslate2 + sentencepiece）+ 在线 API（有道）。

为什么不直接用 argostranslate 库：
  1. 它会拖起 torch + spacy + stanza（1GB+），启动数秒；
  2. 本机实测其 import 就会 `os.makedirs(~/.local/share/argos-translate)` 抛
     PermissionError 直接崩溃。

因此这里复刻它的核心三步（sentencepiece 分词 → ctranslate2 翻译 → decode），
只依赖 ctranslate2 + sentencepiece（import 仅 0.12s，加载模型 0.18s）。
句子分割用它自带的标点规则替代 stanza。
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass
from typing import Protocol

from . import models, paths

#: 句末标点后切句；英文句点要求后跟空白，避免切碎 3.14 这类数字
_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|(?<=\.)\s+|\n+")


class TranslateError(RuntimeError):
    """翻译失败。"""


@dataclass
class TranslationResult:
    text: str
    provider: str
    source_lang: str
    target_lang: str


class Translator(Protocol):
    name: str

    def translate(self, text: str) -> str:
        ...


def split_sentences(text: str) -> list[str]:
    parts = _SPLIT_RE.split(text)
    return [part.strip() for part in parts if part and part.strip()]


class OfflineTranslator:
    """本地 CT2 模型翻译，完全离线。

    模型首次使用时加载（约 0.2s），之后复用。
    """

    name = "offline"

    def __init__(self, pair: str = "en_zh") -> None:
        if pair not in models.PAIRS:
            raise TranslateError(f"不支持的离线语言对：{pair}")
        self.pair = pair
        self.source_lang, self.target_lang = models.PAIRS[pair]
        self._ct2 = None
        self._sp = None

    # ---------- 加载 ----------

    def is_ready(self) -> bool:
        return models.is_installed(self.pair)

    def _load(self):
        if self._ct2 is not None:
            return
        if not self.is_ready():
            raise TranslateError(
                f"离线模型 {self.pair} 尚未下载。\n"
                f"请在「设置」里下载，或手动放到：{models.pair_dir(self.pair)}"
            )

        import ctranslate2
        import sentencepiece as spm

        root = models.pair_dir(self.pair)
        model_path = root / "model"
        spm_path = root / "sentencepiece.model"

        # C++ 库打不开非 ASCII 路径，提前给出明确报错
        paths.assert_ascii_path(model_path)
        paths.assert_ascii_path(spm_path)

        self._ct2 = ctranslate2.Translator(str(model_path), device="cpu")
        self._sp = spm.SentencePieceProcessor(model_file=str(spm_path))

    # ---------- 翻译 ----------

    def translate(self, text: str) -> str:
        self._load()
        if not text.strip():
            return text

        out_lines: list[str] = []
        for line in text.splitlines():
            if not line.strip():
                out_lines.append("")
                continue
            out_lines.append(self._translate_line(line))
        return "\n".join(out_lines)

    def _translate_line(self, line: str) -> str:
        sentences = split_sentences(line) or [line]
        tokenized = [self._sp.encode(sentence, out_type=str) for sentence in sentences]

        batches = self._ct2.translate_batch(
            tokenized,
            beam_size=4,
            max_batch_size=32,
            replace_unknowns=True,
        )
        pieces = [self._decode(batch.hypotheses[0]) for batch in batches]

        # 中文直接相连；英文句间补空格
        separator = "" if self.target_lang == "zh" else " "
        return separator.join(piece for piece in pieces if piece)

    def _decode(self, tokens: list[str]) -> str:
        text = self._sp.decode_pieces(tokens).replace("▁", " ").replace("_", " ")
        return text.strip()


class YoudaoTranslator:
    """有道智云文本翻译（在线，需 app_key + app_secret）。"""

    name = "youdao"
    ENDPOINT = "https://openapi.youdao.com/api"

    def __init__(self, app_key: str, app_secret: str, source_lang: str = "en",
                 target_lang: str = "zh") -> None:
        if not app_key or not app_secret:
            raise TranslateError("有道翻译需要 app_key 与 app_secret，请在设置里填写")
        self.app_key = app_key
        self.app_secret = app_secret
        self.source_lang = source_lang
        self.target_lang = target_lang

    @staticmethod
    def _truncate(text: str) -> str:
        """有道签名规则：长度 <= 20 取全文，否则取 前10 + 长度 + 后10。"""
        if len(text) <= 20:
            return text
        return f"{text[:10]}{len(text)}{text[-10:]}"

    def translate(self, text: str) -> str:
        import requests

        salt = str(uuid.uuid1())
        curtime = str(int(time.time()))
        sign_src = (
            self.app_key + self._truncate(text) + salt + curtime + self.app_secret
        )
        sign = hashlib.sha256(sign_src.encode("utf-8")).hexdigest()

        payload = {
            "q": text,
            "from": self.source_lang,
            "to": self.target_lang,
            "appKey": self.app_key,
            "salt": salt,
            "sign": sign,
            "signType": "v3",
            "curtime": curtime,
        }
        try:
            resp = requests.post(self.ENDPOINT, data=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise TranslateError(f"在线翻译请求失败：{exc}") from exc

        if data.get("errorCode") != "0":
            raise TranslateError(f"有道返回错误码 {data.get('errorCode')}")

        translations = data.get("translation") or []
        return "\n".join(translations)


#: 离线翻译器缓存。模型加载约 0.2s，缓存后重复翻译不再重新加载，
#: 也避免并发翻译时重复占用内存。
_offline_cache: dict[str, OfflineTranslator] = {}


def get_offline_translator(pair: str) -> OfflineTranslator:
    instance = _offline_cache.get(pair)
    if instance is None:
        instance = OfflineTranslator(pair)
        _offline_cache[pair] = instance
    return instance


class TranslationService:
    """按配置调度离线 / 在线翻译。

    mode:
        offline —— 只用本地模型
        online  —— 只用在线 API
        auto    —— 先本地，本地不可用则转在线
    """

    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg

    def _pair_for(self, text: str) -> str:
        """按文本中文字符占比猜测方向。"""
        chinese = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        return "zh_en" if chinese > len(text) * 0.15 else "en_zh"

    def translate(self, text: str) -> TranslationResult:
        section = self.cfg.get("translate", {})
        mode = section.get("mode", "offline")

        if mode == "online":
            return self._online(text, section)

        pair = section.get("offline_pair") or self._pair_for(text)
        offline = get_offline_translator(pair)
        try:
            result = offline.translate(text)
            return TranslationResult(result, "offline", offline.source_lang,
                                     offline.target_lang)
        except TranslateError:
            if mode == "auto":
                return self._online(text, section)
            raise

    def _online(self, text: str, section: dict) -> TranslationResult:
        provider = section.get("online_provider", "youdao")
        if provider != "youdao":
            raise TranslateError(f"暂不支持的在线服务商：{provider}")

        pair = self._pair_for(text)
        src, dst = models.PAIRS[pair]
        translator = YoudaoTranslator(
            section.get("online_app_key", ""),
            section.get("online_app_secret", ""),
            source_lang=src,
            target_lang=dst,
        )
        return TranslationResult(translator.translate(text), "youdao", src, dst)
