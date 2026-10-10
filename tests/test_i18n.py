"""单元测试：界面多语言目录的完整性与一致性。

守住两类很容易悄悄出现的问题：

1. 代码里包了 ``tr("...")`` 但 ``ENGLISH`` 里没有这个键
   —— 英文界面下会直接显示中文，而且很难被发现（要正好点到那个界面）；
2. 英文模板里的 ``{占位符}`` 与中文原文不一致
   —— 运行到那一行会抛 ``KeyError`` 或漏掉插值。

第 1 类靠扫描源码自动发现，不依赖人工记忆。
"""

from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

from fanyi.languages import ZH_HANS, ZH_HANT
from fanyi.ui import i18n
from fanyi.ui.i18n import ENGLISH, catalog, language_display_name, set_language, tr, trn

ROOT = Path(__file__).resolve().parent.parent

#: 会被扫描的界面代码（核心层不参与：那里的文案由界面层传入）
UI_FILES = [
    "fanyi/app.py",
    "fanyi/overlay.py",
    "fanyi/instance.py",
    "fanyi/ui/activate.py",
    "fanyi/ui/controller.py",
    "fanyi/ui/history_panel.py",
    "fanyi/ui/hotkey_edit.py",
    "fanyi/ui/main_window.py",
    "fanyi/ui/result_window.py",
    "fanyi/ui/tray.py",
]


def collect_keys(path: Path) -> set:
    """收集源码里所有 ``tr(...)`` / ``trn(...)`` 用到的字符串键。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = path.read_text(encoding="utf-8").splitlines()
    keys = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("tr", "trn"):
                # 带 noqa: i18n 的行表示有意不翻译（例如托盘图标上的标识字）
                line = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
                if "noqa: i18n" in line:
                    continue
                for arg in node.args:
                    # 支持隐式拼接（多个常量组成一个键）
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        keys.add(arg.value)
                    elif isinstance(arg, ast.JoinedStr):
                        # f-string 作为键是不对的，交给别的检查
                        continue
    return keys


def placeholders(text: str) -> set:
    """提取 ``{name}`` 形式的字段名（忽略 ``{}`` 与位置参数）。"""
    names = set()
    for _literal, field, _spec, _conv in string.Formatter().parse(text):
        if field:
            names.add(field.split(".")[0].split("[")[0])
    return names


# ---------------------------------------------------------------------------
# 目录完整性
# ---------------------------------------------------------------------------
class TestCatalogCompleteness:
    def test_every_used_key_exists_in_english(self):
        """回归：曾经有 3 个键包了 tr() 但字典里没有，英文界面露出中文。"""
        missing = {}
        for relative in UI_FILES:
            path = ROOT / relative
            if not path.exists():
                continue
            absent = sorted(k for k in collect_keys(path) if k not in ENGLISH)
            if absent:
                missing[relative] = absent

        assert not missing, (
            "以下文件里的 tr() 键在 ENGLISH 中缺失（英文界面会显示中文）：\n"
            + "\n".join(f"  {f}: {keys}" for f, keys in missing.items())
        )

    def test_no_empty_translations(self):
        empty = [key for key, value in ENGLISH.items() if not value.strip()]
        assert not empty, f"存在空翻译: {empty}"

    def test_keys_are_unique_by_construction(self):
        # 字典本身保证唯一，这里确认没有"键值都是自身"的漏翻占位
        suspicious = [
            key for key, value in ENGLISH.items() if key == value and any("\u4e00" <= c <= "\u9fff" for c in key)
        ]
        assert not suspicious, f"中英文完全相同的条目，疑似漏翻: {suspicious}"


class TestPlaceholders:
    @pytest.mark.parametrize("key", sorted(k for k in ENGLISH if "{" in k))
    def test_placeholder_names_match(self, key):
        """英文模板的占位符必须与中文原文一致，否则 format 会报错。"""
        assert placeholders(ENGLISH[key]) == placeholders(key), (
            f"占位符不一致：\n  中文 {key!r} -> {placeholders(key)}\n"
            f"  英文 {ENGLISH[key]!r} -> {placeholders(ENGLISH[key])}"
        )


# ---------------------------------------------------------------------------
# 查询行为
# ---------------------------------------------------------------------------
class TestLookup:
    def test_simplified_returns_source_text(self):
        set_language(ZH_HANS)
        assert tr("设置") == "设置"
        assert tr("这条文案不在目录里") == "这条文案不在目录里"

    def test_english_lookup(self):
        set_language("en")
        assert tr("设置") == "Settings"
        set_language(ZH_HANS)

    def test_traditional_is_generated(self):
        set_language(ZH_HANT)
        assert tr("设置") == "設置"
        assert tr("快捷键") == "快捷鍵"
        set_language(ZH_HANS)

    def test_unknown_key_falls_back_to_source(self):
        """漏翻只显示中文，不会变成看不懂的占位符。"""
        set_language("en")
        assert tr("这段文案故意没有翻译") == "这段文案故意没有翻译"
        set_language(ZH_HANS)

    def test_trn_formats(self):
        set_language("en")
        assert trn("共 {count} 条", count=5) == "5 entries"
        set_language(ZH_HANS)

    def test_trn_bad_placeholder_falls_back(self):
        set_language("en")
        # 缺参数时回退原文，而不是抛异常打断界面
        assert trn("共 {count} 条") == "共 {count} 条"
        set_language(ZH_HANS)

    def test_untranslated_helper(self):
        assert i18n.untranslated(ZH_HANS) == []
        assert i18n.untranslated("en") == []

    def test_key_of_round_trip(self):
        set_language("en")
        assert i18n.key_of("Settings") == "设置"
        assert i18n.key_of("设置") == "设置"
        set_language(ZH_HANS)


# ---------------------------------------------------------------------------
# 界面语言显示名
# ---------------------------------------------------------------------------
class TestLanguageNames:
    def test_names_follow_ui_language(self):
        assert language_display_name(ZH_HANS, ZH_HANS) == "简体中文"
        assert language_display_name(ZH_HANS, ZH_HANT) == "簡體中文"
        assert language_display_name(ZH_HANS, "en") == "Chinese (Simplified)"

    def test_english_ui_has_no_cjk(self):
        for code in i18n.UI_LANGUAGES:
            name = language_display_name(code, "en")
            assert not any("\u4e00" <= c <= "\u9fff" for c in name), name

    def test_supported_languages(self):
        assert set(i18n.UI_LANGUAGES) == {ZH_HANS, ZH_HANT, "en"}
        assert i18n.is_supported("en")
        assert not i18n.is_supported("ja")
