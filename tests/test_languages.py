"""语言层的单元测试：分行拼接、简繁转换、代码归一化。"""

from __future__ import annotations

import pytest

from fanyi import languages as L


# ---------------------------------------------------------------------------
# 分行拼接
# ---------------------------------------------------------------------------
class TestJoinLines:
    def test_separate_lines_keep_newline(self):
        # 换行代表原文分行，是天然分句点，必须保留
        assert L.join_lines(["你好，", "世界"], "zh-Hans") == "你好，\n世界"

    def test_cjk_line_then_latin_line_keeps_newline(self):
        # 回归：曾经把中文行直接相连，导致中文行尾与下一行英文粘连成 "工具v0.1.0英文…"
        joined = L.join_lines(["截图翻译工具", "Screenshot translator"], "zh-Hans")
        assert joined == "截图翻译工具\nScreenshot translator"

    def test_ascii_ending_cjk_line_gets_space_before_latin(self):
        # 上一行以 ASCII 字母数字结尾、下一行也以 ASCII 开头 → 直接换行会粘连，改补空格
        joined = L.join_lines(["截图翻译工具 v0.1.0", "Screenshot translator"], "zh-Hans")
        assert joined == "截图翻译工具 v0.1.0 Screenshot translator"
        assert "0Screenshot" not in joined

    def test_adjacent_ascii_lines_joined_with_space(self):
        # 两行首尾都是字母数字，直接换行会粘连成 worldScreenshot
        assert L.join_lines(["Hello world", "Screenshot tool"], "en") == "Hello world Screenshot tool"

    def test_latin_hyphen_wrapped_word(self):
        assert L.join_lines(["trans-", "lation"], "en") == "translation"

    def test_chinese_hyphen_not_merged(self):
        # 中文里的连字符是内容，不能当成英文断词
        assert L.join_lines(["一二—", "三四"], "zh-Hans") == "一二—\n三四"

    def test_blank_lines_ignored(self):
        assert L.join_lines(["  ", "abc", "", "  def "], "en") == "abc def"

    def test_empty_input(self):
        assert L.join_lines([], "en") == ""
        assert L.join_lines(["", "   "], "zh-Hans") == ""

    def test_single_line_unchanged(self):
        assert L.join_lines(["就一行"], "zh-Hans") == "就一行"

    def test_mixed_script_boundary_no_space_needed(self):
        # 中文行尾接英文行首不会粘连（字符类型不同），保留换行即可
        assert L.join_lines(["这是中文", "English line"], "zh-Hans") == "这是中文\nEnglish line"

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


def test_info_falls_back_for_unknown_code():
    """回归：未知语言代码不能抛异常。

    Bing 会把 ``Transformer``、``claude-3-5-sonnet`` 这类短词检测成 ``fr``、
    把 ``v1.2.3-beta`` 检测成 ``et``。早期实现让 ``info()`` 抛 ValueError，
    异常冒到翻译服务后被当成「后端失败」，用户看到的是「翻译经常失败」。
    现在未知代码按「未知语言」处理，翻译照常进行。
    """
    for code in ("fr", "et", "ja", "und", "zh-Hant-TW"):
        assert L.info(code).code == "und", code
    assert L.info("auto").label_zh == "自动检测"


def test_label_of_unknown_code_does_not_crash():
    assert L.label("fr") == "未知语言"


def test_is_supported():
    assert L.is_supported("en")
    assert not L.is_supported("auto")
    assert not L.is_supported("ja")
