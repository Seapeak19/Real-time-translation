"""统一主题：强制明亮白色外观。

为什么需要它：Windows 处于深色模式时，Qt 会给出深色调色板
（``Window=#1e1e1e``、``Base=#2d2d2d``、``Text=#ffffff``）。
如果界面只用 QSS 指定背景色、不指定前景色，就会出现：

* 下拉框 / 输入框文字是白色，拍在白底上 → 看起来像空白或乱码；
* 侧栏、分组框是深灰，内容区是白色 → 一明一暗，非常别扭。

解决办法是**同时**做两件事，而不是逐个控件补 ``color``：

1. 给 ``QApplication`` 装一套完整的浅色调色板（StyleHint、各 ColorRole 都定义），
   这样任何没有被 QSS 覆盖到的控件也会渲染成浅色；
2. 用 Fusion 样式，避免 ``windows11`` 样式在深色模式下对原生控件做自己的染色。

这样新增控件不用再操心配色，主题是"默认就对"的。
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配色（界面里出现的颜色都集中在这里，方便统一调整）
# ---------------------------------------------------------------------------
WHITE = "#FFFFFF"
SURFACE = "#F6F8FC"        # 侧栏 / 状态栏这类次级背景
SURFACE_ALT = "#F9FAFC"    # 提示块背景
BORDER = "#D8DEE8"
BORDER_SOFT = "#E3E8F0"
TEXT = "#111827"           # 主文字
TEXT_MUTED = "#6B7280"     # 次要文字
TEXT_BODY = "#374151"      # 正文
ACCENT = "#2563EB"
ACCENT_DARK = "#1D4ED8"
ACCENT_SOFT = "#E3EDFF"
DANGER = "#DC2626"

#: 中文字体优先级。按顺序找第一个系统里存在的，
#: 避免用默认字体时英文与中文来自两个字族、基线不齐、字形突兀。
FONT_CANDIDATES = [
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "SimHei",
    "SimSun",
]

#: 全局样式表。只写"外观"，颜色尽量交给调色板，减少两处打架的机会。
BASE_STYLESHEET = f"""
QWidget {{ color: {TEXT}; }}

QDialog, QMainWindow {{ background: {WHITE}; }}

QLabel {{ background: transparent; color: {TEXT}; }}
QLabel:disabled {{ color: {TEXT_MUTED}; }}

QGroupBox {{
    background: {WHITE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
    margin-top: 12px;
    padding: 12px 12px 10px 12px;
    color: {TEXT_BODY};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {TEXT_BODY};
}}

QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: #BFDBFE;
    selection-color: {TEXT};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {{
    border-color: #A9C7FF;
}}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled {{
    background: {SURFACE};
    color: #9CA3AF;
}}
QComboBox QAbstractItemView {{
    background: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT_DARK};
    outline: none;
}}

QPushButton {{
    background: {WHITE};
    color: {TEXT_BODY};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{ background: #F0F5FF; border-color: #A9C7FF; color: {ACCENT_DARK}; }}
QPushButton:pressed {{ background: {ACCENT_SOFT}; }}
QPushButton:disabled {{ background: {SURFACE}; color: #9CA3AF; border-color: {BORDER_SOFT}; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; border-color: #A9C7FF; color: {ACCENT_DARK}; }}

QCheckBox, QRadioButton {{ background: transparent; color: {TEXT}; spacing: 6px; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: #9CA3AF; }}

QListWidget, QListView, QTreeView, QTableView, QTableWidget {{
    background: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER_SOFT};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{ padding: 5px 6px; border-radius: 4px; color: {TEXT}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}

/* 表格：选中态也要浅色，避免在明亮界面里出现一大块深蓝 */
QTableWidget::item, QTableView::item {{ color: {TEXT}; padding: 2px 4px; }}
QTableWidget::item:selected, QTableView::item:selected {{
    background: {ACCENT_SOFT}; color: {ACCENT_DARK};
}}
QTableWidget::item:alternate, QTableView::item:alternate {{ background: {SURFACE_ALT}; }}
QTableCornerButton::section {{ background: {SURFACE}; border: none; }}
QHeaderView::section {{
    background: {SURFACE};
    color: {TEXT_BODY};
    border: none;
    border-right: 1px solid {BORDER_SOFT};
    border-bottom: 1px solid {BORDER_SOFT};
    padding: 5px 8px;
}}

QScrollArea {{ background: {WHITE}; border: none; }}
QScrollArea > QWidget > QWidget {{ background: {WHITE}; }}
QAbstractScrollArea::corner {{ background: {WHITE}; }}

QMenu {{
    background: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 18px; border-radius: 4px; color: {TEXT}; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT_DARK}; }}
QMenu::separator {{ height: 1px; background: {BORDER_SOFT}; margin: 4px 8px; }}

QToolTip {{
    background: #1F2937;
    color: {WHITE};
    border: 1px solid #374151;
    padding: 4px 6px;
}}

QScrollBar:vertical, QScrollBar:horizontal {{ background: {SURFACE}; border: none; }}
QScrollBar:vertical {{ width: 10px; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar::handle {{ background: #C7D2E0; border-radius: 5px; min-height: 24px; min-width: 24px; }}
QScrollBar::handle:hover {{ background: #A9B8CC; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTabWidget::pane {{ border: 1px solid {BORDER_SOFT}; border-radius: 6px; background: {WHITE}; }}
QTabBar::tab {{
    background: {SURFACE};
    color: {TEXT_BODY};
    border: 1px solid {BORDER_SOFT};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {WHITE}; color: {ACCENT_DARK}; font-weight: 600; }}

QSplitter::handle {{ background: {BORDER_SOFT}; }}
QStatusBar {{ background: {SURFACE}; color: {TEXT_MUTED}; }}
"""


# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
def pick_ui_font(point_size: int = 10) -> QFont:
    """挑一个能同时显示中英文的界面字体。"""
    families = set(QFontDatabase.families())
    for name in FONT_CANDIDATES:
        if name in families:
            font = QFont(name, point_size)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
            return font
    logger.debug("没有找到候选中文字体，使用系统默认字体")
    return QFont("", point_size)


def apply_font(app: QApplication, point_size: int = 10) -> None:
    app.setFont(pick_ui_font(point_size))


# ---------------------------------------------------------------------------
# 调色板
# ---------------------------------------------------------------------------
def light_palette() -> QPalette:
    """构造完整的浅色调色板。

    关键是把 ``Text`` / ``WindowText`` / ``ButtonText`` 这类**前景色**也设成深色，
    否则深色模式下它们会是白色，落在浅色底上就看不见了。
    """
    palette = QPalette()

    window = QColor(WHITE)
    surface = QColor(SURFACE)
    text = QColor(TEXT)
    muted = QColor(TEXT_MUTED)
    accent = QColor(ACCENT)
    accent_soft = QColor(ACCENT_SOFT)

    # --- 激活 / 非激活 / 失效 三种状态都要给，否则切换窗口时会闪回深色 ---
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Normal,
    ):
        palette.setColor(group, QPalette.ColorRole.Window, window)
        palette.setColor(group, QPalette.ColorRole.WindowText, text)
        palette.setColor(group, QPalette.ColorRole.Base, window)
        palette.setColor(group, QPalette.ColorRole.AlternateBase, surface)
        palette.setColor(group, QPalette.ColorRole.Text, text)
        palette.setColor(group, QPalette.ColorRole.Button, surface)
        palette.setColor(group, QPalette.ColorRole.ButtonText, text)
        palette.setColor(group, QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, window)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, text)
        palette.setColor(group, QPalette.ColorRole.Highlight, accent)
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        palette.setColor(group, QPalette.ColorRole.Link, accent)
        palette.setColor(group, QPalette.ColorRole.LinkVisited, QColor("#7C3AED"))
        palette.setColor(group, QPalette.ColorRole.PlaceholderText, muted)
        palette.setColor(group, QPalette.ColorRole.Light, QColor("#FFFFFF"))
        palette.setColor(group, QPalette.ColorRole.Midlight, QColor("#F1F4F9"))
        palette.setColor(group, QPalette.ColorRole.Mid, QColor("#D8DEE8"))
        palette.setColor(group, QPalette.ColorRole.Dark, QColor("#B9C2D0"))
        palette.setColor(group, QPalette.ColorRole.Shadow, QColor("#8A94A6"))

    # 禁用态：文字压灰，背景保持浅色
    disabled = QPalette.ColorGroup.Disabled
    palette.setColor(disabled, QPalette.ColorRole.Window, window)
    palette.setColor(disabled, QPalette.ColorRole.WindowText, QColor("#9CA3AF"))
    palette.setColor(disabled, QPalette.ColorRole.Base, surface)
    palette.setColor(disabled, QPalette.ColorRole.Text, QColor("#9CA3AF"))
    palette.setColor(disabled, QPalette.ColorRole.Button, surface)
    palette.setColor(disabled, QPalette.ColorRole.ButtonText, QColor("#9CA3AF"))
    palette.setColor(disabled, QPalette.ColorRole.ToolTipText, QColor("#9CA3AF"))
    palette.setColor(disabled, QPalette.ColorRole.Highlight, accent_soft)
    palette.setColor(disabled, QPalette.ColorRole.HighlightedText, muted)
    palette.setColor(disabled, QPalette.ColorRole.PlaceholderText, muted)

    return palette


def apply_light_theme(app: QApplication, font_point_size: int = 10) -> QApplication:
    """把明亮主题应用到整个应用。必须在创建任何窗口之前调用。"""
    # Fusion 在各平台表现一致，且不会像 windows11 样式那样在深色模式下自行染色
    app.setStyle("Fusion")
    app.setPalette(light_palette())
    apply_font(app, font_point_size)
    app.setStyleSheet(BASE_STYLESHEET)
    logger.debug("已应用明亮主题（Fusion + 浅色调色板 + 全局样式表）")
    return app


def apply_to_window(window: QWidget) -> None:
    """把全局样式表补挂到独立窗口上。

    设置了 windowFlags 的顶层窗口（结果窗、历史面板）在部分平台上
    不会自动继承应用级样式表，这里补一次，保证外观一致。
    """
    if not window.styleSheet():
        window.setStyleSheet(BASE_STYLESHEET)


def font_families_available(candidates: Optional[List[str]] = None) -> List[str]:
    """返回候选中实际可用的字体族（供诊断脚本使用）。"""
    wanted = candidates or FONT_CANDIDATES
    available = set(QFontDatabase.families())
    return [name for name in wanted if name in available]


__all__ = [
    "ACCENT",
    "ACCENT_SOFT",
    "BASE_STYLESHEET",
    "BORDER",
    "BORDER_SOFT",
    "FONT_CANDIDATES",
    "SURFACE",
    "SURFACE_ALT",
    "TEXT",
    "TEXT_BODY",
    "TEXT_MUTED",
    "WHITE",
    "apply_font",
    "apply_light_theme",
    "apply_to_window",
    "font_families_available",
    "light_palette",
    "pick_ui_font",
]
