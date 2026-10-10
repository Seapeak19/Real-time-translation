"""「英译中质量」相关修复的回归测试。

守住三个实测得出、容易回退的行为：

1. 未知语言代码不能让翻译失败（Bing 会把短词判成 fr/et）；
2. 源语言为 auto 时应先按书写系统判断，不交给后端猜；
3. "请求成功但原样返回"的结果要被识别出来，并继续尝试其它后端。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fanyi.config import Config
from fanyi.core.base import TranslateResult
from fanyi.core.detect import dominant_language, resolve_source
from fanyi.core.translate import TranslationCache, TranslationService
from tests.test_translate_fallback import _StubTranslator  # 复用可编排的假后端


def _service(behaviors: dict, engines: list, **config_kwargs) -> TranslationService:
    config = Config()
    config.translate_engines = engines
    config.cache_enabled = False
    for key, value in config_kwargs.items():
        setattr(config, key, value)
    service = TranslationService(config)
    service.cache = TranslationCache(Path("testdata") / "unit_cache.json", limit=10)
    stubs = {name: _StubTranslator(name, behavior) for name, behavior in behaviors.items()}
    service.engine = lambda name, _stubs=stubs: _stubs.get(name)  # type: ignore[assignment]
    return service


# ---------------------------------------------------------------------------
# 书写系统判定
# ---------------------------------------------------------------------------
class TestDominantLanguage:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Transformer", "en"),
            ("Sam Altman", "en"),
            ("claude-3-5-sonnet", "en"),
            ("v1.2.3-beta", "en"),
            ("Large language models can hallucinate facts.", "en"),
            ("这是一个翻译工具", "zh-Hans"),
            ("截图翻译工具 v0.3.0", "zh-Hans"),
            ("", None),
            ("   ", None),
            ("12345", None),
            ("!@#$%", None),
            ("https://example.com", "en"),
        ],
    )
    def test_dominant_language(self, text, expected):
        assert dominant_language(text) == expected

    def test_resolve_source_keeps_explicit(self):
        """用户明确指定了源语言就不要自作聪明。"""
        assert resolve_source("Transformer", "zh-Hans") == "zh-Hans"
        assert resolve_source("这是一个工具", "en") == "en"

    def test_resolve_source_fills_auto(self):
        assert resolve_source("Transformer", "auto") == "en"
        assert resolve_source("这是一个工具", "auto") == "zh-Hans"

    def test_resolve_source_leaves_auto_when_undecidable(self):
        """纯数字/符号判不出来时保持 auto，交给后端。"""
        assert resolve_source("12345", "auto") == "auto"


# ---------------------------------------------------------------------------
# 源语言不被后端的错误检测覆盖
# ---------------------------------------------------------------------------
class TestSourceNotOverriddenByBackend:
    def test_explicit_source_wins_over_backend_detection(self):
        """Bing 把 Transformer 判成 fr，但界面显示的应是实际使用的 en。"""

        def echo_english_but_claim_french(_calls):
            return TranslateResult(
                text="变压器", provider="bing", source_lang="fr", target_lang="zh-Hans"
            )

        service = _service({"bing": echo_english_but_claim_french}, ["bing"])
        result = service.translate("Transformer", target="zh-Hans", source="auto", use_cache=False)
        assert result.source_lang == "en", "应以书写系统判定为准，而不是后端的 fr"
        service.close()

    def test_auto_stays_auto_when_text_is_undecidable(self):
        """纯数字/符号判不出语言时，保持 auto 并采信后端，不硬塞一个语言。"""

        def claim_french(_calls):
            return TranslateResult(
                text="一些结果", provider="bing", source_lang="fr", target_lang="zh-Hans"
            )

        service = _service({"bing": claim_french}, ["bing"])
        result = service.translate("12345", target="zh-Hans", source="auto", use_cache=False)
        assert result.text == "一些结果"
        service.close()


# ---------------------------------------------------------------------------
# 未翻译结果的识别与择优
# ---------------------------------------------------------------------------
class TestUntranslatedDetection:
    def test_looks_translated_basic(self):
        service = _service({"bing": "x"}, ["bing"])
        assert service._looks_translated("你好世界", "zh-Hans", "Hello world")
        assert not service._looks_translated("Hello world", "zh-Hans", "Hello world")
        assert service._looks_translated("Hello world", "en", "你好世界")
        assert not service._looks_translated("", "zh-Hans", "Hello")
        service.close()

    def test_symbol_only_output_is_flagged_as_untranslated(self):
        """``v1.2.3`` 这类判为"未翻译"是**有意**的取舍。

        判据只看输出侧（有没有汉字）才能抓住 ``LLM`` 这种必须翻译的短词；
        代价是纯版本号会被多试一个后端。多花一次请求，好过把该翻的短词
        当成翻译成功。
        """
        service = _service({"bing": "x"}, ["bing"])
        assert not service._looks_translated("v1.2.3", "zh-Hans", "v1.2.3")
        # 但如果后端补上了中文括注，就算翻译成功
        assert service._looks_translated("v1.2.3（版本号）", "zh-Hans", "v1.2.3")
        service.close()

    def test_version_number_still_returns_something(self):
        """纯版本号即使所有后端都回显，也要能返回结果而不是报错。"""
        service = _service({"bing": "v1.2.3", "mymemory": "v1.2.3"}, ["bing", "mymemory"])
        result = service.translate("v1.2.3", target="zh-Hans", source="auto", use_cache=False)
        assert result.text == "v1.2.3"
        service.close()

    def test_falls_through_when_first_engine_echoes(self):
        """回归：MyMemory 回显英文时，应继续问能真正翻译的后端。"""
        service = _service(
            {
                "mymemory": "Sam Altman",       # 原样返回
                "bing": "萨姆·奥特曼",           # 真正翻译
            },
            ["mymemory", "bing"],
        )
        result = service.translate("Sam Altman", target="zh-Hans", source="auto", use_cache=False)
        assert result.text == "萨姆·奥特曼"
        assert result.provider == "bing"
        service.close()

    def test_echo_is_used_as_last_resort_when_nothing_translates(self):
        """所有后端都回显时，返回回显结果而不是报错。"""
        service = _service(
            {"mymemory": "Sam Altman", "bing": "Sam Altman"},
            ["mymemory", "bing"],
        )
        result = service.translate("Sam Altman", target="zh-Hans", source="auto", use_cache=False)
        assert result.text == "Sam Altman"
        service.close()

    def test_first_good_translation_wins(self):
        service = _service(
            {"bing": "萨姆·奥特曼", "mymemory": "另一个译法"},
            ["bing", "mymemory"],
        )
        result = service.translate("Sam Altman", target="zh-Hans", source="auto", use_cache=False)
        assert result.text == "萨姆·奥特曼"
        assert service.engine("mymemory").calls == 0  # type: ignore[union-attr]
        service.close()


# ---------------------------------------------------------------------------
# 冷却递增
# ---------------------------------------------------------------------------
class TestCooldownBackoff:
    def test_cooldown_grows_with_repeated_failures(self):
        """连续失败应逐步拉长冷却，避免每次都撞同一堵墙。"""
        from fanyi.core.base import RateLimitedError

        service = _service({"bing": RateLimitedError("限流")}, ["bing"])
        service._mark_failure("bing", RateLimitedError("限流"))
        first = service._in_cooldown("bing")
        service._mark_failure("bing", RateLimitedError("限流"))
        second = service._in_cooldown("bing")
        assert second > first, f"第二次冷却应更长：{first:.1f}s → {second:.1f}s"
        service.close()

    def test_cooldown_capped(self):
        from fanyi.core.base import RateLimitedError
        from fanyi.core.translate import MAX_COOLDOWN

        service = _service({"bing": "x"}, ["bing"])
        for _ in range(10):
            service._mark_failure("bing", RateLimitedError("限流"))
        assert service._in_cooldown("bing") <= MAX_COOLDOWN
        service.close()

    def test_success_clears_strikes(self):
        from fanyi.core.base import RateLimitedError

        service = _service({"bing": "x"}, ["bing"])
        service._mark_failure("bing", RateLimitedError("限流"))
        service._mark_success("bing")
        assert service._in_cooldown("bing") == 0
        assert not service.cooldowns()
        service.close()
