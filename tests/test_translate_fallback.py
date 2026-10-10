"""翻译回退策略的单元测试。

这里守住的是"实测得出、与直觉相反"的几个结论，避免以后被"优化"回去：

* 串行回退在首选可用时明显快于并发竞速（并发会更快触发免费接口限流）；
* 因此 ``race_engines`` 默认必须是 **False**；
* Bing 域名顺序必须是 ``www`` 在前（``cn`` 返回空内容）；
* Bing 的两种返回形状都要能解析。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fanyi.config import DEFAULT_ENGINES, Config
from fanyi.core.base import RateLimitedError, TranslateResult, TranslationError
from fanyi.core.engines import BingTranslator, _bing_has_translation
from fanyi.core.translate import RATE_LIMIT_COOLDOWN, TranslationCache, TranslationService


# ---------------------------------------------------------------------------
# 默认值（被实测结论约束）
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_race_is_off_by_default(self):
        """并发竞速会更快触发限流，实测反而更慢，默认必须关闭。"""
        assert Config().race_engines is False

    def test_engine_order_puts_fastest_first(self):
        assert Config().translate_engines == DEFAULT_ENGINES
        assert DEFAULT_ENGINES[0] == "youdao"
        # Bing 已修好且质量好（带 usedLLM），应排在较慢的兜底前面
        assert DEFAULT_ENGINES.index("bing") < DEFAULT_ENGINES.index("mymemory")
        # Google 在本机网络持续 429，放最后
        assert DEFAULT_ENGINES[-1] == "google"

    def test_legacy_order_migrates(self):
        """老配置里的旧顺序应自动升级，否则用户感受不到改进。"""
        for legacy in (
            ["youdao", "mymemory", "bing", "google"],
            ["google", "mymemory", "bing"],
            ["google", "bing", "mymemory"],
        ):
            assert Config.from_dict({"translate_engines": legacy}).translate_engines == DEFAULT_ENGINES

    def test_custom_order_is_respected(self):
        custom = ["bing", "youdao"]
        assert Config.from_dict({"translate_engines": custom}).translate_engines == custom


# ---------------------------------------------------------------------------
# Bing 返回形状
# ---------------------------------------------------------------------------
class TestBingShapes:
    def test_www_shape_top_level_list(self):
        """www.bing.com 返回顶层数组，元素直接带 translations。"""
        payload = [
            {
                "translations": [{"text": "部署比计划提前完成。", "to": "zh-Hans"}],
                "detectedLanguage": {"language": "en"},
            }
        ]
        assert _bing_has_translation(payload)
        piece, lang = BingTranslator._parse_translation(payload)
        assert piece == "部署比计划提前完成。"
        assert lang == "en"

    def test_cn_shape_data_wrapper(self):
        """cn.bing.com 返回 {"data": {...}}。"""
        payload = {
            "data": {
                "translations": [{"text": "启用全局快捷键", "to": "zh-Hans"}],
                "detectedLanguage": {"language": "en"},
            }
        }
        assert _bing_has_translation(payload)
        piece, lang = BingTranslator._parse_translation(payload)
        assert piece == "启用全局快捷键"

    def test_data_as_list(self):
        payload = {"data": [{"translations": [{"text": "你好"}]}]}
        assert _bing_has_translation(payload)
        assert BingTranslator._parse_translation(payload)[0] == "你好"

    def test_empty_payload_rejected(self):
        assert not _bing_has_translation({})
        assert not _bing_has_translation([])
        assert not _bing_has_translation({"statusCode": 400})
        with pytest.raises(TranslationError):
            BingTranslator._parse_translation({"statusCode": 400})

    def test_empty_translation_rejected(self):
        with pytest.raises(TranslationError):
            BingTranslator._parse_translation({"translations": []})

    def test_www_endpoint_tried_first(self):
        """域名顺序：www 在前，因为 cn 会返回空内容。"""
        from fanyi.core.client import HttpClient

        translator = BingTranslator(HttpClient(timeout=1))
        assert "www.bing.com" in translator.page_url
        assert "www.bing.com" in translator.api_url


# ---------------------------------------------------------------------------
# 回退行为
# ---------------------------------------------------------------------------
class _StubTranslator:
    """可编排的假后端：按脚本返回结果或抛异常。"""

    def __init__(self, name: str, behavior) -> None:
        self.name = name
        self.display_name = name
        self._behavior = behavior
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def translate(self, text: str, source: str, target: str) -> TranslateResult:
        self.calls += 1
        outcome = self._behavior
        if callable(outcome):
            outcome = outcome(self.calls)
        if isinstance(outcome, Exception):
            raise outcome
        # 允许行为直接给一个 TranslateResult，便于测"后端报了奇怪的语言代码"这类情况
        if isinstance(outcome, TranslateResult):
            return outcome
        return TranslateResult(text=outcome, provider=self.name, source_lang="en", target_lang=target)


def _service(behaviors: dict, engines: list, **config_kwargs) -> TranslationService:
    """构造一个用假后端替换真实后端的服务。

    ``engines`` 必须用**已注册的后端名**（youdao / mymemory / bing / google）：
    ``engine_names()`` 会过滤掉未注册的名字，用 "a"/"b" 这类占位名
    会让候选列表变空，测出来的不是回退逻辑本身。
    """
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


class TestFallback:
    def test_first_success_wins_without_calling_others(self):
        service = _service({"youdao": "译文A", "mymemory": "译文B"}, ["youdao", "mymemory"])
        result = service.translate("hello", target="zh-Hans", use_cache=False)
        assert result.text == "译文A"
        assert result.provider == "youdao"
        assert service.engine("mymemory").calls == 0  # type: ignore[union-attr]
        service.close()

    def test_falls_through_on_rate_limit(self):
        service = _service(
            {"youdao": RateLimitedError("限流"), "mymemory": "译文B"},
            ["youdao", "mymemory"],
        )
        result = service.translate("hello", target="zh-Hans", use_cache=False)
        assert result.text == "译文B"
        assert result.provider == "mymemory"
        service.close()

    def test_rate_limited_engine_enters_cooldown(self):
        service = _service(
            {"youdao": RateLimitedError("限流"), "mymemory": "译文B"},
            ["youdao", "mymemory"],
        )
        service.translate("first", target="zh-Hans", use_cache=False)
        cooldowns = service.cooldowns()
        assert "youdao" in cooldowns
        assert 0 < cooldowns["youdao"] <= RATE_LIMIT_COOLDOWN
        service.close()

    def test_cooldown_engine_skipped_next_time(self):
        """被限流的后端在冷却期内应被跳过，不再白白浪费一次请求。"""
        service = _service(
            {"youdao": RateLimitedError("限流"), "mymemory": "译文B"},
            ["youdao", "mymemory"],
        )
        service.translate("first", target="zh-Hans", use_cache=False)
        calls_after_first = service.engine("youdao").calls  # type: ignore[union-attr]
        service.translate("second", target="zh-Hans", use_cache=False)
        assert service.engine("youdao").calls == calls_after_first  # type: ignore[union-attr]
        service.close()

    def test_all_failed_raises_with_details(self):
        from fanyi.core.base import NoEngineAvailable

        service = _service(
            {"youdao": RateLimitedError("限流A"), "mymemory": TranslationError("坏了B")},
            ["youdao", "mymemory"],
        )
        with pytest.raises(NoEngineAvailable) as info:
            service.translate("hello", target="zh-Hans", use_cache=False)
        assert "youdao" in info.value.errors and "mymemory" in info.value.errors
        service.close()

    def test_race_mode_still_returns_a_translation(self):
        """竞速模式虽默认关闭，但开启后必须能正常工作。"""
        service = _service(
            {"youdao": RateLimitedError("限流"), "mymemory": "译文B"},
            ["youdao", "mymemory"],
            race_engines=True,
            race_size=2,
            race_stagger=0.05,
        )
        result = service.translate("hello", target="zh-Hans", use_cache=False)
        assert result.text == "译文B"
        service.close()

    def test_race_returns_fastest(self):
        def slow(_calls):
            time.sleep(0.6)
            return "慢"

        def fast(_calls):
            time.sleep(0.05)
            return "快"

        service = _service(
            {"youdao": slow, "mymemory": fast},
            ["youdao", "mymemory"],
            race_engines=True,
            race_size=2,
        )
        started = time.perf_counter()
        result = service.translate("hello", target="zh-Hans", use_cache=False)
        elapsed = time.perf_counter() - started
        assert result.text == "快"
        # 应该几乎等于快后端的耗时，而不是慢后端
        assert elapsed < 0.45, f"竞速没有走快的那条：{elapsed:.2f}s"
        service.close()
