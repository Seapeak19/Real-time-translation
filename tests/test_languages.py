"""语言层的单元测试：分行拼接、代码归一化、旧繁体标签的兼容。"""

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
            # 繁体已移除：这些字形标签统一归到简体，不能变成"未知语言"
            ("zh-TW", "zh-Hans"),
            ("zh-Hant", "zh-Hans"),
            ("zh-HK", "zh-Hans"),
            ("zh-CHT", "zh-Hans"),
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
        assert L.to_provider("zh-Hans", "bing") == "zh-Hans"
        assert L.to_provider("en", "any-engine") == "en"


# ---------------------------------------------------------------------------
# 旧繁体标签的兼容（繁体选项已移除，但旧数据/后端仍可能给出这些标签）
# ---------------------------------------------------------------------------
class TestLegacyHantCompat:
    @pytest.mark.parametrize("code", ["zh-Hant", "zh-TW", "zh_HK", "zh-MO", "zh-CHT"])
    def test_detected_as_legacy(self, code):
        assert L.is_legacy_hant(code)

    @pytest.mark.parametrize("code", ["zh-Hans", "zh-CN", "en", "ja", "auto"])
    def test_not_legacy(self, code):
        assert not L.is_legacy_hant(code)

    @pytest.mark.parametrize("code", ["zh-Hant", "zh-TW", "zh-CHT"])
    def test_normalized_to_simplified(self, code):
        assert L.normalize_code(code) == L.ZH_HANS

    def test_normalize_keeps_others(self):
        assert L.normalize_code("auto") == "auto"
        assert L.normalize_code("en") == "en"
        assert L.normalize_code("ja") == "ja"

    def test_label_of_legacy_shows_simplified(self):
        """旧配置里的 zh-Hant 在界面上应显示为简体中文，而不是"未知语言"。"""
        assert L.label("zh-Hant") == "简体中文"
        assert L.label("zh-TW") == "简体中文"

    def test_no_script_conversion_anymore(self):
        assert not L.needs_script_conversion("auto", "zh-Hans")
        assert not L.needs_script_conversion("en", "zh-Hans")

    def test_convert_script_is_gone(self):
        """简繁转换已随繁体选项一并移除，不应再存在这个函数。"""
        assert not hasattr(L, "convert_script")


# ---------------------------------------------------------------------------
# 其它
# ---------------------------------------------------------------------------
def test_has_cjk():
    assert L.has_cjk("中文")
    assert not L.has_cjk("English only")
    assert L.has_cjk("mixed 中文 text")


def test_language_choices():
    choices = L.language_choices()
    assert [c for c, _ in choices] == ["zh-Hans", "en"]
    assert L.language_choices(include_auto=True)[0][0] == "auto"


def test_info_falls_back_for_unknown_code():
    """回归：未知语言代码不能抛异常。

    Bing 会把 ``Transformer``、``claude-3-5-sonnet`` 这类短词检测成 ``fr``、
    把 ``v1.2.3-beta`` 检测成 ``et``。早期实现让 ``info()`` 抛 ValueError，
    异常冒到翻译服务后被当成「后端失败」，用户看到的是「翻译经常失败」。
    现在未知代码按「未知语言」处理，翻译照常进行。
    """
    for code in ("fr", "et", "ja", "und"):
        assert L.info(code).code == "und", code
    assert L.info("auto").label_zh == "自动检测"


def test_info_of_legacy_hant_is_unknown_but_label_maps_it():
    """``info()`` 只认内部代码；旧繁体标签由 ``normalize_code`` / ``label`` 兜住。"""
    assert L.info("zh-Hant").code == "und"
    assert L.label("zh-Hant") == "简体中文"


def test_label_of_unknown_code_does_not_crash():
    assert L.label("fr") == "未知语言"


def test_is_supported():
    assert L.is_supported("en")
    assert L.is_supported("zh-Hans")
    assert not L.is_supported("auto")
    assert not L.is_supported("ja")
    assert not L.is_supported("zh-Hant")
