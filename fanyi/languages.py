"""语言定义层。

把"用户看到的语言"（简体中文 / 英语）与"各翻译后端使用的代码"解耦。

**为什么没有繁体中文**：繁体只是同一语言的另一种字形，把它当成一种"语言"
会连带出一整套麻烦——目标语言多一项、界面语言多一项、还要引入 OpenCC 做
字形转换、翻译缓存要按字形分开存、LLM 提示词要额外叮嘱"不要输出简体"。
而实际需求通常是"看懂繁体内容"，这一点**读**就能满足：OCR 字典本身含繁体字，
后端也能正确识别繁体输入，译文按目标语言（简体中文）输出即可。

因此这里只保留简体中文与英语两种。
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
EN = "en"

#: 本项目支持的语言，顺序即 UI 中的展示顺序
SUPPORTED: List[str] = [ZH_HANS, EN]


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


def is_legacy_hant(code: str) -> bool:
    """判断是否为已被移除的繁体中文字形代码。

    保留这个判断是为了**兼容旧数据**：老配置里可能写着 ``zh-Hant``，
    命令行可能有人传 ``zh-TW``，后端也可能回传这些标签。
    它们指向的仍是中文，应当被当作简体中文处理，而不是"未知语言"。
    """
    key = (code or "").strip().replace("_", "-").lower()
    if key == "zh-hant" or key.startswith("zh-hant-"):
        return True
    # zh-TW / zh-HK / zh-MO / zh-CHT 都是繁体写法
    return any(tag in key for tag in ("-tw", "-hk", "-mo", "cht"))


def normalize_code(code: str) -> str:
    """把外部输入的语言代码规范成内部代码。

    主要处理两件事：繁体中文字形标签归到简体中文；``AUTO`` 原样保留。
    未知代码原样返回，由调用方决定如何提示。
    """
    if not code:
        return code
    if code == AUTO:
        return AUTO
    if is_legacy_hant(code):
        return ZH_HANS
    return code


def is_supported(code: str) -> bool:
    """该语言代码是否为受支持的**目标**语言。"""
    return code in LANGUAGES


def info(code: str) -> LanguageInfo:
    """取语言元信息。

    对**未知代码不抛异常**，而是退回"语言中立"的条目：

    后端返回的检测语言可能超出我们支持的两种。实测 Bing 会把
    ``Transformer``、``claude-3-5-sonnet`` 这类短词判成 ``fr``（法语）、
    把 ``v1.2.3-beta`` 判成 ``et``（爱沙尼亚语）。之前这里直接
    ``raise ValueError``，异常冒到翻译服务后被当成"后端失败"，
    于是整条翻译失败并回退到下一个后端——用户看到的就是"经常翻译失败"。

    现在未知代码按"未知语言"处理：既能正常翻译，也不会因为一个字
    没识别出来就整句放弃。
    """
    if code == AUTO:
        return AUTO_INFO
    found = LANGUAGES.get(code)
    if found is not None:
        return found
    return UNKNOWN_INFO


#: 兜底条目：调用方拿到它不会崩，只是不按 CJK 断行
UNKNOWN_INFO = LanguageInfo(
    code="und",
    label_zh="未知语言",
    label_en="Unknown",
    default="und",
)


def label(code: str) -> str:
    """语言的显示名，跟随当前界面语言。

    * 简体中文界面 → ``简体中文`` / ``英语``
    * 英语界面     → ``Chinese (Simplified)`` / ``English``

    传入繁体中文字形标签（``zh-Hant`` / ``zh-TW``）时按简体中文显示，
    避免旧配置或后端回传这类标签时界面出现"未知语言"。
    """
    info_ = info(normalize_code(code))
    if _current_ui_language() == EN:
        return _EN_NAMES.get(info_.code, info_.label_zh)
    return info_.label_zh


# ---------------------------------------------------------------------------
# 界面语言（由界面层注入，避免核心层反向依赖 ui）
# ---------------------------------------------------------------------------
#: 由 :mod:`fanyi.ui.i18n` 注入的"当前界面语言"取值函数。
#: 之所以用注入而不是直接 import：languages 属于核心层，ui.i18n 依赖它，
#: 反向导入会形成循环依赖。未注入时一律返回中文名，核心层仍可独立使用。
_ui_language_getter = None

_EN_NAMES = {
    ZH_HANS: "Chinese (Simplified)",
    EN: "English",
    AUTO: "Auto detect",
    "und": "Unknown",
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
    """把后端返回的语言代码（en / zh-CN / zh-TW / zh-Hant …）归一化为内部代码。

    繁体相关的标签（``zh-TW`` / ``zh-Hant`` …）统一归到简体中文：
    这两者只是字形差别，翻译能力上属于同一种语言。这样后端即使回传
    ``zh-TW``，本工具也不会把它当成"未知语言"。
    """
    if not raw:
        return AUTO
    key = raw.strip().replace("_", "-").lower()
    if key in ("auto", "autodetect", "auto-detect", ""):
        return AUTO
    if key.startswith("zh"):
        return ZH_HANS
    if key.startswith("en"):
        return EN
    # 未支持的语言原样返回，交由上层展示（如 "ja"）
    return key


# ---------------------------------------------------------------------------
# 文本工具
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def has_cjk(text: str) -> bool:
    """文本中是否含有中日韩表意文字。"""
    return bool(_CJK_RE.search(text))


def needs_script_conversion(source: str, target: str) -> bool:
    """是否需要本地字形规范化。

    保留此函数是为了兼容既有调用点，**现在恒为 False**：
    简繁转换已随繁体选项一并移除，译文直接采用后端返回的字形。
    """
    return False


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
