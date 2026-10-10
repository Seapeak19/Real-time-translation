"""系统托盘：语言切换、手动触发、设置与退出入口。"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..config import APP_TITLE, APP_VERSION, Config
from ..hotkey import format_hotkey
from ..languages import LANGUAGES, label as lang_label
from .i18n import app_title, tr, trn


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
        # 图标上的"译"字是标识，不是界面文案 —— 无论界面语言是什么都保持原样，
        # 因此这里用 noqa 明确豁免多语言检查（见 tests/test_i18n.py）
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "译")  # noqa: i18n
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
        self.icon.setToolTip(f"{app_title()} · {tr('截图翻译')}")

        self.menu = QMenu()
        self._build_menu()
        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self.refresh_tooltip()

    # ------------------------------------------------------------------
    def retranslate(self) -> None:
        """重建菜单文案，跟随当前界面语言。

        菜单整体重建而不是逐个 setText：语言下拉里既有语言名又有菜单标题，
        逐个改容易漏；重建能保证与首次构造走同一段代码，不会出现两种写法。
        重建不会丢状态——勾选项由 ``self._config`` 回填。
        """
        self.menu.clear()
        self._target_actions.clear()
        self._source_actions.clear()
        self._build_menu()
        self.refresh_tooltip()

    # ------------------------------------------------------------------
    def _build_menu(self) -> None:
        self.capture_action = QAction(tr("截图翻译"), self.menu)
        self.capture_action.triggered.connect(self.capture_requested.emit)
        self.menu.addAction(self.capture_action)

        self.repeat_action = QAction(tr("重译上次区域"), self.menu)
        self.repeat_action.triggered.connect(self.repeat_requested.emit)
        self.menu.addAction(self.repeat_action)

        self.menu.addSeparator()

        # --- 目标语言 ---
        self.target_menu = self.menu.addMenu(tr("目标语言"))
        group = QActionGroup(self.target_menu)
        group.setExclusive(True)
        for code in LANGUAGES:
            action = QAction(lang_label(code), self.target_menu)
            action.setCheckable(True)
            action.setChecked(code == self._config.target_lang)
            action.triggered.connect(lambda _=False, c=code: self.target_changed.emit(c))
            group.addAction(action)
            self.target_menu.addAction(action)
            self._target_actions[code] = action

        # --- 源语言 ---
        self.source_menu = self.menu.addMenu(tr("源语言"))
        source_group = QActionGroup(self.source_menu)
        source_group.setExclusive(True)
        for code, text in [("auto", tr("自动检测"))] + [
            (c, lang_label(c)) for c in LANGUAGES
        ]:
            action = QAction(text, self.source_menu)
            action.setCheckable(True)
            action.setChecked(code == self._config.source_lang)
            action.triggered.connect(lambda _=False, c=code: self.source_changed.emit(c))
            source_group.addAction(action)
            self.source_menu.addAction(action)
            self._source_actions[code] = action

        self.menu.addSeparator()

        self.history_action = QAction(tr("翻译历史…"), self.menu)
        self.history_action.triggered.connect(self.history_requested.emit)
        self.menu.addAction(self.history_action)

        self.settings_action = QAction(tr("设置…"), self.menu)
        self.settings_action.triggered.connect(self.settings_requested.emit)
        self.menu.addAction(self.settings_action)

        self.cache_action = QAction(tr("清空翻译缓存"), self.menu)
        self.cache_action.triggered.connect(self.cache_clear_requested.emit)
        self.menu.addAction(self.cache_action)

        self.menu.addSeparator()

        self.quit_action = QAction(tr("退出"), self.menu)
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
        disabled = tr("未启用")
        hotkey = format_hotkey(self._config.hotkey) if self._config.hotkey_enabled else disabled
        self.icon.setToolTip(
            f"{app_title()} v{APP_VERSION}\n"
            + trn("目标语言：{language}", language=lang_label(self._config.target_lang))
            + "\n"
            + trn("截图热键：{hotkey}", hotkey=hotkey)
        )
        if hasattr(self, "capture_action"):
            self.capture_action.setText(
                tr("截图翻译")
                if hotkey == disabled
                else trn("截图翻译（{hotkey}）", hotkey=hotkey)
            )

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
