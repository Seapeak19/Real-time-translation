"""框选覆盖层：把抓屏结果铺满虚拟桌面，让用户拖拽选出要翻译的区域。

设计要点：

* **覆盖层不参与抓屏**：图片在显示覆盖层之前就已经抓好，绘制时只做"调暗 + 挖洞"，
  不存在把自己的半透明遮罩拍进去的问题。
* **多显示器**：每个屏幕一个覆盖层窗口，共用一个已抓好的虚拟桌面位图。
* **纯逻辑与 Qt 分离**：坐标换算、选区规范化都放在 :class:`SelectionOverlay` 的
  纯函数里，方便单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from .screenshot import Capture

#: 选区小于该尺寸（物理像素）视为误触
MIN_SELECTION = 8

DIM_ALPHA = 110
BORDER_COLOR = QColor(0, 174, 255)
HINT_BG = QColor(0, 0, 0, 180)
HINT_FG = QColor(255, 255, 255)


@dataclass
class Selection:
    """一次框选结果（虚拟桌面物理像素坐标）。"""

    x: int
    y: int
    width: int
    height: int
    capture: Capture

    @property
    def rect(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    @property
    def is_valid(self) -> bool:
        return self.width >= MIN_SELECTION and self.height >= MIN_SELECTION


def normalize_rect(a: Tuple[int, int], b: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """由两个角点得到规范化的 ``(x, y, w, h)``，w/h 最小为 0。"""
    left, right = sorted((int(a[0]), int(b[0])))
    top, bottom = sorted((int(a[1]), int(b[1])))
    return left, top, max(0, right - left), max(0, bottom - top)


def clamp_rect(rect: Tuple[int, int, int, int], bounds: Tuple[int, int, int, int]):
    """把矩形裁剪到 ``bounds`` 内。"""
    x, y, w, h = rect
    bx, by, bw, bh = bounds
    left = max(x, bx)
    top = max(y, by)
    right = min(x + w, bx + bw)
    bottom = min(y + h, by + bh)
    return left, top, max(0, right - left), max(0, bottom - top)


class SelectionOverlay(QWidget):
    """单屏覆盖层。"""

    region_selected = Signal(object)  # Selection
    cancelled = Signal()

    def __init__(
        self,
        capture: Capture,
        geometry: Tuple[int, int, int, int],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._capture = capture
        self._virtual_origin = capture.origin
        self._screen_geometry = geometry  # 本屏在虚拟桌面中的 (x, y, w, h)，物理像素

        self._origin: Optional[QPoint] = None  # 按下点（窗口逻辑坐标）
        self._current: Optional[QPoint] = None  # 当前点（窗口逻辑坐标）
        self._dragging = False
        self._finished = False

        self._source = QPixmap.fromImage(capture.image)
        self._scale = 1.0  # 位图像素 → 窗口逻辑像素
        self._dimmed: Optional[QPixmap] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(*geometry)
        self.setWindowTitle("选择要翻译的区域")

    # ------------------------------------------------------------------
    # 坐标换算
    # ------------------------------------------------------------------
    def _fit(self) -> None:
        """计算图片→窗口的缩放比例，并准备好调暗后的底图。"""
        rect = self.rect()
        if rect.isEmpty() or self._source.isNull():
            return
        self._scale = min(
            rect.width() / max(1, self._source.width()),
            rect.height() / max(1, self._source.height()),
        )
        scaled = self._source.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        # 预先调暗一次，后续每帧只做拷贝，避免拖拽时反复做像素运算
        dimmed = QPixmap(scaled.size())
        dimmed.fill(Qt.GlobalColor.transparent)
        painter = QPainter(dimmed)
        painter.drawPixmap(0, 0, scaled)
        painter.fillRect(dimmed.rect(), QColor(0, 0, 0, DIM_ALPHA))
        painter.end()
        self._dimmed = dimmed

    def _image_point(self, pos: QPoint) -> QPoint:
        """窗口逻辑坐标 → 抓屏位图坐标。"""
        if self._scale <= 1e-6:
            return QPoint(pos)
        return QPoint(int(pos.x() / self._scale), int(pos.y() / self._scale))

    def _to_virtual(self, pos: QPoint) -> QPoint:
        """窗口逻辑坐标 → 虚拟桌面物理坐标。"""
        image_point = self._image_point(pos)
        return QPoint(
            self._virtual_origin[0] + image_point.x(),
            self._virtual_origin[1] + image_point.y(),
        )

    def _widget_rect(self) -> QRect:
        """当前选区在窗口中的矩形。"""
        if self._origin is None or self._current is None:
            return QRect()
        x, y, w, h = normalize_rect(
            (self._origin.x(), self._origin.y()), (self._current.x(), self._current.y())
        )
        return QRect(x, y, w, h)

    def virtual_selection(self) -> Optional[Selection]:
        """把当前选区换算成虚拟桌面坐标下的截图区域。"""
        rect = self._widget_rect()
        if rect.isNull():
            return None
        top_left = self._to_virtual(rect.topLeft())
        bottom_right = self._to_virtual(rect.bottomRight())
        x, y, w, h = normalize_rect(
            (top_left.x(), top_left.y()), (bottom_right.x(), bottom_right.y())
        )
        x, y, w, h = clamp_rect(
            (x, y, w, h),
            (
                self._virtual_origin[0],
                self._virtual_origin[1],
                self._capture.width,
                self._capture.height,
            ),
        )
        return Selection(x=x, y=y, width=w, height=h, capture=self._capture)

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self._fit()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._origin = event.position().toPoint()
        self._current = self._origin
        self._dragging = True
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint()
        if self._dragging:
            self._current = pos
        else:
            self._current = pos
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = event.position().toPoint()
        selection = self.virtual_selection()
        if selection is None or not selection.is_valid:
            # 只是点了一下没拖动：重新开始，不退出
            self._origin = None
            self._current = None
            self.update()
            return
        self._finish(selection)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()

    # ------------------------------------------------------------------
    def _finish(self, selection: Selection) -> None:
        if self._finished:
            return
        self._finished = True
        self.region_selected.emit(selection)

    def _cancel(self) -> None:
        if self._finished:
            return
        self._finished = True
        self.cancelled.emit()

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        if self._dimmed is not None:
            painter.drawPixmap(0, 0, self._dimmed)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 160))

        selection = self._widget_rect()
        if not selection.isNull():
            self._paint_selection(painter, selection)

        self._paint_hint(painter)
        painter.end()

    def _paint_selection(self, painter: QPainter, selection: QRect) -> None:
        # 挖洞：把选区内的原图（调暗前的）画回去
        clipped = selection.intersected(self.rect())
        if not clipped.isNull() and self._scale > 1e-6:
            source_rect = QRect(
                int(clipped.x() / self._scale),
                int(clipped.y() / self._scale),
                max(1, int(clipped.width() / self._scale)),
                max(1, int(clipped.height() / self._scale)),
            )
            painter.drawPixmap(clipped, self._source, source_rect)

        pen = QPen(BORDER_COLOR)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(selection.adjusted(1, 1, -1, -1))

        self._paint_corner_marks(painter, selection)
        self._paint_size_label(painter, selection)

        # 十字辅助线
        if self._current is not None:
            guide = QPen(QColor(0, 174, 255, 150))
            guide.setWidth(1)
            guide.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(guide)
            painter.drawLine(0, self._current.y(), self.width(), self._current.y())
            painter.drawLine(self._current.x(), 0, self._current.x(), self.height())

    @staticmethod
    def _paint_corner_marks(painter: QPainter, rect: QRect) -> None:
        pen = QPen(BORDER_COLOR)
        pen.setWidth(4)
        painter.setPen(pen)
        length = 10
        # 左上
        painter.drawLine(rect.left(), rect.top(), rect.left() + length, rect.top())
        painter.drawLine(rect.left(), rect.top(), rect.left(), rect.top() + length)
        # 右上
        painter.drawLine(rect.right(), rect.top(), rect.right() - length, rect.top())
        painter.drawLine(rect.right(), rect.top(), rect.right(), rect.top() + length)
        # 左下
        painter.drawLine(rect.left(), rect.bottom(), rect.left() + length, rect.bottom())
        painter.drawLine(rect.left(), rect.bottom(), rect.left(), rect.bottom() - length)
        # 右下
        painter.drawLine(rect.right(), rect.bottom(), rect.right() - length, rect.bottom())
        painter.drawLine(rect.right(), rect.bottom(), rect.right(), rect.bottom() - length)

    def _paint_size_label(self, painter: QPainter, rect: QRect) -> None:
        scale = self._capture.image.width() / max(1, self.width())
        text = f"{int(rect.width() * scale)} × {int(rect.height() * scale)}"
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 12
        height = metrics.height() + 4

        x = min(max(0, rect.left()), max(0, self.width() - width))
        y = rect.top() - height - 4
        if y < 0:
            y = min(self.height() - height, rect.bottom() + 4)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(QRect(x, y, width, height), 4, 4)
        painter.setPen(HINT_FG)
        painter.drawText(QRect(x, y, width, height), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_hint(self, painter: QPainter) -> None:
        text = "拖拽选择要翻译的区域    ·    ESC / 右键取消"
        font = QFont()
        font.setPointSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 32
        height = metrics.height() + 14
        x = (self.width() - width) // 2
        y = 24

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(HINT_BG)
        painter.drawRoundedRect(QRect(x, y, width, height), 8, 8)
        painter.setPen(HINT_FG)
        painter.drawText(QRect(x, y, width, height), Qt.AlignmentFlag.AlignCenter, text)


class OverlayManager:
    """在所有显示器上同时铺开覆盖层，任一处框选都算数。"""

    def __init__(self) -> None:
        self._overlays: List[SelectionOverlay] = []

    @property
    def active(self) -> bool:
        return bool(self._overlays)

    def start(
        self,
        capture: Capture,
        on_selected,
        on_cancelled,
    ) -> bool:
        """开始框选。返回是否成功铺开覆盖层。"""
        self.close()
        screens = QGuiApplication.screens()
        if not screens:
            return False

        for screen in screens:
            geometry = screen.geometry()
            # QScreen.geometry() 可能是逻辑像素；这里统一换算成物理像素
            ratio = float(screen.devicePixelRatio() or 1.0)
            physical = (
                int(round(geometry.x() * ratio)),
                int(round(geometry.y() * ratio)),
                int(round(geometry.width() * ratio)),
                int(round(geometry.height() * ratio)),
            )
            overlay = SelectionOverlay(capture, physical)
            overlay.region_selected.connect(on_selected)
            overlay.cancelled.connect(on_cancelled)
            self._overlays.append(overlay)

        for overlay in self._overlays:
            overlay.show()
        return True

    def close(self) -> None:
        for overlay in self._overlays:
            try:
                overlay.close()
            except Exception:
                pass
        self._overlays.clear()

    def hide_all(self) -> None:
        for overlay in self._overlays:
            overlay.hide()


__all__ = [
    "MIN_SELECTION",
    "OverlayManager",
    "Selection",
    "SelectionOverlay",
    "clamp_rect",
    "normalize_rect",
]
