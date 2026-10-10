"""框选覆盖层的坐标换算回归测试。

这个文件专门守住一个曾经真实出现的 bug：

* 高 DPI 下覆盖层尺寸算错，导致框选区域与屏幕对不上、边缘截不到；
* ``QRect`` 的闭区间与 ``normalize_rect`` 的半开区间混用，
  使每次框选都稳定少 1 像素，拖满全屏也选不到最右一列/最下一行。

两个问题都只在"真的把窗口铺开"时才会显形，因此这里用合成屏幕
（小尺寸 QImage + 单显示器几何）来构造可断言的场景。
"""

from __future__ import annotations

import os
from typing import Tuple

import pytest

# 与 fanyi/app.py 保持一致：必须在导入 PySide6 之前关掉 Qt 的高 DPI 自动缩放
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from fanyi.overlay import (  # noqa: E402
    MIN_SELECTION,
    Selection,
    SelectionOverlay,
    clamp_rect,
    normalize_rect,
)
from fanyi.screenshot import Capture  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def make_capture(width: int, height: int, origin: Tuple[int, int] = (0, 0)) -> Capture:
    """构造一张纯色位图当作抓屏结果，尺寸可控、不依赖真实屏幕。"""
    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(QColor("gray"))
    return Capture(image=image, origin=origin, width=width, height=height)


def make_overlay(qt_app, capture: Capture, geometry: Tuple[int, int, int, int]) -> SelectionOverlay:
    """建立一个与位图 1:1 的覆盖层（等价于真实环境里 DPR=1、尺寸一致的场景）。"""
    overlay = SelectionOverlay(capture, geometry)
    overlay.show()
    qt_app.processEvents()
    overlay._fit()
    return overlay


def drag(overlay: SelectionOverlay, start: QPointF, end: QPointF) -> None:
    """模拟一次按下 → 移动 → 释放。"""
    for kind, pos in (
        (QMouseEvent.Type.MouseButtonPress, start),
        (QMouseEvent.Type.MouseMove, end),
        (QMouseEvent.Type.MouseButtonRelease, end),
    ):
        event = QMouseEvent(
            kind,
            pos,
            overlay.mapToGlobal(pos.toPoint()),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        if kind == QMouseEvent.Type.MouseButtonPress:
            overlay.mousePressEvent(event)
        elif kind == QMouseEvent.Type.MouseMove:
            overlay.mouseMoveEvent(event)
        else:
            overlay.mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# 纯函数：区间语义
# ---------------------------------------------------------------------------
class TestNormalizeRect:
    def test_half_open_interval(self):
        # 半开区间：[10, 50) 宽 40，而不是闭区间理解的 41
        assert normalize_rect((10, 10), (50, 40)) == (10, 10, 40, 30)

    def test_direction_does_not_matter(self):
        assert normalize_rect((50, 40), (10, 10)) == (10, 10, 40, 30)
        assert normalize_rect((50, 10), (10, 40)) == (10, 10, 40, 30)

    def test_negative_coordinates(self):
        assert normalize_rect((-100, -50), (-20, -10)) == (-100, -50, 80, 40)

    def test_zero_span(self):
        assert normalize_rect((5, 5), (5, 5)) == (5, 5, 0, 0)


class TestClampRect:
    def test_clamped_inside(self):
        assert clamp_rect((-10, -10, 50, 50), (0, 0, 100, 100)) == (0, 0, 40, 40)

    def test_overflow_becomes_zero(self):
        # 完全在界外的矩形，坐标保留但尺寸归零（调用方据此判无效）
        assert clamp_rect((200, 200, 10, 10), (0, 0, 100, 100)) == (200, 200, 0, 0)

    def test_untouched_when_inside(self):
        assert clamp_rect((10, 10, 20, 20), (0, 0, 100, 100)) == (10, 10, 20, 20)


# ---------------------------------------------------------------------------
# 覆盖层：尺寸与坐标
# ---------------------------------------------------------------------------
class TestOverlayGeometry:
    def test_scale_is_one_when_sizes_match(self, qt_app):
        capture = make_capture(1920, 1080)
        overlay = make_overlay(qt_app, capture, (0, 0, 1920, 1080))
        assert overlay._scale == pytest.approx(1.0)
        overlay.close()

    def test_overlay_window_covers_exact_screen(self, qt_app):
        capture = make_capture(2560, 1440)
        overlay = make_overlay(qt_app, capture, (0, 0, 2560, 1440))
        geo = overlay.geometry()
        assert (geo.width(), geo.height()) == (2560, 1440)
        overlay.close()

    def test_overlay_not_larger_than_capture(self, qt_app):
        """回归：曾经把几何乘以 devicePixelRatio，在 125% 缩放下窗口比抓屏位图大。"""
        capture = make_capture(2560, 1440)
        overlay = make_overlay(qt_app, capture, (0, 0, 2560, 1440))
        assert overlay.width() <= capture.width
        assert overlay.height() <= capture.height
        overlay.close()


class TestSelectionMath:
    def test_full_drag_selects_entire_screen(self, qt_app):
        """回归：拖满全屏必须正好等于屏幕尺寸，不能少 1 像素。"""
        capture = make_capture(2560, 1440)
        overlay = make_overlay(qt_app, capture, (0, 0, 2560, 1440))

        overlay._origin = QPoint(0, 0)
        overlay._current = QPoint(2559, 1439)  # QRect 的闭区间右下角
        selection = overlay.virtual_selection()

        assert selection is not None
        assert (selection.x, selection.y) == (0, 0)
        assert (selection.width, selection.height) == (2560, 1440)
        assert selection.is_valid
        overlay.close()

    def test_forward_drag_region(self, qt_app):
        """从像素 100 拖到像素 300 是闭区间，覆盖 201 列像素。"""
        capture = make_capture(1000, 800)
        overlay = make_overlay(qt_app, capture, (0, 0, 1000, 800))
        drag(overlay, QPointF(100, 100), QPointF(300, 250))
        selection = overlay.virtual_selection()
        assert selection is not None
        assert (selection.x, selection.y, selection.width, selection.height) == (100, 100, 201, 151)
        overlay.close()

    def test_backward_drag_same_region(self, qt_app):
        """反方向拖拽必须得到与正向完全相同的选区。"""
        capture = make_capture(1000, 800)
        overlay = make_overlay(qt_app, capture, (0, 0, 1000, 800))
        drag(overlay, QPointF(300, 250), QPointF(100, 100))
        selection = overlay.virtual_selection()
        assert selection is not None
        assert (selection.x, selection.y, selection.width, selection.height) == (100, 100, 201, 151)
        overlay.close()

    def test_selection_with_monitor_origin_offset(self, qt_app):
        """副屏在主屏左侧/上方时原点为负，换算不能出错。"""
        capture = make_capture(800, 600, origin=(-1920, -200))
        overlay = make_overlay(qt_app, capture, (-1920, -200, 800, 600))
        overlay._origin = QPoint(0, 0)
        overlay._current = QPoint(799, 599)
        selection = overlay.virtual_selection()
        assert selection is not None
        assert (selection.x, selection.y) == (-1920, -200)
        assert (selection.width, selection.height) == (800, 600)
        overlay.close()

    def test_selection_clamped_into_capture_bounds(self, qt_app):
        """选区不能超出抓屏位图范围。"""
        capture = make_capture(500, 400)
        overlay = make_overlay(qt_app, capture, (0, 0, 500, 400))
        overlay._origin = QPoint(0, 0)
        overlay._current = QPoint(4999, 3999)  # 故意远超窗口
        selection = overlay.virtual_selection()
        assert selection is not None
        assert selection.width <= capture.width
        assert selection.height <= capture.height
        overlay.close()

    def test_tiny_drag_rejected(self, qt_app):
        """误点一下不应当产生有效选区。"""
        capture = make_capture(500, 400)
        overlay = make_overlay(qt_app, capture, (0, 0, 500, 400))
        overlay._origin = QPoint(10, 10)
        overlay._current = QPoint(10 + MIN_SELECTION - 2, 10 + MIN_SELECTION - 2)
        selection = overlay.virtual_selection()
        assert selection is not None
        assert not selection.is_valid
        overlay.close()

    def test_no_selection_before_drag(self, qt_app):
        capture = make_capture(500, 400)
        overlay = make_overlay(qt_app, capture, (0, 0, 500, 400))
        assert overlay.virtual_selection() is None
        overlay.close()


class TestOverlayLifecycle:
    def test_cancel_prevents_commit(self, qt_app):
        capture = make_capture(400, 300)
        overlay = make_overlay(qt_app, capture, (0, 0, 400, 300))
        emitted = []
        overlay.region_selected.connect(emitted.append)
        overlay._cancel()
        qt_app.processEvents()
        assert emitted == []
        overlay.close()

    def test_selection_signal_carries_capture(self, qt_app):
        capture = make_capture(400, 300)
        overlay = make_overlay(qt_app, capture, (0, 0, 400, 300))
        received = []
        overlay.region_selected.connect(received.append)
        overlay._origin = QPoint(0, 0)
        overlay._current = QPoint(49, 49)
        overlay._finish(overlay.virtual_selection())
        qt_app.processEvents()
        assert len(received) == 1
        assert isinstance(received[0], Selection)
        assert received[0].capture is capture
        overlay.close()
