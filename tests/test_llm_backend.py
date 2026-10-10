"""大模型翻译后端的测试。

没有 API Key 也能测：用假的 HttpClient 回放真实结构的响应，
验证提示词构造、响应解析、错误分类与降级行为。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fanyi.config import Config
from fanyi.core.base import EngineError, RateLimitedError, TranslateResult
from fanyi.core.llm import LlmTranslator, build_prompt, clean_output
from fanyi.core.translate import LLM_ENGINE, TranslationCache, TranslationService


class _FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text


class _FakeClient:
    """记录请求并按脚本返回响应。"""

    def __init__(self, responses) -> None:
        self.responses = list(responses) if isinstance(responses, list) else [responses]
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None, **kwargs):  # noqa: A002
        self.calls.append({"url": url, "json": json, "headers": headers or {}, "timeout": timeout})
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, *args, **kwargs):  # pragma: no cover - 大模型后端不用 GET
        raise AssertionError("大模型后端不应发起 GET 请求")

    def close(self) -> None:
        self.closed = True


def _ok(content: str) -> _FakeResponse:
    return _FakeResponse(200, json.dumps({"choices": [{"message": {"content": content}}]}))


def _translator(client, **kwargs) -> LlmTranslator:
    params = {"api_key": "sk-test", "base_url": "https://api.example.com/v1", "model": "test-model"}
    params.update(kwargs)
    return LlmTranslator(client, **params)


# ---------------------------------------------------------------------------
# 提示词与输出清洗
# ---------------------------------------------------------------------------
class TestPrompt:
    def test_prompt_mentions_target_language(self):
        messages = build_prompt("Hello", "auto", "zh-Hans")
        system = messages[0]["content"]
        assert "简体中文" in system
        assert "繁体" in system  # 明确要求不要输出繁体
        assert messages[1]["content"] == "Hello"

    def test_prompt_for_english(self):
        system = build_prompt("你好", "auto", "en")[0]["content"]
        assert "English" in system

    def test_legacy_traditional_target_still_asks_for_simplified(self):
        """繁体已移除：传入旧的 zh-Hant 也应要求输出简体中文，而不是"Unknown"。"""
        system = build_prompt("Hello", "auto", "zh-Hant")[0]["content"]
        assert "简体中文" in system
        assert "Unknown" not in system

    def test_prompt_asks_for_plain_output(self):
        """必须明确"只输出译文"，否则模型会加上开场白。"""
        system = build_prompt("Hello", "auto", "zh-Hans")[0]["content"]
        assert "只输出译文" in system
        assert "专有名词" in system


class TestCleanOutput:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("你好世界", "你好世界"),
            ("  你好世界  ", "你好世界"),
            ("```\n你好世界\n```", "你好世界"),
            ("```text\n你好世界\n```", "你好世界"),
            ("译文：你好世界", "你好世界"),
            ("翻译: 你好世界", "你好世界"),
            ("Translation: Hello", "Hello"),
            ("```\n译文：你好世界\n```", "你好世界"),
            # 模型把换行写成字面量 \n 的情况（实测出现过）
            ("```\\n你好世界\\n```", "你好世界"),
            ("```\\n大型语言模型是基于 Transformer 架构的模型。\\n```",
             "大型语言模型是基于 Transformer 架构的模型。"),
            # 只有开头围栏、结尾缺失
            ("```python\n你好世界", "你好世界"),
            ("```json\\n你好世界", "你好世界"),
        ],
    )
    def test_clean(self, raw, expected):
        assert clean_output(raw) == expected

    def test_empty(self):
        assert clean_output("") == ""
        assert clean_output("   ") == ""


# ---------------------------------------------------------------------------
# 请求与解析
# ---------------------------------------------------------------------------
class TestRequest:
    def test_successful_translation(self):
        client = _FakeClient(_ok("部署提前完成了。"))
        result = _translator(client).translate("The deployment finished early.", "auto", "zh-Hans")
        assert result.text == "部署提前完成了。"
        assert result.provider == "llm"

    def test_sends_bearer_key_and_model(self):
        client = _FakeClient(_ok("你好"))
        _translator(client).translate("Hello", "auto", "zh-Hans")
        call = client.calls[0]
        assert call["headers"]["Authorization"] == "Bearer sk-test"
        assert call["json"]["model"] == "test-model"
        assert call["json"]["stream"] is False
        assert call["url"].endswith("/chat/completions")

    def test_full_endpoint_url_is_respected(self):
        client = _FakeClient(_ok("你好"))
        _translator(client, base_url="https://api.example.com/v1/chat/completions").translate(
            "Hello", "auto", "zh-Hans"
        )
        assert client.calls[0]["url"] == "https://api.example.com/v1/chat/completions"

    def test_low_temperature_by_default(self):
        client = _FakeClient(_ok("你好"))
        _translator(client).translate("Hello", "auto", "zh-Hans")
        assert client.calls[0]["json"]["temperature"] <= 0.3

    def test_same_language_short_circuits(self):
        client = _FakeClient(_ok("不应被调用"))
        result = _translator(client).translate("你好", "zh-Hans", "zh-Hans")
        assert result.text == "你好"
        assert client.calls == []

    def test_empty_text_short_circuits(self):
        client = _FakeClient(_ok("不应被调用"))
        assert _translator(client).translate("   ", "auto", "zh-Hans").text == ""
        assert client.calls == []


class TestAvailability:
    def test_unavailable_without_key(self):
        assert not _translator(_FakeClient(_ok("x")), api_key="").is_available()

    def test_unavailable_without_model(self):
        assert not _translator(_FakeClient(_ok("x")), model="").is_available()

    def test_not_available_raises_clear_error(self):
        translator = _translator(_FakeClient(_ok("x")), api_key="")
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert "API Key" in str(info.value)

    def test_available_with_full_config(self):
        assert _translator(_FakeClient(_ok("x"))).is_available()


class TestErrors:
    def test_401_is_fatal_and_explained(self):
        body = json.dumps({"error": {"message": "Invalid API key"}})
        translator = _translator(_FakeClient(_FakeResponse(401, body)))
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert "401" in str(info.value)
        assert "API Key" in str(info.value)

    def test_403_mentions_balance(self):
        translator = _translator(_FakeClient(_FakeResponse(403, "{}")))
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert "余额" in str(info.value) or "权限" in str(info.value)

    def test_429_is_rate_limited(self):
        translator = _translator(_FakeClient(_FakeResponse(429, "{}")))
        with pytest.raises(RateLimitedError):
            translator.translate("Hello", "auto", "zh-Hans")

    def test_500_retries_once_then_fails(self):
        client = _FakeClient([_FakeResponse(500, "{}"), _FakeResponse(500, "{}")])
        translator = _translator(client)
        with pytest.raises(EngineError):
            translator.translate("Hello", "auto", "zh-Hans")
        assert len(client.calls) == 2, "5xx 应重试一次"

    def test_500_then_success_recovers(self):
        client = _FakeClient([_FakeResponse(500, "{}"), _ok("你好")])
        result = _translator(client).translate("Hello", "auto", "zh-Hans")
        assert result.text == "你好"

    def test_non_json_body_is_reported(self):
        translator = _translator(_FakeClient(_FakeResponse(200, "<html>oops</html>")))
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert "JSON" in str(info.value)

    def test_missing_choices_is_reported(self):
        translator = _translator(_FakeClient(_FakeResponse(200, json.dumps({"choices": []}))))
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert "找不到译文" in str(info.value)

    def test_empty_content_retries_then_fails(self):
        """内容为空要重试一次；仍为空则报错（文案不是重点，行为才是）。"""
        client = _FakeClient(_ok("   "))
        translator = _translator(client)
        with pytest.raises(EngineError) as info:
            translator.translate("Hello", "auto", "zh-Hans")
        assert len(client.calls) == 2, "空响应应重试一次"
        assert "为空" in str(info.value) or "找不到译文" in str(info.value)


# ---------------------------------------------------------------------------
# 与服务层的集成
# ---------------------------------------------------------------------------
class TestServiceIntegration:
    def _service(self, **config_kwargs) -> TranslationService:
        config = Config()
        config.cache_enabled = False
        for key, value in config_kwargs.items():
            setattr(config, key, value)
        service = TranslationService(config)
        service.cache = TranslationCache(Path("testdata") / "unit_cache.json", limit=10)
        return service

    def test_llm_can_be_selected_as_engine(self):
        service = self._service(translate_engines=[LLM_ENGINE], llm_api_key="sk-test")
        assert service.engine_names() == [LLM_ENGINE]
        assert service.engine(LLM_ENGINE) is not None
        service.close()

    def test_llm_appears_first_when_key_configured_and_list_empty(self):
        service = self._service(translate_engines=[], llm_api_key="sk-test")
        assert service.engine_names()[0] == LLM_ENGINE
        service.close()

    def test_llm_not_added_without_key(self):
        service = self._service(translate_engines=[], llm_api_key="")
        assert LLM_ENGINE not in service.engine_names()
        assert service.engine_names()[0] == "youdao"
        service.close()

    def test_unknown_engine_names_are_filtered(self):
        service = self._service(translate_engines=["llm", "bogus"], llm_api_key="sk-test")
        assert service.engine_names() == [LLM_ENGINE]
        service.close()

    def test_engine_label_exists(self):
        from fanyi.core.translate import ENGINE_LABELS

        assert LLM_ENGINE in ENGINE_LABELS
        assert ENGINE_LABELS[LLM_ENGINE]
