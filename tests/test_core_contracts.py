"""OCR / 翻译公共契约的单元测试（不联网、不加载模型）。"""

from __future__ import annotations

import numpy as np
import pytest

from fanyi.core.base import (
    EngineError,
    NetworkError,
    NoEngineAvailable,
    RateLimitedError,
    TranslateResult,
    TranslationError,
    Translator,
    choose_joiner,
    join_for_request,
    split_text,
)
from fanyi.core.client import HttpClient
from fanyi.core.ocr import (
    OcrResult,
    TextLine,
    _group_lines,
    _sort_lines,
    create_engine,
    normalize_cjk_spacing,
)


# ---------------------------------------------------------------------------
# 长文本切分
# ---------------------------------------------------------------------------
class TestSplitText:
    def test_short_text_single_chunk(self):
        assert split_text("hello", 100) == ["hello"]

    def test_empty_text(self):
        assert split_text("", 100) == []
        assert split_text("   ", 100) == []

    def test_prefers_newline_boundary(self):
        text = "a" * 50 + "\n" + "b" * 50
        chunks = split_text(text, 60)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 50
        assert chunks[1] == "b" * 50

    def test_prefers_sentence_boundary(self):
        # 句号出现在窗口的后 2/3 处时应当优先在句末断开
        text = "第一句话写得比较长一些。" + "第" * 40 + "。"
        chunks = split_text(text, 30)
        assert chunks[0].endswith("。")

    def test_hard_split_when_boundary_too_early(self):
        # 句号离窗口开头太近（在阈值之前）时不做无谓的短切分，改为硬切
        text = "第一句话。" + "第" * 40 + "。"
        chunks = split_text(text, 30)
        assert chunks[0].startswith("第一句话。")
        assert len(chunks[0]) == 30
        assert "".join(chunks) == text

    def test_hard_split_when_no_boundary(self):
        text = "x" * 250
        chunks = split_text(text, 100)
        assert all(len(c) <= 100 for c in chunks)
        assert "".join(chunks) == text

    def test_all_content_preserved(self):
        text = ("测试句子。" * 50)
        chunks = split_text(text, 80)
        assert "".join(chunks) == text


def test_choose_joiner_and_join_for_request():
    assert choose_joiner("zh-Hans", "中文") == ""
    assert choose_joiner("en", "text") == " "
    assert join_for_request(["你好，", "世界"], "zh-Hans") == "你好，世界"
    assert join_for_request(["Hello", "world"], "en") == "Hello world"
    assert join_for_request([], "en") == ""


# ---------------------------------------------------------------------------
# 异常语义
# ---------------------------------------------------------------------------
def test_exception_hierarchy_and_retryable():
    for cls in (NetworkError, RateLimitedError, EngineError):
        assert issubclass(cls, TranslationError)
        assert cls.retryable is True
    assert NoEngineAvailable.retryable is False


def test_no_engine_available_keeps_details():
    exc = NoEngineAvailable("全挂了", {"google": "超时", "bing": "429"})
    assert exc.errors["google"] == "超时"


def test_translator_is_abstract():
    with pytest.raises(TypeError):
        Translator()  # type: ignore[abstract]


def test_translate_result_defaults():
    result = TranslateResult(text="hi", provider="x")
    assert result.source_lang == "auto"
    assert result.from_cache is False
    assert result.attempts == []


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class TestHttpClient:
    def test_retries_on_429_then_succeeds(self):
        session = _FakeSession([_FakeResponse(429), _FakeResponse(200, payload={"ok": 1})])
        client = HttpClient(timeout=1, retries=1, backoff=0, session=session)
        resp = client.get("https://example.invalid")
        assert resp.status_code == 200
        assert session.calls == 2

    def test_raises_rate_limited_after_retries(self):
        session = _FakeSession([_FakeResponse(429), _FakeResponse(429)])
        client = HttpClient(timeout=1, retries=1, backoff=0, session=session)
        with pytest.raises(RateLimitedError):
            client.get("https://example.invalid")

    def test_4xx_without_retry(self):
        session = _FakeSession([_FakeResponse(404)])
        client = HttpClient(timeout=1, retries=2, backoff=0, session=session)
        with pytest.raises(EngineError):
            client.get("https://example.invalid")
        assert session.calls == 1

    def test_network_error_wrapped(self):
        import requests

        session = _FakeSession([requests.exceptions.ConnectionError("boom")] * 2)
        client = HttpClient(timeout=1, retries=1, backoff=0, session=session)
        with pytest.raises(NetworkError):
            client.get("https://example.invalid")

    def test_jsonp_parsing(self):
        payload = HttpClient.jsonp('/**/{"sentences":[{"trans":"你好"}]}')
        assert payload["sentences"][0]["trans"] == "你好"

    def test_jsonp_with_prefix_noise(self):
        payload = HttpClient.jsonp('/*O_o*/{"a":1}')
        assert payload["a"] == 1

    def test_jsonp_invalid(self):
        with pytest.raises(EngineError):
            HttpClient.jsonp("no json here")


# ---------------------------------------------------------------------------
# OCR 结果与排序
# ---------------------------------------------------------------------------
def _line(text, x, y, h=20, w=80):
    return TextLine(
        text=text,
        confidence=0.9,
        box=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
    )


class TestLineSorting:
    def test_sorted_top_to_bottom(self):
        lines = [_line("second", 10, 100), _line("first", 10, 10)]
        result = _sort_lines(lines, 400)
        assert [l.text for l in result] == ["first", "second"]

    def test_same_row_sorted_left_to_right(self):
        lines = [_line("right", 200, 10), _line("left", 10, 12)]
        result = _sort_lines(lines, 400)
        assert [l.text for l in result] == ["left", "right"]

    def test_multi_row_reading_order(self):
        lines = [
            _line("r2c2", 300, 120),
            _line("r1c1", 10, 20),
            _line("r2c1", 10, 118),
            _line("r1c2", 300, 18),
        ]
        result = _sort_lines(lines, 400)
        assert [l.text for l in result] == ["r1c1", "r1c2", "r2c1", "r2c2"]

    def test_single_line_untouched(self):
        lines = [_line("only", 10, 10)]
        assert _sort_lines(lines, 400) == lines

    def test_lines_without_box_do_not_crash(self):
        lines = [TextLine("a", 0.9, None), TextLine("b", 0.9, None)]
        assert len(_sort_lines(lines, 400)) == 2


class TestOcrResult:
    def test_text_joins_separate_rows(self):
        result = OcrResult(lines=[_line("你好", 10, 10), _line("世界", 10, 100)])
        assert result.text == "你好\n世界"

    def test_same_row_cjk_joined_without_space(self):
        # 中文被切成多个框时不能插入空格
        result = OcrResult(lines=[_line("截图", 10, 10, w=60), _line("翻译", 72, 10, w=60)])
        assert result.text == "截图翻译"

    def test_same_row_latin_joined_with_space(self):
        # 行框不含词间空格，需要用空格补回来
        result = OcrResult(
            lines=[
                _line("Screenshot", 10, 10, w=100),
                _line("translator", 115, 10, w=90),
            ]
        )
        assert result.text == "Screenshot translator"

    def test_raw_text_keeps_every_box(self):
        result = OcrResult(
            lines=[_line("Screenshot", 10, 10, w=100), _line("translator", 115, 10, w=90)]
        )
        assert result.raw_text == "Screenshot\ntranslator"

    def test_is_empty(self):
        assert OcrResult().is_empty
        assert OcrResult(lines=[TextLine("  ")]).is_empty
        assert not OcrResult(lines=[TextLine("x")]).is_empty

    def test_mean_confidence(self):
        result = OcrResult(lines=[TextLine("a", 0.8), TextLine("b", 1.0)])
        assert result.mean_confidence == pytest.approx(0.9)
        assert OcrResult().mean_confidence == 0.0

    def test_line_geometry(self):
        line = _line("x", 30, 40)
        assert line.left == 30
        assert line.top == 40


class TestCjkSpacing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("截图翻译OCR识别", "截图翻译 OCR 识别"),
            ("使用Python3开发", "使用 Python3 开发"),
            ("已经正常", "已经正常"),
            ("Hello world", "Hello world"),
            ("", ""),
            ("翻译(OCR)工具", "翻译(OCR)工具"),
            ("这是 v0.1.0 版本", "这是 v0.1.0 版本"),
            ("点击OK，然后继续", "点击 OK，然后继续"),
            ("共3条记录", "共 3 条记录"),
            ("CPU占用率50%", "CPU 占用率 50%"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_cjk_spacing(raw) == expected

    def test_no_double_spaces(self):
        assert "  " not in normalize_cjk_spacing("中文 A 英文 B 数字 1 结束")


class TestOcrTextAssembly:
    def test_mixed_row_gets_spacing(self):
        result = OcrResult(lines=[_line("截图翻译", 10, 10), _line("OCR", 100, 10)])
        assert result.text == "截图翻译 OCR"

    def test_chinese_row_not_split_by_spaces(self):
        result = OcrResult(lines=[_line("截图", 10, 10, w=60), _line("翻译", 72, 10, w=60)])
        assert result.text == "截图翻译"


class TestLineGrouping:
    def test_rows_detected_and_sorted(self):
        lines = [
            _line("b1", 10, 100),
            _line("a2", 60, 10),
            _line("a1", 10, 12),
        ]
        groups = _group_lines(lines)
        assert len(groups) == 2
        assert [l.text for l in groups[0]] == ["a1", "a2"]
        assert [l.text for l in groups[1]] == ["b1"]

    def test_lines_without_box_each_form_own_row(self):
        groups = _group_lines([TextLine("a"), TextLine("b")])
        assert len(groups) == 2

    def test_empty(self):
        assert _group_lines([]) == []


def test_create_engine_unknown_name():
    with pytest.raises(Exception):
        create_engine("nope")


def test_rapidocr_parse_variants():
    from fanyi.core.ocr import RapidOcrEngine

    box = [[0, 0], [10, 0], [10, 10], [0, 10]]
    # (result, elapse) 形式
    lines = RapidOcrEngine._parse(([[box, "hello", 0.98]], [0.1]), 10, 10)
    assert lines[0].text == "hello" and lines[0].confidence == 0.98
    # 直接列表形式
    lines = RapidOcrEngine._parse([[box, "world", 0.5]], 10, 10)
    assert lines[0].text == "world"
    # 没有文字
    assert RapidOcrEngine._parse(None, 10, 10) == []
    assert RapidOcrEngine._parse((None, [0.1]), 10, 10) == []
    # 缺置信度
    lines = RapidOcrEngine._parse([[box, "x"]], 10, 10)
    assert lines[0].confidence == 1.0


def test_rapidocr_parse_normalizes_cjk_spacing():
    """回归：归一化必须在解析阶段完成，否则 lines[].text 与 OcrResult.text 不一致。"""
    from fanyi.core.ocr import RapidOcrEngine

    box = [[0, 0], [10, 0], [10, 10], [0, 10]]
    lines = RapidOcrEngine._parse([[box, "截图翻译工具v0.1.0", 0.99]], 10, 10)
    assert lines[0].text == "截图翻译工具 v0.1.0"

    result = OcrResult(lines=lines)
    assert result.text == "截图翻译工具 v0.1.0"
    assert result.raw_text == result.text


# ---------------------------------------------------------------------------
# numpy 参与的类型约束（保证 recognize 接口拿到的是数组）
# ---------------------------------------------------------------------------
def test_ocr_engine_accepts_numpy_array():
    from fanyi.core.ocr import OcrEngine

    class Dummy(OcrEngine):
        name = "dummy"

        def recognize(self, image):
            assert isinstance(image, np.ndarray)
            return OcrResult(lines=[TextLine("ok")])

    engine = Dummy()
    result = engine.recognize(np.zeros((10, 10, 3), dtype=np.uint8))
    assert result.text == "ok"
    assert engine.is_ready()
