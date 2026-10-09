"""历史记录面板：查看、复制、清空最近的翻译。"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .history import HistoryEntry


class HistoryPanel(QDialog):
    """历史记录浏览窗口。"""

    #: 用户请求重新翻译某条记录（参数为原文）
    retranslate_requested = Signal(str)
    #: 用户确认清空
    clear_requested = Signal()

    def __init__(self, entries: Optional[List[HistoryEntry]] = None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("翻译历史")
        self.resize(760, 480)
        self._entries: List[HistoryEntry] = []

        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "方向", "原文", "译文"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._on_select)
        splitter.addWidget(self.table)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        detail_layout.addWidget(self.detail)
        splitter.addWidget(detail)
        splitter.setSizes([300, 180])
        layout.addWidget(splitter)

        buttons = QHBoxLayout()
        self.count_label = QLabel("")
        buttons.addWidget(self.count_label)
        buttons.addStretch(1)

        self.retranslate_button = QPushButton("重译此条")
        self.retranslate_button.setEnabled(False)
        self.retranslate_button.clicked.connect(self._on_retranslate)
        buttons.addWidget(self.retranslate_button)

        self.copy_button = QPushButton("复制译文")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._on_copy)
        buttons.addWidget(self.copy_button)

        self.clear_button = QPushButton("清空历史")
        self.clear_button.clicked.connect(self._on_clear)
        buttons.addWidget(self.clear_button)

        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.hide)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.set_entries(entries or [])

    # ------------------------------------------------------------------
    def set_entries(self, entries: List[HistoryEntry]) -> None:
        """刷新列表（最新的在最上面）。"""
        self._entries = list(reversed(entries))
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            cells = [
                entry.time_text,
                f"{entry.source_lang} → {entry.target_lang}",
                _one_line(entry.original),
                _one_line(entry.translation),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        self.count_label.setText(f"共 {len(self._entries)} 条")
        if self._entries:
            self.table.selectRow(0)
            self._on_select()  # 立即填充详情，不依赖选中变化信号
        else:
            self.detail.clear()
            self.retranslate_button.setEnabled(False)
            self.copy_button.setEnabled(False)

    # ------------------------------------------------------------------
    def _current(self) -> Optional[HistoryEntry]:
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _on_select(self) -> None:
        entry = self._current()
        if entry is None:
            return
        self.detail.setPlainText(
            f"时间：{entry.time_text}\n"
            f"方向：{entry.source_lang} → {entry.target_lang}\n"
            f"引擎：{entry.provider or '—'}\n"
            f"耗时：{entry.elapsed:.2f}s\n"
            f"\n【原文】\n{entry.original}\n\n【译文】\n{entry.translation}"
        )
        self.retranslate_button.setEnabled(True)
        self.copy_button.setEnabled(bool(entry.translation))

    def _on_copy(self) -> None:
        entry = self._current()
        if entry and entry.translation:
            QApplication.clipboard().setText(entry.translation)

    def _on_retranslate(self) -> None:
        entry = self._current()
        if entry and entry.original:
            self.retranslate_requested.emit(entry.original)

    def _on_clear(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空历史",
            f"确定要删除全部 {len(self._entries)} 条历史记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.clear_requested.emit()


def _one_line(text: str, limit: int = 60) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


__all__ = ["HistoryPanel"]
