"""翻译适配层的公共契约：结果类型、异常体系、后端基类与文本切分。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..languages import AUTO, has_cjk, info


# ---------------------------------------------------------------------------
# 异常体系
# ---------------------------------------------------------------------------
class TranslationError(Exception):
    """翻译相关错误的基类，带有是否值得换后端重试的语义。"""

    retryable = True


class NetworkError(TranslationError):
    """网络不可达 / 超时。"""

    retryable = True


class RateLimitedError(TranslationError):
    """被限流或额度用尽。"""

    retryable = True


class EngineError(TranslationError):
    """后端返回了非预期内容。"""

    retryable = True


class NoEngineAvailable(TranslationError):
    """所有后端都失败了。"""

    retryable = False

    def __init__(self, message: str, errors: Optional[Dict[str, str]] = None) -> None:
        super().__init__(message)
        self.errors: Dict[str, str] = errors or {}


class TextTooLongError(TranslationError):
    """单次请求文本超长。"""

    retryable = False


# ---------------------------------------------------------------------------
# 结果类型
# ---------------------------------------------------------------------------
@dataclass
class TranslateResult:
    """一次成功翻译的结果。"""

    text: str
    provider: str
    source_lang: str = AUTO
    target_lang: str = ""
    from_cache: bool = False
    #: 实际尝试过的后端（含失败项），便于排错
    attempts: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 后端基类
# ---------------------------------------------------------------------------
class Translator(ABC):
    """翻译后端接口。

    新后端只需实现 :meth:`translate`，并在 :mod:`engine` 中注册即可，
    主流程（回退、缓存、字形归一化）完全无需改动。
    """

    #: 后端唯一标识，同时也是语言代码映射用的 key
    name: str = "base"
    #: UI 中的显示名
    display_name: str = "未命名后端"

    @abstractmethod
    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        """把 ``text`` 从 ``source`` 翻译到 ``target``（内部语言代码）。"""

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """后端当前是否可用（例如本地模型是否已就绪）。"""
        return True

    def close(self) -> None:
        """释放资源。"""

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<{type(self).__name__} name={self.name!r}>"


# ---------------------------------------------------------------------------
# 长文本切分
# ---------------------------------------------------------------------------
def split_text(
    text: str,
    max_chars: int = 1800,
    hard_limit: int = 4800,
) -> List[str]:
    """把长文本切成不超过 ``max_chars`` 的片段。

    切分优先落在换行处，其次落在句末标点，最后才硬切，
    这样既满足接口长度限制，又不会把句子拦腰截断。
    """
    text = text or ""
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks: List[str] = []
    remaining = text

    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = -1
        for sep in ("\n", "。", "！", "？", ". ", "! ", "? ", "；", ";", "，", ",", " "):
            pos = window.rfind(sep)
            if pos > max_chars // 3:
                cut = pos + len(sep)
                break
        if cut <= 0:
            cut = min(max_chars, hard_limit)
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].lstrip()

    if remaining.strip():
        chunks.append(remaining.strip())
    return [c for c in chunks if c]


def choose_joiner(source: str, text: str) -> str:
    """按目标语言习惯决定多行文本拼接符。

    中日韩文本直接相连；拉丁文本用空格，避免把换行带进译文。
    """
    cjk = info(source).cjk if source != AUTO else has_cjk(text)
    return "" if cjk else " "


def join_for_request(lines: Sequence[str], source: str) -> str:
    """把多行 OCR 文本拼成单条请求文本。"""
    cleaned = [ln.strip() for ln in lines if ln and ln.strip()]
    if not cleaned:
        return ""
    return choose_joiner(source, "".join(cleaned)).join(cleaned)
