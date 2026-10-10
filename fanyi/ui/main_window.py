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
    QLineEdit,
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
from .i18n import (
    UI_LANGUAGES,
    app_title,
    key_of as _key_of,
    language_display_name,
    tr,
    trn,
)
from .theme import (
    ACCENT,
    ACCENT_DARK,
    ACCENT_SOFT,
    BASE_STYLESHEET,
    BORDER,
    BORDER_SOFT,
    SURFACE_ALT,
    TEXT,
    TEXT_BODY,
    TEXT_MUTED,
    WHITE,
)

#: 主窗口自己的样式，追加在全局主题之后。
#:
#: 统一的明亮白色：侧栏、内容区、状态栏全部白底，
#: 只用 1px 淡边框做分区，不再用灰色块（否则在深色系统上就是"一明一暗"）。
#: 这里**每个带颜色的选择器都显式写了前景色**——只写背景色是之前
#: 白底白字（看着像乱码）的根因。
_STYLE = BASE_STYLESHEET + f"""
#Sidebar {{ background: {WHITE}; border-right: 1px solid {BORDER_SOFT}; }}
#SidebarTitle {{ color: {TEXT_MUTED}; font-weight: 600; padding: 10px 12px 4px 12px; }}
#SidebarList {{ background: {WHITE}; border: none; }}
#SidebarList::item {{ padding: 9px 12px; border-radius: 6px; color: {TEXT_BODY}; }}
#SidebarList::item:hover {{ background: {SURFACE_ALT}; color: {ACCENT_DARK}; }}
#SidebarList::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; font-weight: 600; }}
#Content {{ background: {WHITE}; }}
#PageTitle {{ color: {TEXT}; font-size: 15pt; font-weight: 700; }}
#PageDesc {{ color: {TEXT_MUTED}; }}
#TipBox {{
    color: {TEXT_MUTED}; background: {SURFACE_ALT};
    border: 1px solid {BORDER_SOFT}; border-radius: 6px; padding: 10px;
}}
#StatusBar {{ background: {WHITE}; border-top: 1px solid {BORDER_SOFT}; }}
#StatusText {{ color: {TEXT_MUTED}; }}
#StatusWarn {{ color: #B45309; }}
QGroupBox {{
    background: {WHITE}; border: 1px solid {BORDER_SOFT}; border-radius: 8px;
    margin-top: 12px; padding: 12px 12px 10px 12px;
    color: {TEXT_BODY}; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {TEXT_BODY}; }}
QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {WHITE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 4px 8px; min-height: 20px;
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: #A9C7FF; }}
QPushButton {{
    background: {WHITE}; color: {TEXT_BODY}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 12px;
}}
QPushButton:hover {{ background: #F0F5FF; border-color: #A9C7FF; color: {ACCENT_DARK}; }}
QPushButton#Primary {{ background: {ACCENT}; border-color: {ACCENT}; color: {WHITE}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_DARK}; border-color: {ACCENT_DARK}; }}
QListWidget {{ background: {WHITE}; color: {TEXT}; border: 1px solid {BORDER_SOFT}; border-radius: 6px; }}
"""


#: 侧栏导航项（翻译键，顺序即页面顺序）
_SIDEBAR_KEYS = ("语言", "快捷键", "识别（OCR）", "翻译", "界面")

#: OCR 引擎下拉项（代码, 翻译键）
_OCR_KEYS = (("rapidocr", "RapidOCR（本地离线，中简/中繁/英）"),)

#: 翻译后端列表项（代码, 翻译键），顺序会被用户调整，这里只定义可选集合
_ENGINE_KEYS = (
    ("llm", "大模型翻译（需 API Key，译文质量最好）"),
    ("youdao", "有道翻译（最快，无需 Key）"),
    ("mymemory", "MyMemory（免费额度，较稳定）"),
    ("bing", "Bing 翻译（无需 Key，需先取令牌）"),
    ("google", "Google 免费端点（部分网络不可达）"),
)

#: 大模型服务的常见接口地址，供下拉快速选择。
#: 第一项是**服务商自己的名字**（产品名），有意不参与多语言化：
#: 品牌名在任何界面语言下都应保持原样，翻译反而会让人认不出来。
_LLM_PRESETS = (  # noqa: i18n
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("本地 Ollama", "http://localhost:11434/v1", "qwen2.5"),
)


class MainWindow(QDialog):
    """设置主窗口。只负责收集与展示配置，具体生效由控制器完成。"""

    #: 用户切换了界面语言（参数为语言代码）
    ui_language_changed = Signal(str)
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

        self.setWindowTitle(f"{app_title()} · {tr('设置')}")
        self.setStyleSheet(_STYLE)
        self.resize(960, 660)
        self.setMinimumSize(820, 520)

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
        # 侧栏只给最小宽度，让它按内容自适应：
        # 英文主按钮 "Translate a screenshot now" 比中文长得多，
        # 固定宽度会把它裁成 "late a screenshot now"（左侧被切掉）
        holder.setMinimumWidth(190)
        holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel(f"{app_title()} v{APP_VERSION}")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        self._sidebar = QListWidget()
        self._sidebar.setObjectName("SidebarList")
        for key in _SIDEBAR_KEYS:
            self._sidebar.addItem(tr(key))
        self._sidebar.currentRowChanged.connect(self._on_page_changed)
        layout.addWidget(self._sidebar, 1)

        capture = QPushButton(tr("开始截图翻译"))
        capture.setProperty("_i18n", "开始截图翻译")
        capture.setProperty("_i18n", "开始截图翻译")
        capture.setObjectName("Primary")
        capture.setToolTip(tr("立即进入框选模式（与全局热键等效）"))
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
        # 记下翻译键，切换界面语言时 retranslate() 会据此重写文案
        heading.setProperty("_i18n", _key_of(title))
        layout.addWidget(heading)
        if desc:
            detail = QLabel(desc)
            detail.setObjectName("PageDesc")
            detail.setWordWrap(True)
            detail.setProperty("_i18n", _key_of(desc))
            layout.addWidget(detail)
        for child in children:
            layout.addWidget(child)
        layout.addStretch(1)
        return page

    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)

    # ------------------------------------------------------------------
    # 界面语言
    # ------------------------------------------------------------------
    def retranslate(self) -> None:
        """按当前 :mod:`fanyi.ui.i18n` 语言刷新界面上所有文案。

        实现方式：控件创建时把"翻译键"存在动态属性 ``_i18n`` 上，
        这里统一遍历刷新，而不是重建窗口。

        为什么不用"销毁重建"：重建会丢掉窗口位置、当前页签、正在录制的
        热键状态，还要处理旧窗口的销毁时机，反而更容易出问题。
        遍历刷新把复杂度限制在"控件自己知道怎么写文案"这一件事上。

        数量/语言名这类动态内容由各自的方法负责（``_rebuild_language_items``、
        ``refresh_status``），它们不依赖 ``_i18n`` 属性。
        """
        from PySide6.QtWidgets import (
            QAbstractButton,
            QComboBox,
            QGroupBox,
            QLabel,
            QLineEdit,
            QPlainTextEdit,
        )

        for widget in self.findChildren(QWidget):
            key = widget.property("_i18n")
            if not key:
                continue
            text = tr(key)
            if isinstance(widget, QGroupBox):
                widget.setTitle(text)
            elif isinstance(widget, QAbstractButton):
                widget.setText(text)
            elif isinstance(widget, QLabel):
                widget.setText(text)
            elif isinstance(widget, (QLineEdit, QPlainTextEdit)):
                widget.setPlaceholderText(text)

        self.setWindowTitle(f"{app_title()} · {tr('设置')}")
        self._sidebar.clear()
        for key in _SIDEBAR_KEYS:
            self._sidebar.addItem(tr(key))

        self._rebuild_language_items()
        self._retranslate_combo_items()

        # 录制的提示文字与状态栏是动态生成的，单独刷一遍
        for editor in (self.capture_hotkey, self.repeat_hotkey):
            retranslate = getattr(editor, "retranslate", None)
            if callable(retranslate):
                retranslate()
        self._rebuild_engine_items()
        self.refresh_status()

    def _rebuild_language_items(self) -> None:
        """语言下拉项的文案跟随界面语言。"""
        for combo, include_auto in ((self.source_combo, True), (self.target_combo, False)):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if include_auto:
                combo.addItem(tr("自动检测"), "auto")
            for code in SUPPORTED:
                combo.addItem(f"{lang_label(code)}（{_english_name(code)}）", code)
            combo.blockSignals(False)
            _select_data(combo, current)

        current_ui = self.ui_language_combo.currentData()
        self.ui_language_combo.blockSignals(True)
        self.ui_language_combo.clear()
        for code in UI_LANGUAGES:
            self.ui_language_combo.addItem(language_display_name(code), code)
        self.ui_language_combo.blockSignals(False)
        _select_data(self.ui_language_combo, current_ui)

        # 常用目标语言的快捷按钮
        for button in self.quick_target_buttons:
            code = button.property("_lang_code")
            if code:
                button.setText(lang_label(code))

    def _rebuild_engine_items(self) -> None:
        """翻译后端列表：勾选状态与顺序保留，只换文案。"""
        states = []
        for row in range(self.engine_list.count()):
            item = self.engine_list.item(row)
            states.append((item.data(Qt.ItemDataRole.UserRole), item.checkState()))
        order = [code for code, _ in states]
        check = dict(states)

        self.engine_list.blockSignals(True)
        self.engine_list.clear()
        for code, label_key in _ENGINE_KEYS:
            item = QListWidgetItem(tr(label_key))
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(check.get(code, Qt.CheckState.Unchecked))
            self.engine_list.addItem(item)
        self.engine_list.blockSignals(False)

        # 按原顺序重排
        for target_row, code in enumerate(order):
            for row in range(self.engine_list.count()):
                if self.engine_list.item(row).data(Qt.ItemDataRole.UserRole) == code:
                    if row != target_row:
                        self.engine_list.insertItem(target_row, self.engine_list.takeItem(row))
                    break

    def _retranslate_combo_items(self) -> None:
        """OCR 引擎下拉：文案来自配置常量，这里按界面语言重建。"""
        current = self.ocr_combo.currentData()
        self.ocr_combo.blockSignals(True)
        self.ocr_combo.clear()
        for code, label_key in _OCR_KEYS:
            self.ocr_combo.addItem(tr(label_key), code)
        self.ocr_combo.blockSignals(False)
        _select_data(self.ocr_combo, current)

    # ------------------------------------------------------------------
    # 语言页
    # ------------------------------------------------------------------
    def _build_language_page(self) -> QWidget:
        # --- 界面语言（与翻译语言分开，互不影响）---
        ui_box = QGroupBox(tr("界面语言"))
        ui_box.setProperty("_i18n", "界面语言")
        ui_form = QVBoxLayout(ui_box)
        ui_form.setSpacing(8)

        self.ui_language_combo = QComboBox()
        for code in UI_LANGUAGES:
            self.ui_language_combo.addItem(language_display_name(code), code)
        _select_data(self.ui_language_combo, self.config.ui_language)
        ui_form.addLayout(
            _row(
                tr("界面语言"),
                self.ui_language_combo,
                tr("界面显示语言，切换后立即生效"),
            )
        )
        self.ui_language_combo.currentIndexChanged.connect(self._emit_ui_language)

        box = QGroupBox(tr("翻译语言"))
        box.setProperty("_i18n", "翻译语言")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.source_combo = QComboBox()
        self.source_combo.addItem(tr("自动检测"), "auto")
        for code in SUPPORTED:
            self.source_combo.addItem(f"{lang_label(code)}（{_english_name(code)}）", code)
        _select_data(self.source_combo, self.config.source_lang)
        form.addLayout(_row(tr("源语言"), self.source_combo, tr("「自动检测」由翻译引擎判断原文语言")))

        self.target_combo = QComboBox()
        for code in SUPPORTED:
            self.target_combo.addItem(f"{lang_label(code)}（{_english_name(code)}）", code)
        _select_data(self.target_combo, self.config.target_lang)
        form.addLayout(_row(tr("目标语言"), self.target_combo, tr("译文输出成这个语言")))

        self.swap_button = QPushButton(tr("⇄ 互换源语言与目标语言"))
        self.swap_button.setProperty("_i18n", "⇄ 互换源语言与目标语言")
        self.swap_button.setProperty("_i18n", "⇄ 互换源语言与目标语言")
        self.swap_button.clicked.connect(self._on_swap)
        form.addWidget(self.swap_button)

        quick = QHBoxLayout()
        _label = QLabel(tr("常用目标："))
        _label.setProperty("_i18n", "常用目标：")
        quick.addWidget(_label)
        # 记住这些按钮：切换界面语言时语言名也要跟着换
        self.quick_target_buttons: list = []
        for code in SUPPORTED:
            button = QPushButton(lang_label(code))
            button.setProperty("_lang_code", code)
            button.clicked.connect(lambda _=False, c=code: self._set_target(c))
            quick.addWidget(button)
            self.quick_target_buttons.append(button)
        quick.addStretch(1)
        form.addLayout(quick)

        self.normalize_check = QCheckBox(tr("自动统一简繁字形（目标为中文时把译文校正为简体/繁体）"))
        self.normalize_check.setProperty("_i18n", "自动统一简繁字形（目标为中文时把译文校正为简体/繁体）")
        self.normalize_check.setChecked(self.config.normalize_script)
        form.addWidget(self.normalize_check)

        self.source_combo.currentIndexChanged.connect(self._emit_languages)
        self.target_combo.currentIndexChanged.connect(self._emit_languages)
        self.normalize_check.toggled.connect(self._emit_languages)

        return self._page(
            ui_box,
            box,
            _tip(
                tr(
                    "语言的改动立即生效。已经显示的译文会按新目标语言自动重译一次；\n"
                    "也可以随时在托盘菜单或结果窗口右上角切换目标语言。"
                )
            ),
            title=tr("语言"),
            desc=tr("决定把屏幕上的文字翻译成哪种语言。支持简体中文、繁体中文、英语互译。"),
        )

    def _emit_ui_language(self) -> None:
        self.ui_language_changed.emit(self.ui_language_combo.currentData())

    def _set_target(self, code: str) -> None:
        _select_data(self.target_combo, code)

    def _on_swap(self) -> None:
        source = self.source_combo.currentData()
        target = self.target_combo.currentData()
        if source == "auto":
            QMessageBox.information(
                self,
                tr("无法互换"),
                tr(
                    "源语言是「自动检测」时没有可互换的语言。\n"
                    "请先把源语言指定为具体语言。"
                ),
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
        box = QGroupBox(tr("全局快捷键"))
        box.setProperty("_i18n", "全局快捷键")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.hotkey_enabled_check = QCheckBox(tr("启用全局快捷键"))
        self.hotkey_enabled_check.setProperty("_i18n", "启用全局快捷键")
        self.hotkey_enabled_check.setChecked(self.config.hotkey_enabled)
        form.addWidget(self.hotkey_enabled_check)

        self.capture_hotkey = HotkeyEdit(self.config.hotkey)
        self.capture_hotkey.hotkey_changed.connect(self._on_capture_hotkey)
        self.capture_hotkey.recording_started.connect(self._on_record_started)
        self.capture_hotkey.recording_stopped.connect(self._on_record_stopped)
        form.addLayout(
            _stacked_row(tr("截图翻译"), self.capture_hotkey, tr("唤出框选层，框住哪里就翻译哪里"))
        )

        self.repeat_hotkey = HotkeyEdit(self.config.repeat_hotkey, placeholder=tr("不设置"))
        self.repeat_hotkey.hotkey_changed.connect(self._on_repeat_hotkey)
        self.repeat_hotkey.recording_started.connect(self._on_record_started)
        self.repeat_hotkey.recording_stopped.connect(self._on_record_stopped)
        form.addLayout(
            _stacked_row(
                tr("重译上次区域"),
                self.repeat_hotkey,
                tr("不重新截图，直接把上一次框选的区域再翻译一次"),
            )
        )

        self.hotkey_apply_button = QPushButton(tr("重新注册快捷键"))
        self.hotkey_apply_button.setProperty("_i18n", "重新注册快捷键")
        self.hotkey_apply_button.clicked.connect(self.reapply_hotkeys_requested.emit)
        form.addWidget(self.hotkey_apply_button)

        self.hotkey_enabled_check.toggled.connect(self._on_hotkey_toggled)

        return self._page(
            box,
            _tip(
                tr(
                    "怎么设置：点「录制」→ 直接按下想要的组合键（例如 Ctrl+Alt+Z）。\n"
                    "录制期间会临时停用全局热键，否则按键会被系统钩子先吃掉，界面录不到。\n"
                    "组合必须包含 Ctrl / Alt / Shift / Win 中至少一个修饰键。\n"
                    "按 Esc 取消录制；点「默认」恢复出厂快捷键。\n\n"
                    "若提示注册失败：多半是组合被别的软件占用，换一个即可；\n"
                    "少数机器需要以管理员身份运行才能安装键盘钩子。"
                )
            ),
            title=tr("快捷键"),
            desc=tr("录制你习惯的按键组合。改动会立即重新注册，无需重启程序。"),
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
        box = QGroupBox(tr("识别引擎"))
        box.setProperty("_i18n", "识别引擎")
        form = QVBoxLayout(box)
        form.setSpacing(8)

        self.ocr_combo = QComboBox()
        # 条目文案用常量表的翻译键，_retranslate_combo_items() 依赖同一张表
        for code, label_key in _OCR_KEYS:
            self.ocr_combo.addItem(tr(label_key), code)
        _select_data(self.ocr_combo, self.config.ocr_engine)
        form.addLayout(_row(tr("OCR 引擎"), self.ocr_combo, tr("本地离线，不联网，不上传屏幕内容")))

        self.ocr_scale_spin = QDoubleSpinBox()
        self.ocr_scale_spin.setRange(1.0, 3.0)
        self.ocr_scale_spin.setSingleStep(0.5)
        self.ocr_scale_spin.setDecimals(1)
        self.ocr_scale_spin.setValue(float(self.config.ocr_scale or 1.0))
        form.addLayout(
            _row(tr("识别前放大倍数"), self.ocr_scale_spin, tr("字太小识别不准时调到 1.5 ~ 2.0"))
        )

        self.ocr_confidence_spin = QDoubleSpinBox()
        self.ocr_confidence_spin.setRange(0.0, 0.95)
        self.ocr_confidence_spin.setSingleStep(0.05)
        self.ocr_confidence_spin.setDecimals(2)
        self.ocr_confidence_spin.setValue(float(self.config.ocr_min_confidence))
        form.addLayout(
            _row(tr("最低置信度"), self.ocr_confidence_spin, tr("低于该值的识别结果会被丢弃"))
        )

        self.ocr_scale_spin.valueChanged.connect(self._emit_ocr)
        self.ocr_confidence_spin.valueChanged.connect(self._emit_ocr)
        self.ocr_combo.currentIndexChanged.connect(self._emit_ocr)

        return self._page(
            box,
            _tip(
                tr(
                    "RapidOCR 模型在程序启动后会在后台加载（约 1~3 秒），之后常驻内存，\n"
                    "单次识别通常在 1 秒内完成，全程不联网。"
                )
            ),
            title=tr("识别（OCR）"),
            desc=tr("屏幕文字先由本地引擎识别成文本，再送去翻译。"),
        )

    def _emit_ocr(self) -> None:
        self.ocr_changed.emit()

    # ------------------------------------------------------------------
    # 翻译页
    # ------------------------------------------------------------------
    def _build_translate_page(self) -> QWidget:
        box = QGroupBox(tr("后端优先级（自上而下依次尝试，失败自动切换）"))
        box.setProperty("_i18n", "后端优先级（自上而下依次尝试，失败自动切换）")
        layout = QVBoxLayout(box)

        self.engine_list = QListWidget()
        self.engine_list.setFixedHeight(140)
        # 条目文案用常量表的翻译键，_rebuild_engine_items() 依赖同一张表
        for code, label_key in _ENGINE_KEYS:
            item = QListWidgetItem(tr(label_key))
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
        up = QPushButton(tr("上移"))
        up.setProperty("_i18n", "上移")
        up.clicked.connect(lambda: self._move_engine(-1))
        down = QPushButton(tr("下移"))
        down.setProperty("_i18n", "下移")
        down.clicked.connect(lambda: self._move_engine(1))
        buttons.addWidget(up)
        buttons.addWidget(down)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(2.0, 30.0)
        self.timeout_spin.setSingleStep(1.0)
        self.timeout_spin.setDecimals(1)
        self.timeout_spin.setSuffix(tr(" 秒"))
        self.timeout_spin.setValue(float(self.config.request_timeout))
        self.timeout_spin.valueChanged.connect(self._emit_translate)
        layout.addLayout(_row(tr("单次请求超时"), self.timeout_spin, tr("网络慢时可适当调大")))

        self.cache_check = QCheckBox(tr("启用翻译缓存（相同内容不再请求网络）"))
        self.cache_check.setProperty("_i18n", "启用翻译缓存（相同内容不再请求网络）")
        self.cache_check.setChecked(self.config.cache_enabled)
        self.cache_check.toggled.connect(self._emit_translate)
        layout.addWidget(self.cache_check)

        cache_row = QHBoxLayout()
        clear_cache = QPushButton(tr("清空翻译缓存"))
        clear_cache.setProperty("_i18n", "清空翻译缓存")
        clear_cache.clicked.connect(self.cache_clear_requested.emit)
        cache_row.addWidget(clear_cache)
        cache_row.addStretch(1)
        layout.addLayout(cache_row)

        llm_box = self._build_llm_group()

        return self._page(
            box,
            llm_box,
            _tip(
                tr(
                    "上面四个后端都是免费公开接口，不需要 API Key。\n"
                    "被限流的后端会自动进入冷却并切换到下一个，\n"
                    "因此把响应快的排在上面体验最好。\n"
                    "想测自己网络下哪个最快：运行 scripts\\benchmark_translate.py。\n"
                    "如果觉得译文不够准（尤其是 AI 术语、人名），"
                    "建议在下面配置大模型后端——它最准，但需要 API Key 且按量计费。"
                )
            ),
            title=tr("翻译"),
            desc=tr(
                "译文由在线接口生成。任何一个后端不可用都不会让翻译整个失败。"
                "勾选并拖动可调整优先级。"
            ),
        )

    # ------------------------------------------------------------------
    def _build_llm_group(self) -> QGroupBox:
        """大模型翻译后端的设置区。

        这是唯一需要 API Key 的后端，因此单独成组并给出获取途径，
        避免和上面"全免费"的后端混在一起让人以为要付费才能用。
        """
        box = QGroupBox(tr("大模型翻译（可选，译文质量最好）"))
        box.setProperty("_i18n", "大模型翻译（可选，译文质量最好）")
        layout = QVBoxLayout(box)

        self.llm_preset_combo = QComboBox()
        self.llm_preset_combo.setProperty("_i18n", "服务商")
        for name, base_url, model in _LLM_PRESETS:
            self.llm_preset_combo.addItem(name, (base_url, model))
        self.llm_preset_combo.addItem(tr("自定义"), None)
        self.llm_preset_combo.currentIndexChanged.connect(self._on_llm_preset)
        layout.addLayout(_row(tr("服务商"), self.llm_preset_combo, tr("选择后会自动填好下面的接口地址与模型名")))

        self.llm_key_edit = QLineEdit(self.config.llm_api_key or "")
        self.llm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.llm_key_edit.setPlaceholderText(tr("粘贴你的 API Key，留空则不启用"))
        self.llm_key_edit.textChanged.connect(self._emit_translate)
        layout.addLayout(_row(tr("API Key"), self.llm_key_edit, tr("只保存在本机配置里，不会上传到别处")))

        self.llm_base_edit = QLineEdit(self.config.llm_base_url or "")
        self.llm_base_edit.setPlaceholderText("https://api.deepseek.com/v1")
        self.llm_base_edit.textChanged.connect(self._emit_translate)
        layout.addLayout(
            _row(tr("接口地址"), self.llm_base_edit, tr("OpenAI 兼容地址，本地模型也可填"))
        )

        self.llm_model_edit = QLineEdit(self.config.llm_model or "")
        self.llm_model_edit.setPlaceholderText("deepseek-chat")
        self.llm_model_edit.textChanged.connect(self._emit_translate)
        layout.addLayout(_row(tr("模型名"), self.llm_model_edit, tr("例如 deepseek-chat")))

        self.llm_status = QLabel("")
        self.llm_status.setObjectName("PageDesc")
        self.llm_status.setWordWrap(True)
        layout.addWidget(self.llm_status)

        self._sync_llm_preset()
        self._refresh_llm_status()
        return box

    def _on_llm_preset(self, index: int) -> None:
        preset = self.llm_preset_combo.itemData(index)
        if preset is None:
            return
        base_url, model = preset
        self.llm_base_edit.setText(base_url)
        self.llm_model_edit.setText(model)

    def _sync_llm_preset(self) -> None:
        """按键值把"服务商"下拉对到当前配置；对不上就选"自定义"。"""
        base = (self.config.llm_base_url or "").strip().rstrip("/")
        model = (self.config.llm_model or "").strip()
        for index, (_name, url, preset_model) in enumerate(_LLM_PRESETS):
            if url.rstrip("/") == base and preset_model == model:
                self.llm_preset_combo.blockSignals(True)
                self.llm_preset_combo.setCurrentIndex(index)
                self.llm_preset_combo.blockSignals(False)
                return
        self.llm_preset_combo.blockSignals(True)
        self.llm_preset_combo.setCurrentIndex(self.llm_preset_combo.count() - 1)
        self.llm_preset_combo.blockSignals(False)

    def _checked_engines(self) -> List[str]:
        """按列表当前顺序返回被勾选的后端代码。"""
        engines: List[str] = []
        for row in range(self.engine_list.count()):
            item = self.engine_list.item(row)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                engines.append(str(item.data(Qt.ItemDataRole.UserRole)))
        return engines

    def _refresh_llm_status(self) -> None:
        """提示当前大模型后端是否可用，以及它排在第几位。"""
        has_key = bool((self.llm_key_edit.text() or "").strip())
        checked = "llm" in self._checked_engines()
        if not has_key:
            self.llm_status.setText(tr("未填写 API Key：大模型后端不会参与翻译。"))
        elif not checked:
            self.llm_status.setText(tr("已填写 API Key，但未在上面的列表里勾选「大模型翻译」。"))
        else:
            self.llm_status.setText(tr("已启用：翻译时会按列表顺序尝试它。"))

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
        # 后端勾选/密钥变化都会影响"大模型是否启用"的提示，顺手刷新
        refresh = getattr(self, "_refresh_llm_status", None)
        if refresh is not None and hasattr(self, "llm_status"):
            refresh()
        self.translate_changed.emit()

    # ------------------------------------------------------------------
    # 界面页
    # ------------------------------------------------------------------
    def _build_appearance_page(self) -> QWidget:
        box = QGroupBox(tr("结果窗口"))
        box.setProperty("_i18n", "结果窗口")
        form = QVBoxLayout(box)

        self.on_top_check = QCheckBox(tr("结果窗口置顶显示"))
        self.on_top_check.setProperty("_i18n", "结果窗口置顶显示")
        self.on_top_check.setChecked(self.config.result_always_on_top)
        form.addWidget(self.on_top_check)

        self.show_original_check = QCheckBox(tr("显示原文区域"))
        self.show_original_check.setProperty("_i18n", "显示原文区域")
        self.show_original_check.setChecked(self.config.show_original)
        form.addWidget(self.show_original_check)

        self.auto_copy_check = QCheckBox(tr("翻译完成后自动复制译文到剪贴板"))
        self.auto_copy_check.setProperty("_i18n", "翻译完成后自动复制译文到剪贴板")
        self.auto_copy_check.setChecked(self.config.result_auto_copy)
        form.addWidget(self.auto_copy_check)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 28)
        self.font_spin.setValue(int(self.config.result_font_size))
        self.font_spin.setSuffix(" pt")
        form.addLayout(_row(tr("字号"), self.font_spin, tr("译文字号会比原文大 2pt")))

        for widget in (self.on_top_check, self.show_original_check, self.auto_copy_check):
            widget.toggled.connect(self.appearance_changed.emit)
        self.font_spin.valueChanged.connect(self.appearance_changed.emit)

        data_box = QGroupBox(tr("数据与历史"))
        data_box.setProperty("_i18n", "数据与历史")
        data_layout = QVBoxLayout(data_box)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(20, 2000)
        self.history_spin.setValue(int(self.config.history_limit))
        self.history_spin.setSuffix(tr(" 条"))
        self.history_spin.valueChanged.connect(self.appearance_changed.emit)
        data_layout.addLayout(_row(tr("历史记录上限"), self.history_spin, tr("超出后自动丢弃最旧的记录")))

        row = QHBoxLayout()
        history_button = QPushButton(tr("查看翻译历史"))
        history_button.setProperty("_i18n", "查看翻译历史")
        history_button.clicked.connect(self.history_requested.emit)
        row.addWidget(history_button)
        path_button = QPushButton(tr("打开配置文件目录"))
        path_button.setProperty("_i18n", "打开配置文件目录")
        path_button.clicked.connect(self.open_config_dir_requested.emit)
        row.addWidget(path_button)
        row.addStretch(1)
        data_layout.addLayout(row)

        return self._page(
            box,
            data_box,
            _tip(trn("配置文件位置：{path}", path=config_path())),
            title=tr("界面"),
            desc=tr("调整结果窗口的显示方式与本地数据规模。"),
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

        self.close_button = QPushButton(tr("关闭窗口"))
        self.close_button.setProperty("_i18n", "关闭窗口")
        self.close_button.setProperty("_i18n", "关闭窗口")
        self.close_button.clicked.connect(self.hide)
        layout.addWidget(self.close_button)
        return bar

    def set_hotkey_status(self, registered: List[str], error: str = "") -> None:
        """由控制器回填热键注册结果，让用户立刻知道有没有生效。"""
        self._hotkey_error = error
        self._registered = list(registered)
        self.refresh_status()

    def refresh_status(self) -> None:
        parts = [
            trn("目标语言：{language}", language=lang_label(self.target_combo.currentData()))
        ]
        if self.config.hotkey_enabled:
            if self._hotkey_error:
                parts.append(trn("⚠ 热键未生效：{reason}", reason=self._hotkey_error))
            else:
                capture = self.capture_hotkey.hotkey
                parts.append(
                    trn("截图热键：{hotkey}", hotkey=format_hotkey(capture))
                    if capture
                    else tr("截图热键：未设置")
                )
        else:
            parts.append(tr("全局热键已停用"))
        self.status_label.setText("　·　".join(parts))

    # ------------------------------------------------------------------
    # 收集配置
    # ------------------------------------------------------------------
    def collect(self) -> Config:
        """把界面上的值写回配置对象（不做落盘，落盘由控制器负责）。"""
        config = self.config
        # 界面语言不在 collect 里改：它需要立刻重建界面，
        # 由 ui_language_changed 信号单独处理，避免被 collect 覆盖回去
        config.source_lang = self.source_combo.currentData()
        config.target_lang = self.target_combo.currentData()
        config.normalize_script = self.normalize_check.isChecked()

        config.hotkey_enabled = self.hotkey_enabled_check.isChecked()
        config.hotkey = self.capture_hotkey.hotkey or config.hotkey
        config.repeat_hotkey = self.repeat_hotkey.hotkey

        config.ocr_engine = self.ocr_combo.currentData()
        config.ocr_scale = float(self.ocr_scale_spin.value())
        config.ocr_min_confidence = float(self.ocr_confidence_spin.value())

        engines: List[str] = self._checked_engines()
        if engines:
            config.translate_engines = engines
        config.request_timeout = float(self.timeout_spin.value())
        config.cache_enabled = self.cache_check.isChecked()
        config.llm_api_key = self.llm_key_edit.text().strip()
        config.llm_base_url = self.llm_base_edit.text().strip()
        config.llm_model = self.llm_model_edit.text().strip()

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
        self.llm_key_edit.setText(config.llm_api_key or "")
        self.llm_base_edit.setText(config.llm_base_url or "")
        self.llm_model_edit.setText(config.llm_model or "")
        self._sync_llm_preset()
        self._refresh_llm_status()
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
    """一行设置项：左标签、中控件、右灰色说明。

    这里刻意**不设最小宽度**：给控件和说明文字设最小值会让三者的需求宽度
    之和超过窗口宽度，Qt 只能按比例裁掉一部分，表现为文字被切掉半边
    （快捷键录入框、英文主按钮都踩过这个坑）。改为让布局自己分配空间。
    """
    row = QHBoxLayout()
    row.setSpacing(10)

    name = QLabel(label)
    name.setProperty("_i18n", _key_of(label))
    name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(name)

    row.addWidget(widget, 2)

    if hint:
        note = QLabel(hint)
        note.setObjectName("PageDesc")
        note.setWordWrap(True)
        note.setProperty("_i18n", _key_of(hint))
        row.addWidget(note, 1)
    return row


def _stacked_row(label: str, widget: QWidget, hint: str = "") -> QVBoxLayout:
    """整行布局：标签在上、控件独占下一行、说明再下一行。

    给快捷键录入框这类"内部由多个控件拼成"的部件用。标签放在控件左侧
    会占掉约 110px，加上说明文字，录入框拿到的宽度就不足以容纳
    （显示框 + 录制 + 清除 + 默认）四个控件的最小宽度，Qt 只能裁掉一部分，
    表现为按钮文字被切成 "ecord"/"efault"。这里把标签也挪到上方，
    让录入框独占整行宽度。
    """
    column = QVBoxLayout()
    column.setSpacing(4)

    name = QLabel(label)
    name.setProperty("_i18n", _key_of(label))
    column.addWidget(name)
    column.addWidget(widget)

    if hint:
        note = QLabel(hint)
        note.setObjectName("PageDesc")
        note.setWordWrap(True)
        note.setProperty("_i18n", _key_of(hint))
        column.addWidget(note)
    return column


def _wide_row(label: str, widget: QWidget, hint: str = "") -> QVBoxLayout:
    """一行设置项：上方是占满宽度的控件，下方是说明文字。

    适合录入框、列表这类需要横向空间的控件——说明文字放右侧会把它们挤扁。
    """
    column = QVBoxLayout()
    column.setSpacing(4)

    top = QHBoxLayout()
    top.setSpacing(10)
    name = QLabel(label)
    name.setProperty("_i18n", _key_of(label))
    name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    top.addWidget(name)
    top.addWidget(widget, 1)
    column.addLayout(top)

    if hint:
        note = QLabel(hint)
        note.setObjectName("PageDesc")
        note.setWordWrap(True)
        note.setContentsMargins(114, 0, 0, 0)
        note.setProperty("_i18n", _key_of(hint))
        column.addWidget(note)
    return column


def _tip(text: str) -> QWidget:
    label = QLabel(text)
    label.setObjectName("TipBox")
    label.setWordWrap(True)
    label.setProperty("_i18n", _key_of(text))
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


__all__ = ["MainWindow", "_english_name", "_row", "_select_data"]
