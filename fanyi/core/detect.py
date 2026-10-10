"""按书写系统判断文本大概是什么语言。

用在"源语言=自动检测"的场合：短词（``Transformer``、``Sam Altman``）交给
后端自动检测时，实测 Bing 会把它们判成法语、爱沙尼亚语，于是译出
"变形""十四行诗"这种离谱结果。既然本工具只支持中英三种语言，
用书写系统先判一次，比让后端猜更可靠。

只做"够用"的判断，不引入语言识别依赖：

* 出现拉丁字母且没有汉字 → 按英语处理
* 出现汉字 → 按中文处理（具体简繁由调用方的目标语言决定）
* 两者都有 → 谁多听谁的
* 都没有（纯符号/数字） → 返回 None，保持原样
"""

from __future__ import annotations

import re
from typing import Optional

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN = re.compile(r"[A-Za-z]")

#: 语言代码常量放在这里避免循环导入
_EN = "en"
_ZH_HANS = "zh-Hans"


def dominant_language(text: str) -> Optional[str]:
    """返回 ``"en"`` / ``"zh-Hans"``，判断不了时返回 ``None``。"""
    if not text or not text.strip():
        return None

    cjk = len(_CJK.findall(text))
    latin = len(_LATIN.findall(text))

    if cjk == 0 and latin == 0:
        return None  # 纯数字/符号，没有可翻译的文字
    if cjk == 0:
        return _EN
    if latin == 0:
        return _ZH_HANS
    # 混排：汉字多按中文，否则按英文
    return _ZH_HANS if cjk >= latin else _EN


def resolve_source(text: str, configured: str) -> str:
    """把"自动检测"解析成一个具体语言；其它取值原样返回。"""
    if configured != "auto":
        return configured
    return dominant_language(text) or configured


__all__ = ["dominant_language", "resolve_source"]
