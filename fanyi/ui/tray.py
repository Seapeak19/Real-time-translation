"""系统托盘：语言切换、手动触发、设置与退出入口。"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import APP_TITLE, APP_VERSION, Config
from ..hotkey import format_hotkey
from ..languages import LANGUAGES, label as lang_label


def build_tray_icon() -> QIcon:
    """画一个"译"字托盘图标（避免额外携带图片资源）。"""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 圆角底色
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2563EB"))
        radius = size * 0.22
        painter.drawRoundedRect(0, 0, size, size, radius, radius)

        # 居中"译"字
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(int(size * 0.62))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")
        painter.end()

        icon.addPixmap(pixmap)
    return icon


class TrayIcon(QObject):
    """托盘图标与菜单。只负责发信号，具体行为由控制器实现。"""

    capture_requested = Signal()
    repeat_requested = Signal()
    target_changed = Signal(str)
    source_changed = Signal(str)
    settings_requested = Signal()
    history_requested = Signal()
    cache_clear_requested = Signal()
    quit_requested = Signal()

    def __init__(self, config: Config, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._target_actions: Dict[str, QAction] = {}
        self._source_actions: Dict[str, QAction] = {}

        self.icon = QSystemTrayIcon(build_tray_icon(), self)
        self.icon.setToolTip(f"{APP_TITLE} · 截图翻译")

        self.menu = QMenu()
        self._build_menu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.refresh_tooltip()

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        self.capture_action = QAction("截图翻译", self.menu)
        self.capture_action.triggered.connect(self.capture_requested.emit)
        self.menu.addAction(self.capture_action)

        self.repeat_action = QAction("重译上次区域", self.menu)
        self.repeat_action.triggered.connect(self.repeat_requested.emit)
        self.menu.addAction(self.repeat_action)

        self.menu.addSeparator()

        # --- 目标语言 ---
        self.target_menu = self.menu.addMenu("目标语言")
        group = QActionGroup(self.target_menu)
        group.setExclusive(True)
        for code, info in LANGUAGES.items():
            action = QAction(info.label_zh, self.target_menu)
            action.setCheckable(True)
            action.setChecked(code == self._config.target_lang)
            action.triggered.connect(lambda _=False, c=code: self.target_changed.emit(c))
            group.addAction(action)
            self.target_menu.addAction(action)
            self._target_actions[code] = action

        # --- 源语言 ---
        self.source_menu = self.menu.addMenu("源语言")
        source_group = QActionGroup(self.source_menu)
        source_group.setExclusive(True)
        for code, text in [("auto", "自动检测")] + [
            (c, i.label_zh) for c, i in LANGUAGES.items()
        ]:
            action = QAction(text, self.source_menu)
            action.setCheckable(True)
            action.setChecked(code == self._config.source_lang)
            action.triggered.connect(lambda _=False, c=code: self.source_changed.emit(c))
            source_group.addAction(action)
            self.source_menu.addAction(action)
            self._source_actions[code] = action

        self.menu.addSeparator()

        self.history_action = QAction("翻译历史…", self.menu)
        self.history_action.triggered.connect(self.history_requested.emit)
        self.menu.addAction(self.history_action)

        self.settings_action = QAction("设置…", self.menu)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(self.settings_action)

        self.cache_action = QAction("清空翻译缓存", self.menu)
        self.cache_action.triggered.connect(self.cache_clear_requested.emit)
        self.menu.addAction(self.cache_action)

        self.menu.addSeparator()

        self.quit_action = QAction("退出", self.menu)
        self.quit_action.triggered.connect(self.quit_requested.emit)
        self.menu.addAction(self.quit_action)

    # ------------------------------------------------------------------
    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def notify(self, title: str, message: str, msecs: int = 4000) -> None:
        """弹出气泡提示（热键注册失败、错误等场景）。"""
        try:
            self.icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, msecs)
        except Exception:
            pass

    def refresh_tooltip(self) -> None:
        hotkey = format_hotkey(self._config.hotkey) if self._config.hotkey_enabled else "未启用"
        self.icon.setToolTip(
            f"{APP_TITLE} v{APP_VERSION}\n"
            f"目标语言：{lang_label(self._config.target_lang)}\n"
            f"截图热键：{hotkey}"
        )
        if hasattr(self, "capture_action"):
            self.capture_action.setText(f"截图翻译（{hotkey}）" if hotkey != "未启用" else "截图翻译")

    def set_target(self, code: str) -> None:
        action = self._target_actions.get(code)
        if action is not None:
            action.setChecked(True)
        self._config.target_lang = code
        self.refresh_tooltip()

    def set_source(self, code: str) -> None:
        action = self._source_actions.get(code)
        if action is not None:
            action.setChecked(True)
        self._config.source_lang = code
        self.refresh_tooltip()

    # ------------------------------------------------------------------
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # 左键单击 / 双击都直接开始截图翻译（这是最高频的操作）
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.capture_requested.emit()


__all__ = ["TrayIcon", "build_tray_icon"]
