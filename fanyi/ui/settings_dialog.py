"""设置面板：语言、热键、OCR、翻译后端与界面选项。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import OCR_ENGINES, TRANSLATE_ENGINES, Config
from ..hotkey import format_hotkey, is_valid_hotkey, normalize_hotkey
from ..languages import language_choices


class SettingsDialog(QDialog):
    """配置对话框。确认后通过 :meth:`result_config` 取回新配置。"""

    config_saved = Signal(object)  # Config

    def __init__(self, config: Config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_language_tab(), "语言")
        tabs.addTab(self._build_hotkey_tab(), "热键")
        tabs.addTab(self._build_ocr_tab(), "OCR")
        tabs.addTab(self._build_translate_tab(), "翻译")
        tabs.addTab(self._build_ui_tab(), "界面")
        layout.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # 各标签页
    # ------------------------------------------------------------------
    def _build_language_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.target_combo = QComboBox()
        for code, label in language_choices():
            self.target_combo.addItem(label, code)
        self._select(self.target_combo, self._config.target_lang)
        form.addRow("默认目标语言", self.target_combo)

        self.source_combo = QComboBox()
        for code, label in language_choices(include_auto=True):
            self.source_combo.addItem(label, code)
        self._select(self.source_combo, self._config.source_lang)
        form.addRow("默认源语言", self.source_combo)

        hint = QLabel(
            "源语言选「自动检测」时由翻译引擎判断；\n"
            "目标语言随时可在结果窗口或托盘菜单里切换。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B7280;")
        form.addRow("", hint)

        self.normalize_check = QCheckBox("自动统一简繁字形（目标为中文时生效）")
        self.normalize_check.setChecked(self._config.normalize_script)
        form.addRow("", self.normalize_check)
        return page

    def _build_hotkey_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.hotkey_enabled_check = QCheckBox("启用全局热键")
        self.hotkey_enabled_check.setChecked(self._config.hotkey_enabled)
        form.addRow("", self.hotkey_enabled_check)

        self.capture_hotkey_edit = QKeySequenceEdit(QKeySequence(self._config.hotkey))
        self.capture_hotkey_edit.setMaximumSequenceLength(1)
        capture_row = QHBoxLayout()
        capture_row.addWidget(self.capture_hotkey_edit, 1)
        clear_capture = QPushButton("清除")
        clear_capture.clicked.connect(self.capture_hotkey_edit.clear)
        capture_row.addWidget(clear_capture)
        holder = QWidget()
        holder.setLayout(capture_row)
        form.addRow("截图翻译", holder)

        self.repeat_hotkey_edit = QKeySequenceEdit(QKeySequence(self._config.repeat_hotkey))
        self.repeat_hotkey_edit.setMaximumSequenceLength(1)
        repeat_row = QHBoxLayout()
        repeat_row.addWidget(self.repeat_hotkey_edit, 1)
        clear_repeat = QPushButton("清除")
        clear_repeat.clicked.connect(self.repeat_hotkey_edit.clear)
        repeat_holder = QWidget()
        repeat_holder.setLayout(repeat_row)
        form.addRow("重译上次区域", repeat_holder)

        hint = QLabel(
            "热键需要至少一个修饰键（Ctrl / Alt / Shift / Win）。\n"
            "若注册失败，通常是安全软件拦截，可尝试以管理员身份运行。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B7280;")
        form.addRow("", hint)
        return page

    def _build_ocr_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.ocr_combo = QComboBox()
        for code, label in OCR_ENGINES:
            self.ocr_combo.addItem(label, code)
        self._select(self.ocr_combo, self._config.ocr_engine)
        form.addRow("识别引擎", self.ocr_combo)

        self.ocr_scale_spin = QDoubleSpinBox()
        self.ocr_scale_spin.setRange(1.0, 3.0)
        self.ocr_scale_spin.setSingleStep(0.5)
        self.ocr_scale_spin.setDecimals(1)
        self.ocr_scale_spin.setValue(float(self._config.ocr_scale or 1.0))
        form.addRow("识别前放大倍数", self.ocr_scale_spin)

        self.ocr_confidence_spin = QDoubleSpinBox()
        self.ocr_confidence_spin.setRange(0.0, 0.95)
        self.ocr_confidence_spin.setSingleStep(0.05)
        self.ocr_confidence_spin.setDecimals(2)
        self.ocr_confidence_spin.setValue(float(self._config.ocr_min_confidence))
        form.addRow("最低置信度", self.ocr_confidence_spin)

        hint = QLabel(
            "RapidOCR 为本地离线引擎，模型在首次识别时加载（约 1~3 秒），之后常驻内存。\n"
            "小字识别不准时可把放大倍数调到 1.5 ~ 2.0。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B7280;")
        form.addRow("", hint)
        return page

    def _build_translate_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        group = QGroupBox("后端优先级（自上而下依次尝试，失败自动切换）")
        group_layout = QVBoxLayout(group)
        self.engine_list = QListWidget()
        for code, label in TRANSLATE_ENGINES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if code in (self._config.translate_engines or [])
                else Qt.CheckState.Unchecked
            )
            self.engine_list.addItem(item)
        group_layout.addWidget(self.engine_list)

        buttons = QHBoxLayout()
        up = QPushButton("上移")
        up.clicked.connect(lambda: self._move_engine(-1))
        down = QPushButton("下移")
        down.clicked.connect(lambda: self._move_engine(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        buttons.addStretch(1)
        group_layout.addLayout(buttons)
        layout.addWidget(group)

        form = QFormLayout()
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(2.0, 30.0)
        self.timeout_spin.setSingleStep(1.0)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(float(self._config.request_timeout))
        form.addRow("单次请求超时", self.timeout_spin)

        self.cache_check = QCheckBox("启用翻译缓存（重复内容不再请求网络）")
        self.cache_check.setChecked(self._config.cache_enabled)
        form.addRow("", self.cache_check)
        layout.addLayout(form)

        hint = QLabel("所有后端均为免费公开接口，无需 API Key；被限流时会自动切换到下一个。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6B7280;")
        layout.addWidget(hint)
        return page

    def _build_ui_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.on_top_check = QCheckBox("结果窗口置顶")
        self.on_top_check.setChecked(self._config.result_always_on_top)
        form.addRow("", self.on_top_check)

        self.show_original_check = QCheckBox("显示原文区域")
        self.show_original_check.setChecked(self._config.show_original)
        form.addRow("", self.show_original_check)

        self.auto_copy_check = QCheckBox("翻译完成后自动复制译文")
        self.auto_copy_check.setChecked(self._config.result_auto_copy)
        form.addRow("", self.auto_copy_check)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 28)
        self.font_spin.setValue(int(self._config.result_font_size))
        form.addRow("结果字号", self.font_spin)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(20, 2000)
        self.history_spin.setValue(int(self._config.history_limit))
        form.addRow("历史记录条数上限", self.history_spin)
        return page

    # ------------------------------------------------------------------
    @staticmethod
    def _select(combo: QComboBox, code: str) -> None:
        index = combo.findData(code)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _move_engine(self, delta: int) -> None:
        row = self.engine_list.currentRow()
        if row < 0:
            return
        target = row + delta
        if not (0 <= target < self.engine_list.count()):
            return
        item = self.engine_list.takeItem(row)
        self.engine_list.insertItem(target, item)
        self.engine_list.setCurrentRow(target)

    # ------------------------------------------------------------------
    def _on_accept(self) -> None:
        hotkey = ""
        if self.hotkey_enabled_check.isChecked():
            hotkey = normalize_hotkey(self.capture_hotkey_edit.keySequence().toString())
            if not hotkey or not is_valid_hotkey(hotkey):
                QMessageBox.warning(
                    self, "热键无效", "截图翻译热键需要「至少一个修饰键 + 一个主键」，例如 Ctrl+Alt+Z。"
                )
                return
        repeat = normalize_hotkey(self.repeat_hotkey_edit.keySequence().toString())
        if repeat and not is_valid_hotkey(repeat):
            QMessageBox.warning(self, "热键无效", f"「{repeat}」不是合法的热键组合。")
            return
        if repeat and repeat == hotkey:
            QMessageBox.warning(self, "热键冲突", "两个功能不能使用同一个热键。")
            return

        engines: List[str] = []
        for row in range(self.engine_list.count()):
            item = self.engine_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                engines.append(str(item.data(Qt.ItemDataRole.UserRole)))
        if not engines:
            QMessageBox.warning(self, "缺少后端", "请至少勾选一个翻译后端。")
            return

        config = self._config
        config.target_lang = self.target_combo.currentData()
        config.source_lang = self.source_combo.currentData()
        config.normalize_script = self.normalize_check.isChecked()
        config.hotkey_enabled = self.hotkey_enabled_check.isChecked()
        config.hotkey = hotkey or config.hotkey
        config.repeat_hotkey = repeat
        config.ocr_engine = self.ocr_combo.currentData()
        config.ocr_scale = float(self.ocr_scale_spin.value())
        config.ocr_min_confidence = float(self.ocr_confidence_spin.value())
        config.translate_engines = engines
        config.request_timeout = float(self.timeout_spin.value())
        config.cache_enabled = self.cache_check.isChecked()
        config.result_always_on_top = self.on_top_check.isChecked()
        config.show_original = self.show_original_check.isChecked()
        config.result_auto_copy = self.auto_copy_check.isChecked()
        config.result_font_size = int(self.font_spin.value())
        config.history_limit = int(self.history_spin.value())

        self.config_saved.emit(config)
        self.accept()

    def result_config(self) -> Config:
        return self._config


__all__ = ["SettingsDialog"]
