"""快捷键录入控件。

比 ``QKeySequenceEdit`` 更适合本场景的地方：

* 录入期间会临时**解绑全局热键**，否则按下的组合会先被系统钩子吃掉，
  界面上根本录不到（这是热键类工具最容易踩的坑）；
* 只接受"至少一个修饰键 + 一个主键"的组合，没有修饰键的按键直接拒绝，
  避免把 ``z`` 这类普通按键注册成全局热键而吞掉正常输入。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..config import DEFAULT_HOTKEY
from ..hotkey import format_hotkey, is_valid_hotkey, normalize_hotkey
from .i18n import tr, trn

#: Qt 键名 → keyboard 库键名（仅列出需要改名的）
#:
#: 注意两件事：
#: 1. ``QKeySequence.toString()`` 对 PageUp/PageDown 输出的是 ``PgUp``/``PgDown``，
#:    而不是 ``PageUp`` —— 漏掉这两个映射会生成 ``ctrl+alt+pageup`` 这种
#:    keyboard 库不认识的组合，注册时静默失败。
#: 2. Ins/Del 同理只输出缩写。
_QT_KEY_NAMES = {
    "PgUp": "page up",
    "PgDown": "page down",
    "PageUp": "page up",
    "PageDown": "page down",
    "Del": "delete",
    "Delete": "delete",
    "Ins": "insert",
    "Insert": "insert",
    "Return": "enter",
    "Enter": "enter",
    "Backspace": "backspace",
    "Esc": "esc",
    "Escape": "escape",
    "Space": "space",
    "Tab": "tab",
    "Home": "home",
    "End": "end",
    "Up": "up",
    "Down": "down",
    "Left": "left",
    "Right": "right",
    "Print": "print screen",
    "PrtSc": "print screen",
    "CapsLock": "caps lock",
}

#: 大小写不敏感的查表版本。
#: 不同 Qt 版本 / 不同 SequenceFormat 下，同一按键可能输出 ``PgUp`` 或 ``PageUp``，
#: 逐个列举容易漏（漏了就会生成 keyboard 库不认识的组合、注册静默失败），
#: 因此统一按小写匹配。
_QT_KEY_NAMES_LOWER = {key.lower(): value for key, value in _QT_KEY_NAMES.items()}


def qt_sequence_to_combo(sequence: QKeySequence) -> str:
    """把 Qt 的按键序列转成本项目使用的 ``ctrl+alt+z`` 形式。"""
    if sequence.isEmpty():
        return ""
    text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    if not text:
        return ""

    parts = [p for p in text.split("+") if p]
    modifiers = []
    keys = []
    for part in parts:
        low = part.lower()
        if low == "ctrl" or low == "control":
            modifiers.append("ctrl")
        elif low == "alt":
            modifiers.append("alt")
        elif low == "shift":
            modifiers.append("shift")
        elif low in ("meta", "win", "super"):
            modifiers.append("windows")
        else:
            keys.append(_QT_KEY_NAMES_LOWER.get(part.lower(), part.lower()))

    if not keys:
        return ""
    return normalize_hotkey("+".join(modifiers + [keys[-1]]))


class HotkeyEdit(QWidget):
    """点击「录制」后按下组合键即可录入，也支持直接手输。"""

    #: 录入到合法组合时发出（值为 ``ctrl+alt+z`` 形式）
    hotkey_changed = Signal(str)
    #: 开始/结束录入，用于临时解绑全局热键
    recording_started = Signal()
    recording_stopped = Signal()

    def __init__(
        self,
        hotkey: str = "",
        placeholder: str = tr("未设置"),
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._hotkey = normalize_hotkey(hotkey)
        self._recording = False
        self._placeholder = placeholder

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.display = QLabel()
        # 宽度是权衡的结果：太窄会把 "Ctrl + Alt + Page Up" 截断成 "Ctrl ·"，
        # 太宽则会把右侧三个按钮挤出可用空间，Qt 只能裁切它们
        # （表现为按钮文字变成 "ecord"/"efault"）。这里取中间值，
        # 并让按钮用较小但足够的最小宽度，整体不超出常见窗口宽度。
        self.display.setMinimumWidth(170)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setStyleSheet(
            "QLabel { border: 1px solid #D8DEE8; border-radius: 6px;"
            " padding: 5px 10px; background: #FFFFFF; color: #111827; }"
        )
        layout.addWidget(self.display, 1)

        # 按钮文案会随界面语言变化，宽度按最长的一种（"Record"/"录制"）留够；
        # 用 setFixedWidth 会让英文按下时被截成 "Reco…"
        self.record_button = QPushButton(tr("录制"))
        self.record_button.setCheckable(True)
        self.record_button.setMinimumWidth(64)
        self.record_button.toggled.connect(self._on_record_toggled)
        layout.addWidget(self.record_button)

        self.clear_button = QPushButton(tr("清除"))
        self.clear_button.setMinimumWidth(64)
        self.clear_button.clicked.connect(lambda: self.set_hotkey("", emit=True))
        layout.addWidget(self.clear_button)

        self.reset_button = QPushButton(tr("默认"))
        self.reset_button.setMinimumWidth(64)
        self.reset_button.setToolTip(
            trn("恢复默认 {hotkey}", hotkey=format_hotkey(DEFAULT_HOTKEY))
        )
        self.reset_button.clicked.connect(
            lambda: self.set_hotkey(DEFAULT_HOTKEY, emit=True)
        )
        layout.addWidget(self.reset_button)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color: #DC2626;")
        layout.addWidget(self.hint)

        self._refresh()

    # ------------------------------------------------------------------
    def retranslate(self) -> None:
        """按当前界面语言刷新按钮与提示文案。"""
        self.record_button.setText(tr("取消") if self._recording else tr("录制"))
        self.clear_button.setText(tr("清除"))
        self.reset_button.setText(tr("默认"))
        self.reset_button.setToolTip(
            trn("恢复默认 {hotkey}", hotkey=format_hotkey(DEFAULT_HOTKEY))
        )
        self.display.setToolTip(tr("点击「录制」后按下组合键即可录入，也支持直接手输。"))
        self._refresh()

    # ------------------------------------------------------------------
    @property
    def hotkey(self) -> str:
        return self._hotkey

    @property
    def recording(self) -> bool:
        return self._recording

    def set_hotkey(self, hotkey: str, emit: bool = False) -> None:
        value = normalize_hotkey(hotkey)
        self._hotkey = value
        self.hint.setText("")
        self._refresh()
        if emit:
            self.hotkey_changed.emit(value)

    def _refresh(self) -> None:
        if self._recording:
            self.display.setText(tr("请按下组合键…"))
            self.display.setStyleSheet(
                "QLabel { border: 2px solid #2563EB; border-radius: 6px;"
                " padding: 4px 10px; background: #EFF6FF; color: #1D4ED8;"
                " font-weight: 600; }"
            )
            return
        self.display.setStyleSheet(
            "QLabel { border: 1px solid #D8DEE8; border-radius: 6px;"
            " padding: 5px 10px; background: #FFFFFF; color: #111827; }"
        )
        self.display.setText(format_hotkey(self._hotkey) if self._hotkey else self._placeholder)

    # ------------------------------------------------------------------
    def _on_record_toggled(self, checked: bool) -> None:
        self._recording = checked
        self.record_button.setText(tr("取消") if checked else tr("录制"))
        self._refresh()
        if checked:
            self.hint.setText("")
            self.setFocus(Qt.FocusReason.OtherFocusReason)
            self.recording_started.emit()
        else:
            self.recording_stopped.emit()

    def stop_recording(self) -> None:
        if self._recording:
            self.record_button.setChecked(False)

    # ------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if not self._recording:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            # 只按了修饰键，继续等主键。用 keyboard 库的写法展示，跟最终热键一致
            pending = []
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                pending.append("Ctrl")
            if modifiers & Qt.KeyboardModifier.AltModifier:
                pending.append("Alt")
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                pending.append("Shift")
            if modifiers & Qt.KeyboardModifier.MetaModifier:
                pending.append("Win")
            if key == Qt.Key.Key_Meta and "Win" not in pending:
                pending.append("Win")
            # 只按修饰键时，某些平台不会把它算进 modifiers()，这里补一个占位，
            # 保证用户能看到"已经按住了什么"，而不是一直显示初始提示
            self.display.setText(" + ".join(pending + ["…"]) if pending else "Ctrl / Alt / Shift / Win + …")
            return

        if key == Qt.Key.Key_Escape:
            self.stop_recording()
            return

        sequence = QKeySequence(event.keyCombination())
        combo = qt_sequence_to_combo(sequence)

        if not combo:
            self.hint.setText(tr("请同时按下 Ctrl / Alt / Shift 之一与一个主键"))
            return

        if not is_valid_hotkey(combo):
            self.hint.setText(tr("需要至少一个修饰键，例如 Ctrl+Alt+Z"))
            return

        self.hint.setText("")
        self._hotkey = combo
        self.stop_recording()
        self._refresh()
        self.hotkey_changed.emit(combo)
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # 录入过程中点别处即取消，避免一直挂着键盘抓取
        if self._recording and not self.rect().contains(event.position().toPoint()):
            self.stop_recording()
        super().mousePressEvent(event)


__all__ = ["HotkeyEdit", "qt_sequence_to_combo"]
