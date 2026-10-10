"""快捷键录入控件的单元测试。

重点验证「Qt 按键 → keyboard 库组合」的转换，以及必须拒绝的非法组合。
这些逻辑出错会让用户录不到键或录进一个吞掉正常输入的热键。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QKeySequence  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fanyi.ui.hotkey_edit import HotkeyEdit, qt_sequence_to_combo  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Qt 序列 → 内部组合
# ---------------------------------------------------------------------------
class TestQtSequenceToCombo:
    @pytest.mark.parametrize(
        "sequence,expected",
        [
            ("Ctrl+Alt+Z", "ctrl+alt+z"),
            ("Ctrl+Shift+F", "ctrl+shift+f"),
            ("Ctrl+Shift+F2", "ctrl+shift+f2"),
            ("Alt+1", "alt+1"),
            ("Ctrl+Alt+Space", "ctrl+alt+space"),
            ("Meta+Alt+Q", "windows+alt+q"),
            ("Ctrl+Alt+Left", "ctrl+alt+left"),
            ("Ctrl+Alt+PgUp", "ctrl+alt+page up"),
            ("Ctrl+Alt+Del", "ctrl+alt+delete"),
        ],
    )
    def test_supported_combinations(self, sequence, expected):
        assert qt_sequence_to_combo(QKeySequence(sequence)) == expected

    def test_bare_key_rejected(self):
        assert qt_sequence_to_combo(QKeySequence("Z")) == ""

    def test_modifier_only_rejected(self):
        assert qt_sequence_to_combo(QKeySequence("Ctrl")) == ""
        assert qt_sequence_to_combo(QKeySequence("Ctrl+Alt")) == ""

    def test_empty_rejected(self):
        assert qt_sequence_to_combo(QKeySequence()) == ""


# ---------------------------------------------------------------------------
# 控件行为
# ---------------------------------------------------------------------------
def _press(widget: HotkeyEdit, key, modifiers) -> None:
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


class TestHotkeyEdit:
    def test_initial_display(self, qt_app):
        edit = HotkeyEdit("ctrl+alt+z")
        assert edit.hotkey == "ctrl+alt+z"
        assert edit.display.text() == "Ctrl + Alt + Z"

    def test_placeholder_when_empty(self, qt_app):
        edit = HotkeyEdit("")
        assert edit.hotkey == ""
        assert edit.display.text() == "未设置"

    def test_records_valid_combination(self, qt_app):
        edit = HotkeyEdit("")
        received = []
        edit.hotkey_changed.connect(received.append)

        edit.record_button.setChecked(True)
        assert edit.recording

        _press(edit, Qt.Key.Key_J, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        assert edit.hotkey == "ctrl+alt+j"
        assert received == ["ctrl+alt+j"]
        assert not edit.recording  # 录到就自动结束

    def test_rejects_key_without_modifier(self, qt_app):
        edit = HotkeyEdit("ctrl+alt+z")
        edit.record_button.setChecked(True)
        _press(edit, Qt.Key.Key_K, Qt.KeyboardModifier.NoModifier)
        assert edit.hotkey == "ctrl+alt+z"  # 未被覆盖
        assert edit.hint.text()  # 给出提示
        assert edit.recording  # 仍在等待合法输入

    def test_modifier_only_keeps_waiting(self, qt_app):
        edit = HotkeyEdit("")
        edit.record_button.setChecked(True)
        _press(edit, Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier)
        assert edit.recording
        assert edit.hotkey == ""
        assert "Ctrl" in edit.display.text()

    def test_escape_cancels_without_change(self, qt_app):
        edit = HotkeyEdit("ctrl+alt+z")
        edit.record_button.setChecked(True)
        _press(edit, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        assert not edit.recording
        assert edit.hotkey == "ctrl+alt+z"

    def test_clear_button_emits_empty(self, qt_app):
        edit = HotkeyEdit("ctrl+alt+z")
        received = []
        edit.hotkey_changed.connect(received.append)
        edit.clear_button.click()
        assert edit.hotkey == ""
        assert received == [""]

    def test_reset_button_restores_default(self, qt_app):
        edit = HotkeyEdit("")
        edit.reset_button.click()
        assert edit.hotkey == "ctrl+alt+z"

    def test_set_hotkey_normalizes(self, qt_app):
        edit = HotkeyEdit("")
        edit.set_hotkey("CTRL + SHIFT + A")
        assert edit.hotkey == "ctrl+shift+a"

    def test_set_hotkey_can_emit(self, qt_app):
        edit = HotkeyEdit("")
        received = []
        edit.hotkey_changed.connect(received.append)
        edit.set_hotkey("ctrl+alt+q", emit=True)
        assert received == ["ctrl+alt+q"]

    def test_recording_signals(self, qt_app):
        edit = HotkeyEdit("")
        events = []
        edit.recording_started.connect(lambda: events.append("start"))
        edit.recording_stopped.connect(lambda: events.append("stop"))

        edit.record_button.setChecked(True)
        assert events == ["start"]
        _press(edit, Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
        assert events == ["start", "stop"]

    def test_invalid_hotkey_never_applied(self, qt_app):
        """没有修饰键的组合绝不能写进配置，否则会吞掉正常按键。"""
        edit = HotkeyEdit("")
        edit.record_button.setChecked(True)
        for key in (Qt.Key.Key_A, Qt.Key.Key_1, Qt.Key.Key_Space):
            _press(edit, key, Qt.KeyboardModifier.NoModifier)
        assert edit.hotkey == ""
