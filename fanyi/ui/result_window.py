"""结果窗口：置顶悬浮，展示原文与译文，并提供常用操作。"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..languages import label as lang_label

#: 译文框里可选的字体族（按可用性依次尝试）
_FONT_CANDIDATES = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "SimSun"]

_STYLE = """
#ResultCard {
    background: #FFFFFF;
    border: 1px solid #D8DEE8;
    border-radius: 10px;
}
#TitleBar {
    background: #F4F6FA;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-bottom: 1px solid #E3E8F0;
}
#TitleText { color: #1F2937; font-weight: 600; }
#StateText { color: #6B7280; }
QLabel#SectionLabel { color: #6B7280; }
QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #E3E8F0;
    border-radius: 6px;
    padding: 6px;
    color: #111827;
    selection-background-color: #BFDBFE;
}
QPlainTextEdit#OriginalText { background: #FAFBFD; color: #4B5563; }
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D8DEE8;
    border-radius: 6px;
    padding: 4px 10px;
    color: #374151;
}
QPushButton:hover { background: #F0F5FF; border-color: #A9C7FF; color: #1D4ED8; }
QPushButton:pressed { background: #E3EDFF; }
QPushButton#PrimaryButton {
    background: #2563EB; border-color: #2563EB; color: #FFFFFF; font-weight: 600;
}
QPushButton#PrimaryButton:hover { background: #1D4ED8; border-color: #1D4ED8; }
QPushButton#CloseButton { border: none; background: transparent; color: #6B7280; padding: 4px 8px; }
QPushButton#CloseButton:hover { background: #FEE2E2; color: #DC2626; }
"""


class ResultWindow(QWidget):
    """翻译结果卡片。

    通过 :meth:`show_loading` / :meth:`show_result` / :meth:`show_error`
    三个方法切换状态，窗口自身不做任何 OCR 或网络调用。
    """

    #: 用户点击"重译"
    retranslate_requested = Signal()
    #: 用户切换目标语言（参数为新的语言代码）
    target_changed = Signal(str)
    #: 用户点击"设置"，请求打开设置窗口
    settings_requested = Signal()
    #: 窗口尺寸变化（便于持久化）
    resized = Signal(QSize)

    def __init__(
        self,
        target_lang: str,
        source_lang: str = "auto",
        font_size: int = 12,
        always_on_top: bool = True,
        show_original: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._target_lang = target_lang
        self._source_lang = source_lang
        self._provider = ""
        self._pinned = always_on_top
        self._original_visible = show_original

        self.setObjectName("ResultCard")
        self.setStyleSheet(_STYLE)
        self.setWindowTitle("翻译结果")
        self.resize(QSize(560, 380))
        self.setMinimumSize(QSize(380, 200))
        self._apply_flags()

        self._build_ui(font_size)
        self._install_shortcuts()
        self.update_language_labels()

    # ------------------------------------------------------------------
    # 构建
    # ------------------------------------------------------------------
    def _apply_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _pick_font(self) -> str:
        families = set(QGuiApplication.font().families() or [])
        available = set()
        try:
            from PySide6.QtGui import QFontDatabase

            available = set(QFontDatabase.families())
        except Exception:
            available = families
        for name in _FONT_CANDIDATES:
            if name in available:
                return name
        return ""

    def _build_ui(self, font_size: int) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_title_bar())

        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 6)
        body.setSpacing(6)

        # --- 原文 ---
        self.original_header = QWidget()
        header_layout = QHBoxLayout(self.original_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        self.original_label = QLabel("原文")
        self.original_label.setObjectName("SectionLabel")
        self.toggle_original_button = QPushButton("收起")
        self.toggle_original_button.setFixedHeight(22)
        self.toggle_original_button.clicked.connect(self.toggle_original)
        header_layout.addWidget(self.original_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.toggle_original_button)
        body.addWidget(self.original_header)

        text_font = QFont()
        if family := self._pick_font():
            text_font.setFamily(family)
        text_font.setPointSize(font_size)

        self.original_text = QPlainTextEdit()
        self.original_text.setObjectName("OriginalText")
        self.original_text.setReadOnly(True)
        self.original_text.setFont(text_font)
        self.original_text.setPlaceholderText("（未识别到文字）")
        self.original_text.setMaximumHeight(120)
        self.original_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        body.addWidget(self.original_text)

        # --- 译文 ---
        translation_header = QHBoxLayout()
        translation_header.setSpacing(6)
        self.translation_label = QLabel("译文")
        self.translation_label.setObjectName("SectionLabel")
        self.copy_button = QPushButton("复制译文")
        self.copy_button.setObjectName("PrimaryButton")
        self.copy_button.setFixedHeight(24)
        self.copy_button.clicked.connect(lambda: self.copy_translation())
        translation_header.addWidget(self.translation_label)
        translation_header.addStretch(1)
        translation_header.addWidget(self.copy_button)
        body.addLayout(translation_header)

        self.translation_text = QPlainTextEdit()
        self.translation_text.setReadOnly(True)
        big_font = QFont(text_font)
        big_font.setPointSize(font_size + 2)
        self.translation_text.setFont(big_font)
        self.translation_text.setPlaceholderText("等待结果…")
        self.translation_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        body.addWidget(self.translation_text, 1)

        outer.addLayout(body, 1)

        # --- 状态栏 ---
        self.status = QLabel("")
        self.status.setObjectName("StateText")
        self.status.setWordWrap(True)
        status_holder = QWidget()
        status_layout = QHBoxLayout(status_holder)
        status_layout.setContentsMargins(12, 0, 12, 10)
        status_layout.addWidget(self.status)
        outer.addWidget(status_holder)

    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(38)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(6)

        self.title_label = QLabel("翻译")
        self.title_label.setObjectName("TitleText")
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.target_button = QPushButton("目标语言")
        self.target_button.setToolTip("切换目标语言并重新翻译")
        self.target_button.clicked.connect(self._cycle_target)
        layout.addWidget(self.target_button)

        self.retranslate_button = QPushButton("重译")
        self.retranslate_button.setToolTip("对当前原文重新翻译")
        self.retranslate_button.clicked.connect(self.retranslate_requested.emit)
        layout.addWidget(self.retranslate_button)

        self.pin_button = QPushButton("置顶")
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self._pinned)
        self.pin_button.setToolTip("切换窗口置顶")
        self.pin_button.clicked.connect(self.set_pinned)
        layout.addWidget(self.pin_button)

        self.settings_button = QPushButton("设置")
        self.settings_button.setToolTip("打开设置：快捷键、语言、OCR 与翻译后端")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_button)

        close_button = QPushButton("✕")
        close_button.setObjectName("CloseButton")
        close_button.setToolTip("关闭 (Esc)")
        close_button.clicked.connect(self.hide)
        layout.addWidget(close_button)

        # 无边框窗口：标题栏拖动
        bar.mousePressEvent = self._title_press  # type: ignore[method-assign]
        bar.mouseMoveEvent = self._title_move  # type: ignore[method-assign]
        bar.mouseReleaseEvent = self._title_release  # type: ignore[method-assign]
        self._drag_offset: Optional[QPoint] = None
        return bar

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Esc"), self, activated=self.hide)
        QShortcut(QKeySequence("Ctrl+C"), self, activated=lambda: self.copy_translation())
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.retranslate_requested.emit)

    # ------------------------------------------------------------------
    # 无边框拖动
    # ------------------------------------------------------------------
    def _title_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_move(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _title_release(self, event) -> None:
        self._drag_offset = None

    # ------------------------------------------------------------------
    # 状态切换
    # ------------------------------------------------------------------
    def show_loading(self, stage: str = "正在识别…") -> None:
        self.status.setText(stage)
        self.translation_text.setPlaceholderText(stage)
        self.copy_button.setEnabled(False)
        self.retranslate_button.setEnabled(False)

    def show_result(
        self,
        original: str,
        translation: str,
        provider: str = "",
        source_lang: str = "auto",
        elapsed: float = 0.0,
        from_cache: bool = False,
    ) -> None:
        self._provider = provider
        self._source_lang = source_lang
        self.original_text.setPlainText(original)
        self.translation_text.setPlainText(translation)
        self.copy_button.setEnabled(bool(translation))
        self.retranslate_button.setEnabled(True)
        self.update_language_labels()

        bits = []
        if provider:
            bits.append(f"引擎：{provider}")
        if from_cache:
            bits.append("缓存命中")
        if elapsed > 0:
            bits.append(f"耗时 {elapsed:.2f}s")
        if original:
            bits.append(f"原文 {len(original)} 字")
        self.status.setText("　·　".join(bits))

    def show_error(self, message: str, original: str = "") -> None:
        if original:
            self.original_text.setPlainText(original)
        self.translation_text.setPlainText("")
        self.translation_text.setPlaceholderText("翻译失败")
        self.status.setText(message)
        self.copy_button.setEnabled(False)
        self.retranslate_button.setEnabled(bool(original))

    # ------------------------------------------------------------------
    # 语言
    # ------------------------------------------------------------------
    def set_languages(self, source_lang: str, target_lang: str) -> None:
        self._source_lang = source_lang
        self._target_lang = target_lang
        self.update_language_labels()

    def update_language_labels(self) -> None:
        self.title_label.setText(
            f"{lang_label(self._source_lang)} → {lang_label(self._target_lang)}"
        )
        self.target_button.setText(f"目标：{lang_label(self._target_lang)}")
        self.original_label.setText(f"原文（{lang_label(self._source_lang)}）")
        self.translation_label.setText(f"译文（{lang_label(self._target_lang)}）")
        self.translation_text.setPlaceholderText("等待结果…")

    def _cycle_target(self) -> None:
        from ..languages import SUPPORTED

        try:
            index = SUPPORTED.index(self._target_lang)
        except ValueError:
            index = -1
        self.target_changed.emit(SUPPORTED[(index + 1) % len(SUPPORTED)])

    # ------------------------------------------------------------------
    # 其它
    # ------------------------------------------------------------------
    def current_texts(self) -> Tuple[str, str]:
        return self.original_text.toPlainText(), self.translation_text.toPlainText()

    def copy_translation(self) -> bool:
        text = self.translation_text.toPlainText()
        if not text:
            return False
        QApplication.clipboard().setText(text)
        self.status.setText("已复制译文到剪贴板")
        return True

    def set_pinned(self, pinned: Optional[bool] = None) -> None:
        if pinned is None:
            pinned = not self._pinned
        if pinned == self._pinned and self.isVisible():
            return
        self._pinned = bool(pinned)
        self.pin_button.setChecked(self._pinned)
        visible = self.isVisible()
        self._apply_flags()
        if visible:  # 改窗口标志会隐藏窗口，需要重新显示
            self.show()

    @property
    def pinned(self) -> bool:
        return self._pinned

    def toggle_original(self) -> None:
        self._original_visible = not self._original_visible
        self.original_text.setVisible(self._original_visible)
        self.toggle_original_button.setText("收起" if self._original_visible else "展开")

    def set_show_original(self, show: bool) -> None:
        if show != self._original_visible:
            self.toggle_original()

    def set_font_size(self, size: int) -> None:
        original_font = self.original_text.font()
        original_font.setPointSize(size)
        self.original_text.setFont(original_font)
        big = QFont(original_font)
        big.setPointSize(size + 2)
        self.translation_text.setFont(big)

    def move_near(self, x: int, y: int, width: int = 0, height: int = 0) -> None:
        """把窗口放到指定位置附近，并保证不超出所在屏幕。"""
        screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()

        pos_x = x
        pos_y = y + height + 8
        if pos_y + self.height() > area.bottom():
            pos_y = max(area.top(), y - self.height() - 8)
        if pos_x + self.width() > area.right():
            pos_x = max(area.left(), area.right() - self.width())
        pos_x = max(area.left(), pos_x)
        pos_y = max(area.top(), pos_y)
        self.move(pos_x, pos_y)

    def move_to_corner(self) -> None:
        """移动到主屏右下角（用于"重译上次区域"这类没有鼠标位置的场景）。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - 16,
            area.bottom() - self.height() - 16,
        )

    def reveal(self) -> None:
        """显示并激活窗口。"""
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.resized.emit(self.size())

    def closeEvent(self, event) -> None:  # noqa: N802
        # 关闭按钮只隐藏，便于下次复用
        event.ignore()
        self.hide()


__all__ = ["ResultWindow"]
