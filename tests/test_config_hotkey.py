"""配置、热键、框选几何的单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fanyi import config as config_module
from fanyi.config import Config
from fanyi.hotkey import format_hotkey, is_valid_hotkey, normalize_hotkey
from fanyi.overlay import clamp_rect, normalize_rect


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.target_lang == "zh-Hans"
        assert config.source_lang == "auto"
        assert config.hotkey == "ctrl+alt+z"
        assert config.translate_engines == config_module.DEFAULT_ENGINES

    def test_save_and_load_round_trip(self, tmp_path: Path):
        path = tmp_path / "config.json"
        config = Config()
        config.target_lang = "en"
        config.hotkey = "ctrl+shift+t"
        config.ocr_scale = 1.5
        config.translate_engines = ["mymemory", "bing"]
        config.save(path)

        loaded = Config.load(path)
        assert loaded.target_lang == "en"
        assert loaded.hotkey == "ctrl+shift+t"
        assert loaded.ocr_scale == pytest.approx(1.5)
        assert loaded.translate_engines == ["mymemory", "bing"]

    def test_unicode_is_preserved(self, tmp_path: Path):
        path = tmp_path / "config.json"
        Config().save(path)
        raw = path.read_text(encoding="utf-8")
        assert "\\u" not in raw  # ensure_ascii=False
        assert json.loads(raw)["target_lang"] == "zh-Hans"

    def test_unknown_keys_ignored(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"target_lang": "en", "future_option": 123}), encoding="utf-8"
        )
        config = Config.load(path)
        assert config.target_lang == "en"
        assert not hasattr(config, "future_option")

    def test_missing_keys_fall_back_to_defaults(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"target_lang": "en"}), encoding="utf-8")
        config = Config.load(path)
        assert config.target_lang == "en"
        assert config.hotkey == "ctrl+alt+z"

    def test_type_mismatch_falls_back(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text(
            json.dumps({"ocr_scale": "not-a-number", "cache_enabled": "x"}),
            encoding="utf-8",
        )
        config = Config.load(path)
        assert config.ocr_scale == pytest.approx(1.0)
        assert config.cache_enabled is True

    def test_broken_json_is_quarantined(self, tmp_path: Path):
        path = tmp_path / "config.json"
        path.write_text("{ this is not json", encoding="utf-8")
        config = Config.load(path)
        assert config.target_lang == "zh-Hans"
        assert (tmp_path / "config.json.bad").exists()

    def test_missing_file_returns_defaults(self, tmp_path: Path):
        config = Config.load(tmp_path / "nope.json")
        assert config.target_lang == "zh-Hans"

    def test_legacy_engine_order_is_upgraded(self):
        config = Config.from_dict({"translate_engines": ["google", "mymemory", "bing"]})
        assert config.translate_engines == config_module.DEFAULT_ENGINES

    def test_custom_engine_order_is_kept(self):
        custom = ["bing", "google"]
        config = Config.from_dict({"translate_engines": custom})
        assert config.translate_engines == custom

    def test_set_target_reports_change(self):
        config = Config()
        assert config.set_target("en") is True
        assert config.set_target("en") is False
        assert config.target_lang == "en"

    def test_swap_languages(self):
        config = Config()
        config.source_lang = "en"
        config.target_lang = "zh-Hans"
        assert config.swap_languages() is True
        assert (config.source_lang, config.target_lang) == ("zh-Hans", "en")

    def test_swap_refused_when_source_is_auto(self):
        config = Config()
        config.source_lang = "auto"
        assert config.swap_languages() is False


def test_app_home_respects_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FANYI_HOME", str(tmp_path / "custom"))
    home = config_module.app_home()
    assert home == tmp_path / "custom"
    assert home.exists()


# ---------------------------------------------------------------------------
# 热键
# ---------------------------------------------------------------------------
class TestHotkeyNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Ctrl+Alt+Z", "ctrl+alt+z"),
            ("ctrl+alt+z", "ctrl+alt+z"),
            ("CTRL + ALT + Z", "ctrl+alt+z"),
            ("ctrl-alt-z", "ctrl+alt+z"),
            ("ctrl_alt_z", "ctrl+alt+z"),
            ("Control+Shift+A", "ctrl+shift+a"),
            ("win+alt+q", "windows+alt+q"),
            ("ctrl+alt+shift+f2", "ctrl+alt+shift+f2"),
            ("ctrl+alt+space", "ctrl+alt+space"),
            ("", ""),
            ("z", ""),
            ("ctrl", ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_hotkey(raw) == expected

    def test_duplicate_modifiers_collapsed(self):
        assert normalize_hotkey("ctrl+ctrl+alt+z") == "ctrl+alt+z"

    @pytest.mark.parametrize(
        "combo,expected",
        [
            ("ctrl+alt+z", True),
            ("ctrl+shift+f2", True),
            ("ctrl+alt+space", True),
            ("z", False),
            ("ctrl", False),
            ("", False),
            ("ctrl+alt+unknownkey", False),
        ],
    )
    def test_validity(self, combo, expected):
        assert is_valid_hotkey(combo) is expected

    def test_display(self):
        assert format_hotkey("ctrl+alt+z") == "Ctrl + Alt + Z"
        assert format_hotkey("ctrl+shift+f2") == "Ctrl + Shift + F2"
        assert format_hotkey("windows+alt+q") == "Win + Alt + Q"
        assert format_hotkey("") == "未设置"


# ---------------------------------------------------------------------------
# 框选几何
# ---------------------------------------------------------------------------
class TestRects:
    def test_normalize_any_direction(self):
        assert normalize_rect((10, 10), (50, 40)) == (10, 10, 40, 30)
        assert normalize_rect((50, 40), (10, 10)) == (10, 10, 40, 30)
        assert normalize_rect((50, 10), (10, 40)) == (10, 10, 40, 30)

    def test_zero_size_when_same_point(self):
        assert normalize_rect((5, 5), (5, 5)) == (5, 5, 0, 0)

    def test_negative_coordinates(self):
        assert normalize_rect((-100, -50), (-20, -10)) == (-100, -50, 80, 40)

    def test_clamp_to_bounds(self):
        bounds = (0, 0, 100, 100)
        assert clamp_rect((-10, -10, 50, 50), bounds) == (0, 0, 40, 40)
        assert clamp_rect((80, 80, 50, 50), bounds) == (80, 80, 20, 20)

    def test_clamp_fully_outside(self):
        assert clamp_rect((200, 200, 10, 10), (0, 0, 100, 100)) == (200, 200, 0, 0)

    def test_clamp_keeps_inside_rect(self):
        assert clamp_rect((10, 10, 20, 20), (0, 0, 100, 100)) == (10, 10, 20, 20)
