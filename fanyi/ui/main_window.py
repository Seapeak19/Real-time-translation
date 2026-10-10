"""主设置窗口：可视化配置快捷键、语言、OCR 与翻译后端。

这是本工具唯一的"前台界面"——平时它藏在托盘里，点托盘菜单或双击图标即可打开。
所有改动都会**立即生效并落盘**，不需要点"确定"，减少一层心智负担。

布局：左侧导航（设置分组）+ 右侧滚动内容，底部一条状态栏显示热键注册结果与配置文件位置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    APP_TITLE,
    APP_VERSION,
    OCR_ENGINES,
    TRANSLATE_ENGINES,
    Config,
    config_path,
)
from ..hotkey import format_hotkey
from ..languages import LANGUAGES, SUPPORTED, label as lang_label
from .hotkey_edit import HotkeyEdit

_STYLE = """
#Sidebar { background: #F6F8FC; border-right: 1px solid #E3E8F0; }
#SidebarTitle { color: #6B7280; font-weight: 600; padding: 10px 12px 4px 12px; }
#Sidebar QListWidget { background: transparent; border: none; outline: none; }
#Sidebar QListWidget::item { padding: 9px 12px; border-radius: 6px; color: #374151; }
#Sidebar QListWidget::item:selected { background: #E3EDFF; color: #1D4ED8; font-weight: 600; }
#Content { background: #FFFFFF; }
#PageTitle { color: #111827; font-size: 15pt; font-weight: 700; }
#PageDesc { color: #6B7280; }
#StatusBar { background: #F6F8FC; border-top: 1px solid #E3E8F0; }
#StatusText { color: #6B7280; }
QGroupBox {
    border: 1px solid #E3E8F0; border-radius: 8px; margin-top: 12px;
    padding: 12px 12px 10px 12px; color: #374151; font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
QComboBox, QSpinBox, QDoubleSpinBox {
    border: 1px solid #D8DEE8; border-radius: 6px; padding: 4px 8px;
    background: #FFFFFF; min-height: 20px;
}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #A9C7FF; }
QPushButton {
    border: 1px solid #D8DEE8; border-radius: 6px; padding: 5px 12px;
    background: #FFFFFF; color: #374151;
}
QPushButton:hover { background: #F0F5FF; border-color: #A9C7FF; color: #1D4ED8; }
QPushButton#Primary { background: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600; }
QPushButton#Primary:hover { background: #1D4ED8; border-color: #1D4ED8; }
QListWidget { border: 1px solid #E3E8F0; border-radius: 6px; }
"""


class MainWindow(QDialog):
    """设置主窗口。只负责收集与展示配置，具体生效由控制器完成。"""

    #: 语言发生变化（保存后由控制器应用）
    languages_changed = Signal()
    #: 热键发生变化
    hotkeys_changed = Signal()
    #: OCR 相关设置发生变化
    ocr_changed = Signal()
    #: 翻译后端设置发生变化
    translate_changed = Signal()
    #: 结果窗外观设置发生变化
    appearance_changed = Signal()
    #: 用户点击「立即截图翻译」
    capture_requested = Signal()
    #: 用户点击「清空翻译缓存」
    cache_clear_requested = Signal()
    #: 用户点击「打开配置文件所在目录」
    open_config_dir_requested = Signal()
    #: 用户点击「查看翻译历史」
    history_requested = Signal()
    #: 用户点击「立即生效热键」以外的重注册（由控制器实现）
    reapply_hotkeys_requested = Signal()
    #: 快捷键录制开始/结束（参数为是否正在录制）。
    #: 控制器据此临时停用全局热键，否则按键会被钩子截走、界面录不到。
    recording_changed = Signal(bool)

    def __init__(self, config: Config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._hotkey_error = ""

        self.setWindowTitle(f"{APP_TITLE} · 设置")
        self.setStyleSheet(_STYLE)
        self.resize(860, 600)
        self.setMinimumSize(720, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_content(), 1)
        root.addLayout(body, 1)
        root.addWidget(self._build_status_bar())

        self._sidebar.setCurrentRow(0)
        self.refresh_status()

    # ------------------------------------------------------------------
    # 左侧导航
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        holder = QFrame()
        holder.setObjectName("Sidebar")
        holder.setFixedWidth(190)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel(f"{APP_TITLE} v{APP_VERSION}")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("SidebarList")
        for text in ("语言", "快捷键", "识别（OCR）", "翻译", "界面"):
            self._sidebar.addItem(text)
        self._sidebar.currentRowChanged.connect(self._on_page_changed)
        layout.addWidget(self._sidebar, 1)

        capture = QPushButton("开始截图翻译")
        capture.setObjectName("Primary")
        capture.setToolTip("立即进入框选模式（与全局热键等效）")
        capture.clicked.connect(self.capture_requested.emit)
        layout.addWidget(capture)

        return holder

    def _build_content(self) -> QWidget:
        self._stack = QStackedWidget()
        self._stack.setObjectName("Content")
        self._stack.addWidget(self._wrap_page(self._build_language_page()))
        self._stack.addWidget(self._wrap_page(self._build_hotkey_page()))
        self._stack.addWidget(self._wrap_page(self._build_ocr_page()))
        self._stack.addWidget(self._wrap_page(self._build_translate_page()))
        self._stack.addWidget(self._wrap_page(self._build_appearance_page()))
        return self._stack

    def _wrap_page(self, inner: QWidget) -> QWidget:
        """把页面放进滚动区，窗口变小也不会挤压内容。"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _page(*children: QWidget, title: str, desc: str = "") -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        heading = QLabel(title)
        heading.setObjectName("PageTitle")
        layout.addWidget(heading)
        if desc:
            detail = QLabel(desc)
            detail.setObjectName("PageDesc")
            detail.setWordWrap(True)
            layout.addWidget(detail)
        for child in children:
            layout.addWidget(child)
        layout.addStretch(1)
        return page

    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    # ------------------------------------------------------------------
    # 语言页
    # ------------------------------------------------------------------
    def _build_language_page(self) -> QWidget:
        box = QGroupBox("翻译语言")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.source_combo = QComboBox()
        self.source_combo.addItem("自动检测", "auto")
        for code in SUPPORTED:
            self.source_combo.addItem(f"{lang_label(code)}（{_english_name(code)}）", code)
        _select_data(self.source_combo, self.config.source_lang)
        form.addLayout(_row("源语言", self.source_combo, "「自动检测」由翻译引擎判断原文语言"))

        self.target_combo = QComboBox()
        for code in SUPPORTED:
            self.target_combo.addItem(f"{lang_label(code)}（{_english_name(code)}）", code)
        _select_data(self.target_combo, self.config.target_lang)
        form.addLayout(_row("目标语言", self.target_combo, "译文输出成这个语言"))

        self.swap_button = QPushButton("⇄ 互换源语言与目标语言")
        self.swap_button.clicked.connect(self._on_swap)
        form.addWidget(self.swap_button)

        quick = QHBoxLayout()
        quick.addWidget(QLabel("常用目标："))
        for code in SUPPORTED:
            button = QPushButton(lang_label(code))
            button.clicked.connect(lambda _=False, c=code: self._set_target(c))
            quick.addWidget(button)
        quick.addStretch(1)
        form.addLayout(quick)

        self.normalize_check = QCheckBox("自动统一简繁字形（目标为中文时把译文校正为简体/繁体）")
        self.normalize_check.setChecked(self.config.normalize_script)
        form.addWidget(self.normalize_check)

        self.source_combo.currentIndexChanged.connect(self._emit_languages)
        self.target_combo.currentIndexChanged.connect(self._emit_languages)
        self.normalize_check.toggled.connect(self._emit_languages)

        return self._page(
            box,
            _tip(
                "语言的改动立即生效。已经显示的译文会按新目标语言自动重译一次；\n"
                "也可以随时在托盘菜单或结果窗口右上角切换目标语言。"
            ),
            title="语言",
            desc="决定把屏幕上的文字翻译成哪种语言。支持简体中文、繁体中文、英语互译。",
        )

    def _set_target(self, code: str) -> None:
        _select_data(self.target_combo, code)

    def _on_swap(self) -> None:
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()
        if source == "auto":
            QMessageBox.information(
                self,
                "无法互换",
                "源语言是「自动检测」时没有可互换的语言。\n"
                "请先把源语言指定为具体语言。",
            )
            return
        _select_data(self.source_combo, target)
        _select_data(self.target_combo, source)
        self._emit_languages()

    def _emit_languages(self) -> None:
        self.languages_changed.emit()
        self.refresh_status()

    # ------------------------------------------------------------------
    # 快捷键页
    # ------------------------------------------------------------------
    def _build_hotkey_page(self) -> QWidget:
        box = QGroupBox("全局快捷键")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.hotkey_enabled_check = QCheckBox("启用全局快捷键")
        self.hotkey_enabled_check.setChecked(self.config.hotkey_enabled)
        form.addWidget(self.hotkey_enabled_check)

        self.capture_hotkey = HotkeyEdit(self.config.hotkey)
        self.capture_hotkey.hotkey_changed.connect(self._on_capture_hotkey)
        self.capture_hotkey.recording_started.connect(self._on_record_started)
        self.capture_hotkey.recording_stopped.connect(self._on_record_stopped)
        form.addLayout(_row("截图翻译", self.capture_hotkey, "唤出框选层，框住哪里就翻译哪里"))

        self.repeat_hotkey = HotkeyEdit(self.config.repeat_hotkey, placeholder="不设置")
        self.repeat_hotkey.hotkey_changed.connect(self._on_repeat_hotkey)
        self.repeat_hotkey.recording_started.connect(self._on_record_started)
        self.repeat_hotkey.recording_stopped.connect(self._on_record_stopped)
        form.addLayout(_row("重译上次区域", self.repeat_hotkey, "不重新截图，直接重译上一次框选的区域"))

        self.hotkey_apply_button = QPushButton("重新注册快捷键")
        self.hotkey_apply_button.clicked.connect(self.reapply_hotkeys_requested.emit)
        form.addWidget(self.hotkey_apply_button)

        self.hotkey_enabled_check.toggled.connect(self._on_hotkey_toggled)

        return self._page(
            box,
            _tip(
                "怎么设置：点「录制」→ 直接按下想要的组合键（例如 Ctrl+Alt+Z）。\n"
                "录制期间会临时停用全局热键，否则按键会被系统钩子先吃掉，界面录不到。\n"
                "组合必须包含 Ctrl / Alt / Shift / Win 中至少一个修饰键。\n"
                "按 Esc 取消录制；点「默认」恢复出厂快捷键。\n\n"
                "若提示注册失败：多半是组合被别的软件占用，换一个即可；\n"
                "少数机器需要以管理员身份运行才能安装键盘钩子。"
            ),
            title="快捷键",
            desc="录制你习惯的按键组合。改动会立即重新注册，无需重启程序。",
        )

    def _on_record_started(self) -> None:
        # 两个录制框互斥，避免同时挂着键盘抓取
        for widget in (self.capture_hotkey, self.repeat_hotkey):
            if widget.recording and widget is not self.sender():
                widget.stop_recording()
        self.recording_changed.emit(True)

    def _on_record_stopped(self) -> None:
        still_recording = self.capture_hotkey.recording or self.repeat_hotkey.recording
        self.recording_changed.emit(still_recording)
        if not still_recording:
            # 录制结束，把最终组合落盘并重新注册全局热键
            self.hotkeys_changed.emit()

    def _on_capture_hotkey(self, combo: str) -> None:
        if combo == self.repeat_hotkey.hotkey and combo:
            self.repeat_hotkey.set_hotkey("")
        self.hotkeys_changed.emit()

    def _on_repeat_hotkey(self, combo: str) -> None:
        if combo == self.capture_hotkey.hotkey and combo:
            self.capture_hotkey.set_hotkey(combo)
            self.repeat_hotkey.set_hotkey("")
        self.hotkeys_changed.emit()

    def _on_hotkey_toggled(self, checked: bool) -> None:
        self.capture_hotkey.setEnabled(checked)
        self.repeat_hotkey.setEnabled(checked)
        self.hotkeys_changed.emit()

    # ------------------------------------------------------------------
    # OCR 页
    # ------------------------------------------------------------------
    def _build_ocr_page(self) -> QWidget:
        box = QGroupBox("识别引擎")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.ocr_combo = QComboBox()
        for code, label in OCR_ENGINES:
            self.ocr_combo.addItem(label, code)
        _select_data(self.ocr_combo, self.config.ocr_engine)
        form.addLayout(_row("OCR 引擎", self.ocr_combo, "本地离线，不联网，不上传屏幕内容"))

        self.ocr_scale_spin = QDoubleSpinBox()
        self.ocr_scale_spin.setRange(1.0, 3.0)
        self.ocr_scale_spin.setSingleStep(0.5)
        self.ocr_scale_spin.setDecimals(1)
        self.ocr_scale_spin.setValue(float(self.config.ocr_scale or 1.0))
        form.addLayout(
            _row("识别前放大倍数", self.ocr_scale_spin, "字太小识别不准时调到 1.5 ~ 2.0")
        )

        self.ocr_confidence_spin = QDoubleSpinBox()
        self.ocr_confidence_spin.setRange(0.0, 0.95)
        self.ocr_confidence_spin.setSingleStep(0.05)
        self.ocr_confidence_spin.setDecimals(2)
        self.ocr_confidence_spin.setValue(float(self.config.ocr_min_confidence))
        form.addLayout(
            _row("最低置信度", self.ocr_confidence_spin, "低于该值的识别结果会被丢弃")
        )

        self.ocr_scale_spin.valueChanged.connect(self._emit_ocr)
        self.ocr_confidence_spin.valueChanged.connect(self._emit_ocr)
        self.ocr_combo.currentIndexChanged.connect(self._emit_ocr)

        return self._page(
            box,
            _tip(
                "RapidOCR 模型在程序启动后会在后台加载（约 1~3 秒），之后常驻内存，\n"
                "单次识别通常在 1 秒内完成，全程不联网。"
            ),
            title="识别（OCR）",
            desc="屏幕文字先由本地引擎识别成文本，再送去翻译。",
        )

    def _emit_ocr(self) -> None:
        self.ocr_changed.emit()

    # ------------------------------------------------------------------
    # 翻译页
    # ------------------------------------------------------------------
    def _build_translate_page(self) -> QWidget:
        box = QGroupBox("后端优先级（自上而下依次尝试，失败自动切换）")
        layout = QVBoxLayout(box)

        self.engine_list = QListWidget()
        self.engine_list.setFixedHeight(140)
        for code, label in TRANSLATE_ENGINES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if code in (self.config.translate_engines or [])
                else Qt.CheckState.Unchecked
            )
            self.engine_list.addItem(item)
        self.engine_list.itemChanged.connect(self._emit_translate)
        layout.addWidget(self.engine_list)

        buttons = QHBoxLayout()
        up = QPushButton("上移")
        up.clicked.connect(lambda: self._move_engine(-1))
        down = QPushButton("下移")
        down.clicked.connect(lambda: self._move_engine(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(2.0, 30.0)
        self.timeout_spin.setSingleStep(1.0)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSuffix(" 秒")
        self.timeout_spin.setValue(float(self.config.request_timeout))
        self.timeout_spin.valueChanged.connect(self._emit_translate)
        layout.addLayout(_row("单次请求超时", self.timeout_spin, "网络慢时可适当调大"))

        self.cache_check = QCheckBox("启用翻译缓存（相同内容不再请求网络）")
        self.cache_check.setChecked(self.config.cache_enabled)
        self.cache_check.toggled.connect(self._emit_translate)
        layout.addWidget(self.cache_check)

        cache_row = QHBoxLayout()
        clear_cache = QPushButton("清空翻译缓存")
        clear_cache.clicked.connect(self.cache_clear_requested.emit)
        cache_row.addWidget(clear_cache)
        cache_row.addStretch(1)
        layout.addLayout(cache_row)

        return self._page(
            box,
            _tip(
                "所有后端都是免费公开接口，不需要 API Key。\n"
                "被限流的后端会自动进入冷却（默认 45 秒）并切换到下一个，\n"
                "因此把响应快的排在上面体验最好。\n"
                "想测自己网络下哪个最快：运行 scripts\\probe_engines.py。"
            ),
            title="翻译",
            desc="译文由在线免费接口生成。任何一个后端不可用都不会让翻译整个失败。",
        )

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
        self._emit_translate()

    def _emit_translate(self) -> None:
        self.translate_changed.emit()

    # ------------------------------------------------------------------
    # 界面页
    # ------------------------------------------------------------------
    def _build_appearance_page(self) -> QWidget:
        box = QGroupBox("结果窗口")
        form = QVBoxLayout(box)

        self.on_top_check = QCheckBox("结果窗口置顶显示")
        self.on_top_check.setChecked(self.config.result_always_on_top)
        form.addWidget(self.on_top_check)

        self.show_original_check = QCheckBox("显示原文区域")
        self.show_original_check.setChecked(self.config.show_original)
        form.addWidget(self.show_original_check)

        self.auto_copy_check = QCheckBox("翻译完成后自动复制译文到剪贴板")
        self.auto_copy_check.setChecked(self.config.result_auto_copy)
        form.addWidget(self.auto_copy_check)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 28)
        self.font_spin.setValue(int(self.config.result_font_size))
        self.font_spin.setSuffix(" pt")
        form.addLayout(_row("字号", self.font_spin, "译文字号会比原文大 2pt"))

        for widget in (self.on_top_check, self.show_original_check, self.auto_copy_check):
            widget.toggled.connect(self.appearance_changed.emit)
        self.font_spin.valueChanged.connect(self.appearance_changed.emit)

        data_box = QGroupBox("数据与历史")
        data_layout = QVBoxLayout(data_box)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(20, 2000)
        self.history_spin.setValue(int(self.config.history_limit))
        self.history_spin.setSuffix(" 条")
        self.history_spin.valueChanged.connect(self.appearance_changed.emit)
        data_layout.addLayout(_row("历史记录上限", self.history_spin, "超出后自动丢弃最旧的记录"))

        row = QHBoxLayout()
        history_button = QPushButton("查看翻译历史")
        history_button.clicked.connect(self.history_requested.emit)
        row.addWidget(history_button)
        path_button = QPushButton("打开配置文件目录")
        path_button.clicked.connect(self.open_config_dir_requested.emit)
        row.addWidget(path_button)
        row.addStretch(1)
        data_layout.addLayout(row)

        return self._page(
            box,
            data_box,
            _tip(f"配置文件位置：{config_path()}"),
            title="界面",
            desc="调整结果窗口的显示方式与本地数据规模。",
        )

    # ------------------------------------------------------------------
    # 底部状态栏
    # ------------------------------------------------------------------
    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(40)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(10)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusText")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status_label, 1)

        self.close_button = QPushButton("关闭窗口")
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.close_button)
        return bar

    def set_hotkey_status(self, registered: List[str], error: str = "") -> None:
        """由控制器回填热键注册结果，让用户立刻知道有没有生效。"""
        self._hotkey_error = error
        self._registered = list(registered)
        self.refresh_status()

    def refresh_status(self) -> None:
        parts = [f"目标语言：{lang_label(self.target_combo.currentData())}"]
        if self.config.hotkey_enabled:
            if self._hotkey_error:
                parts.append(f"⚠ 热键未生效：{self._hotkey_error}")
            else:
                capture = self.capture_hotkey.hotkey
                parts.append(
                    f"截图热键：{format_hotkey(capture)}" if capture else "截图热键：未设置"
                )
        else:
            parts.append("全局热键已停用")
        self.status_label.setText("　·　".join(parts))

    # ------------------------------------------------------------------
    # 收集配置
    # ------------------------------------------------------------------
    def collect(self) -> Config:
        """把界面上的值写回配置对象（不做落盘，落盘由控制器负责）。"""
        config = self.config
        config.source_lang = self.source_combo.currentData()
        config.target_lang = self.target_combo.currentData()
        config.normalize_script = self.normalize_check.isChecked()

        config.hotkey_enabled = self.hotkey_enabled_check.isChecked()
        config.hotkey = self.capture_hotkey.hotkey or config.hotkey
        config.repeat_hotkey = self.repeat_hotkey.hotkey

        config.ocr_engine = self.ocr_combo.currentData()
        config.ocr_scale = float(self.ocr_scale_spin.value())
        config.ocr_min_confidence = float(self.ocr_confidence_spin.value())

        engines: List[str] = []
        for row in range(self.engine_list.count()):
            item = self.engine_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                engines.append(str(item.data(Qt.ItemDataRole.UserRole)))
        if engines:
            config.translate_engines = engines
        config.request_timeout = float(self.timeout_spin.value())
        config.cache_enabled = self.cache_check.isChecked()

        config.result_always_on_top = self.on_top_check.isChecked()
        config.show_original = self.show_original_check.isChecked()
        config.result_auto_copy = self.auto_copy_check.isChecked()
        config.result_font_size = int(self.font_spin.value())
        config.history_limit = int(self.history_spin.value())
        return config

    def reload_from(self, config: Config) -> None:
        """从配置对象刷新界面（用于外部改了配置之后同步显示）。"""
        self.config = config
        _select_data(self.source_combo, config.source_lang)
        _select_data(self.target_combo, config.target_lang)
        self.normalize_check.setChecked(config.normalize_script)
        self.hotkey_enabled_check.setChecked(config.hotkey_enabled)
        self.capture_hotkey.set_hotkey(config.hotkey)
        self.repeat_hotkey.set_hotkey(config.repeat_hotkey)
        _select_data(self.ocr_combo, config.ocr_engine)
        self.ocr_scale_spin.setValue(float(config.ocr_scale or 1.0))
        self.ocr_confidence_spin.setValue(float(config.ocr_min_confidence))
        self.on_top_check.setChecked(config.result_always_on_top)
        self.show_original_check.setChecked(config.show_original)
        self.auto_copy_check.setChecked(config.result_auto_copy)
        self.font_spin.setValue(int(config.result_font_size))
        self.history_spin.setValue(int(config.history_limit))
        self.refresh_status()

    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        # 关闭只隐藏，保持常驻，下次打开更快
        event.ignore()
        self.hide()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _english_name(code: str) -> str:
    return LANGUAGES[code].label_en


def _select_data(combo: QComboBox, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def _row(label: str, widget: QWidget, hint: str = "") -> QHBoxLayout:
    """一行设置项：左标签、中控件、右灰色说明。"""
    row = QHBoxLayout()
    row.setSpacing(10)

    name = QLabel(label)
    name.setMinimumWidth(96)
    name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(name)

    widget.setMinimumWidth(200)
    row.addWidget(widget, 1)

    if hint:
        note = QLabel(hint)
        note.setObjectName("PageDesc")
        note.setWordWrap(True)
        note.setMinimumWidth(240)
        row.addWidget(note, 1)
    return row


def _tip(text: str) -> QWidget:
    label = QLabel(text)
    label.setObjectName("PageDesc")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet("QLabel { color: #6B7280; background: #F9FAFC;"
                        " border: 1px solid #EEF1F6; border-radius: 6px; padding: 10px; }")
    return label


__all__ = ["MainWindow", "_english_name", "_row", "_select_data"]
