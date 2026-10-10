"""语言定义层。

把"用户看到的语言"（简体中文 / 繁体中文 / English）与"各翻译后端使用的代码"解耦，
并在中简/中繁之间做本地字形转换（在线引擎通常只区分 zh-CN，不区分字形）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 语言标识
# ---------------------------------------------------------------------------

AUTO = "auto"
ZH_HANS = "zh-Hans"
ZH_HANT = "zh-Hant"
EN = "en"

#: 本项目支持的语言，顺序即 UI 中的展示顺序
SUPPORTED: List[str] = [ZH_HANS, ZH_HANT, EN]


@dataclass(frozen=True)
class LanguageInfo:
    """一种语言的元信息及它在各后端中的代码映射。"""

    code: str
    label_zh: str
    label_en: str
    #: 各后端使用的语言代码；未列出的后端回退到 `default`
    provider_codes: Dict[str, str] = field(default_factory=dict)
    #: 默认后端代码
    default: str = ""
    #: 该语言是否使用中日韩表意文字（影响断行拼接策略）
    cjk: bool = False

    def code_for(self, provider: str) -> str:
        """返回该语言在指定后端中的代码。"""
        return self.provider_codes.get(provider, self.default)


LANGUAGES: Dict[str, LanguageInfo] = {
    ZH_HANS: LanguageInfo(
        code=ZH_HANS,
        label_zh="简体中文",
        label_en="Chinese (Simplified)",
        provider_codes={
            "google": "zh-CN",
            "bing": "zh-Hans",
            "mymemory": "zh-CN",
        },
        default="zh-CN",
        cjk=True,
    ),
    ZH_HANT: LanguageInfo(
        code=ZH_HANT,
        label_zh="繁体中文",
        label_en="Chinese (Traditional)",
        provider_codes={
            "google": "zh-TW",
            "bing": "zh-Hant",
            "mymemory": "zh-TW",
        },
        default="zh-TW",
        cjk=True,
    ),
    EN: LanguageInfo(
        code=EN,
        label_zh="英语",
        label_en="English",
        provider_codes={"google": "en", "bing": "en", "mymemory": "en"},
        default="en",
    ),
}

#: 虚拟的"自动检测"语言
AUTO_INFO = LanguageInfo(
    code=AUTO,
    label_zh="自动检测",
    label_en="Auto detect",
    provider_codes={"google": "auto", "bing": "auto-detect", "mymemory": "Autodetect"},
    default="auto",
)


def is_supported(code: str) -> bool:
    """该语言代码是否为受支持的**目标**语言。"""
    return code in LANGUAGES


def info(code: str) -> LanguageInfo:
    """取语言元信息，`auto` 返回自动检测项。"""
    if code == AUTO:
        return AUTO_INFO
    try:
        return LANGUAGES[code]
    except KeyError:  # pragma: no cover - 防御性
        raise ValueError(f"不支持的语言代码: {code!r}") from None


def label(code: str) -> str:
    """语言的显示名，跟随当前界面语言。

    * 简体中文界面 → ``简体中文`` / ``英语``
    * 繁体中文界面 → ``簡體中文`` / ``英語``
    * 英语界面     → ``Chinese (Simplified)`` / ``English``
    """
    info_ = info(code)
    ui_language = _current_ui_language()
    if ui_language == EN:
        return _EN_NAMES.get(code, info_.label_zh)
    if ui_language == ZH_HANT:
        return _HANT_NAMES.get(info_.label_zh, info_.label_en)
    return info_.label_zh


# ---------------------------------------------------------------------------
# 界面语言（由界面层注入，避免核心层反向依赖 ui）
# ---------------------------------------------------------------------------
#: 由 :mod:`fanyi.ui.i18n` 注入的"当前界面语言"取值函数。
#: 之所以用注入而不是直接 import：languages 属于核心层，ui.i18n 依赖它，
#: 反向导入会形成循环依赖。未注入时一律返回中文名，核心层仍可独立使用。
_ui_language_getter = None

_HANT_NAMES = {
    "简体中文": "簡體中文",
    "繁体中文": "繁體中文",
    "英语": "英語",
    "自动检测": "自動偵測",
}

_EN_NAMES = {
    ZH_HANS: "Chinese (Simplified)",
    ZH_HANT: "Chinese (Traditional)",
    EN: "English",
    AUTO: "Auto detect",
}


def set_ui_language_getter(getter) -> None:
    """注册界面语言取值函数（由 :mod:`fanyi.ui.i18n` 调用）。"""
    global _ui_language_getter
    _ui_language_getter = getter


def _current_ui_language() -> str:
    if _ui_language_getter is None:
        return ZH_HANS
    try:
        return _ui_language_getter() or ZH_HANS
    except Exception:  # pragma: no cover - 防御性
        return ZH_HANS


def to_provider(code: str, provider: str) -> str:
    """把内部语言代码转成指定后端的代码。"""
    return info(code).code_for(provider)


def from_provider(raw: Optional[str]) -> str:
    """把后端返回的语言代码（可能是 en / zh-CN / zh-TW / zh-Hans …）归一化为内部代码。"""
    if not raw:
        return AUTO
    key = raw.strip().replace("_", "-").lower()
    if key in ("auto", "autodetect", "auto-detect", ""):
        return AUTO
    if key.startswith("zh"):
        # zh-tw / zh-hk / zh-hant / zh-cht → 繁体；其余（zh / zh-cn / zh-hans）→ 简体
        if any(tag in key for tag in ("hant", "tw", "hk", "mo", "cht")):
            return ZH_HANT
        return ZH_HANS
    if key.startswith("en"):
        return EN
    # 未支持的语言原样返回，交由上层展示（如 "ja"）
    return key


# ---------------------------------------------------------------------------
# 字形转换（简体 ↔ 繁体）
# ---------------------------------------------------------------------------

_OPENCC = None
_OPENCC_TRIED = False


def _load_opencc():
    """惰性加载 opencc（可选依赖），失败则返回 None。"""
    global _OPENCC, _OPENCC_TRIED
    if _OPENCC_TRIED:
        return _OPENCC
    _OPENCC_TRIED = True
    try:
        from opencc import OpenCC  # type: ignore

        _OPENCC = OpenCC
    except Exception:
        _OPENCC = None
    return _OPENCC


#: 极简内置兜底词表：仅在缺少 opencc 时使用，覆盖最常见的字形差异
_FALLBACK_S2T = {
    "简": "簡", "体": "體", "汉": "漢", "语": "語", "译": "譯", "这": "這", "个": "個",
    "们": "們", "为": "為", "说": "說", "认": "認", "识": "識", "别": "別", "时": "時",
    "间": "間", "现": "現", "图": "圖", "别": "別", "软": "軟", "件": "件", "电": "電",
    "脑": "腦", "网": "網", "页": "頁", "开": "開", "关": "關", "设": "設", "置": "置",
    "发": "發", "现": "現", "问": "問", "题": "題", "后": "後", "从": "從", "长": "長",
    "车": "車", "东": "東", "马": "馬", "鸟": "鳥", "鱼": "魚", "龙": "龍", "术": "術",
    "应": "應", "该": "該", "种": "種", "样": "樣", "数": "數", "据": "據", "处": "處",
    "理": "理", "统": "統", "计": "計", "过": "過", "还": "還", "进": "進", "运": "運",
    "输": "輸", "转": "轉", "换": "換", "选": "選", "择": "擇", "读": "讀", "写": "寫",
}
_FALLBACK_T2S = {v: k for k, v in _FALLBACK_S2T.items()}

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    """文本中是否含有中日韩表意文字。"""
    return bool(_CJK_RE.search(text))


def convert_script(text: str, target: str) -> str:
    """把中文文本转换成目标字形（zh-Hans / zh-Hant）。

    优先使用 opencc（精确、覆盖全）；不可用时退化为内置常用字表。
    文本不含中文、或目标不是中文时原样返回。
    """
    if not text or target not in (ZH_HANS, ZH_HANT):
        return text
    if not has_cjk(text):
        return text

    OpenCC = _load_opencc()
    if OpenCC is not None:
        config = "t2s" if target == ZH_HANS else "s2t"
        try:
            return OpenCC(config).convert(text)
        except Exception:
            pass

    table = _FALLBACK_T2S if target == ZH_HANS else _FALLBACK_S2T
    return "".join(table.get(ch, ch) for ch in text)


def needs_script_conversion(source: str, target: str) -> bool:
    """给定源语言与目标语言，是否需要本地字形规范化。"""
    if target not in (ZH_HANS, ZH_HANT):
        return False
    return source in (ZH_HANS, ZH_HANT, AUTO)


# ---------------------------------------------------------------------------
# 分行文本的拼接策略
# ---------------------------------------------------------------------------

_SENTENCE_END = "。！？；.!?;:：）)」』】"


def join_lines(lines: List[str], source_lang: str = AUTO) -> str:
    """把 OCR 得到的多行文本拼成一段便于翻译的文本。

    **换行是有意义的信息**：它代表原文的版面分行，也是天然的分句点。
    早期版本把中文行直接相连（``"".join``），结果是"截图翻译工具"和
    紧随其后的英文行粘成 ``截图翻译工具v0.1.0Screenshot translator…``，
    译文跟着乱掉。因此这里一律保留换行，只做两件事：

    1. 行尾是连字符时去掉连字符续接（``trans-`` + ``lation`` → ``translation``）；
    2. 相邻两行首尾都是字母/数字时，把换行换成空格，
       避免跨行粘连成 ``worldScreenshot`` 这种毁掉分词的错误。
    """
    cleaned = [ln.strip() for ln in lines]
    cleaned = [ln for ln in cleaned if ln]
    if not cleaned:
        return ""

    out = cleaned[0]
    for line in cleaned[1:]:
        if out.endswith("-") and len(out) > 1 and out[-2].isascii():
            # 英文单词被换行拆开
            out = out[:-1] + line
        elif out[-1].isascii() and out[-1].isalnum() and line[0].isascii() and line[0].isalnum():
            # 两行首尾都是 ASCII 字母数字，直接换行会粘连，改用空格
            out = out + " " + line
        else:
            out = out + "\n" + line
    return out


def language_choices(include_auto: bool = False) -> List[tuple]:
    """返回 UI 下拉框用的 (代码, 显示名) 列表。"""
    items = [(code, LANGUAGES[code].label_zh) for code in SUPPORTED]
    if include_auto:
        items.insert(0, (AUTO, AUTO_INFO.label_zh))
    return items
