"""语言层的单元测试：分行拼接、简繁转换、代码归一化。"""

from __future__ import annotations

import pytest

from fanyi import languages as L


# ---------------------------------------------------------------------------
# 分行拼接
# ---------------------------------------------------------------------------
class TestJoinLines:
    def test_cjk_lines_are_concatenated_without_space(self):
        assert L.join_lines(["你好，", "世界"], "zh-Hans") == "你好，世界"

    def test_cjk_auto_detected(self):
        assert L.join_lines(["截图", "翻译工具"], "auto") == "截图翻译工具"

    def test_latin_lines_joined_with_space(self):
        assert L.join_lines(["Hello", "world"], "en") == "Hello world"

    def test_latin_hyphen_wrapped_word(self):
        assert L.join_lines(["trans-", "lation"], "en") == "translation"

    def test_latin_sentence_end_keeps_newline(self):
        assert L.join_lines(["Done.", "Next step"], "en") == "Done.\nNext step"

    def test_blank_lines_ignored(self):
        assert L.join_lines(["  ", "abc", "", "  def "], "en") == "abc def"

    def test_empty_input(self):
        assert L.join_lines([], "en") == ""
        assert L.join_lines(["", "   "], "zh-Hans") == ""


# ---------------------------------------------------------------------------
# 语言代码归一化
# ---------------------------------------------------------------------------
class TestProviderCode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("en", "en"),
            ("EN", "en"),
            ("en-US", "en"),
            ("zh", "zh-Hans"),
            ("zh-CN", "zh-Hans"),
            ("zh-Hans", "zh-Hans"),
            ("zh_CHS", "zh-Hans"),
            ("zh-TW", "zh-Hant"),
            ("zh-Hant", "zh-Hant"),
            ("zh-HK", "zh-Hant"),
            ("zh-CHT", "zh-Hant"),
            ("ja", "ja"),
            (None, "auto"),
            ("", "auto"),
            ("auto", "auto"),
            ("auto-detect", "auto"),
            ("Autodetect", "auto"),
        ],
    )
    def test_from_provider(self, raw, expected):
        assert L.from_provider(raw) == expected

    def test_to_provider_uses_mapping(self):
        assert L.to_provider("zh-Hans", "google") == "zh-CN"
        assert L.to_provider("zh-Hant", "google") == "zh-TW"
        assert L.to_provider("zh-Hans", "bing") == "zh-Hans"
        assert L.to_provider("en", "any-engine") == "en"


# ---------------------------------------------------------------------------
# 简繁转换
# ---------------------------------------------------------------------------
class TestConvertScript:
    def test_simplified_to_traditional(self):
        result = L.convert_script("这是一个翻译软件", "zh-Hant")
        assert result != "这是一个翻译软件"
        assert "這" in result or "譯" in result

    def test_round_trip(self):
        original = "这是一个截图翻译软件，用来识别屏幕上的文字。"
        traditional = L.convert_script(original, "zh-Hant")
        assert L.convert_script(traditional, "zh-Hans") == original

    def test_english_untouched(self):
        assert L.convert_script("Hello world", "zh-Hant") == "Hello world"

    def test_non_chinese_target_untouched(self):
        text = "这是一个翻译软件"
        assert L.convert_script(text, "en") == text

    def test_empty(self):
        assert L.convert_script("", "zh-Hant") == ""

    def test_needs_script_conversion(self):
        assert L.needs_script_conversion("auto", "zh-Hant")
        assert L.needs_script_conversion("zh-Hans", "zh-Hant")
        assert not L.needs_script_conversion("en", "zh-Hant")
        assert not L.needs_script_conversion("auto", "en")


# ---------------------------------------------------------------------------
# 其它
# ---------------------------------------------------------------------------
def test_has_cjk():
    assert L.has_cjk("中文")
    assert not L.has_cjk("English only")
    assert L.has_cjk("mixed 中文 text")


def test_language_choices():
    choices = L.language_choices()
    assert [c for c, _ in choices] == ["zh-Hans", "zh-Hant", "en"]
    assert L.language_choices(include_auto=True)[0][0] == "auto"


def test_info_rejects_unknown():
    with pytest.raises(ValueError):
        L.info("fr")
    assert L.info("auto").label_zh == "自动检测"


def test_is_supported():
    assert L.is_supported("en")
    assert not L.is_supported("auto")
    assert not L.is_supported("ja")
