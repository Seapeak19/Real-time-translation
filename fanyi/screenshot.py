"""屏幕截图（Windows GDI 实现）。

为什么不用 Qt 自带的抓屏：

* ``QScreen.grabWindow`` 在"先显示覆盖层再抓屏"时会把覆盖层自己拍进去；
* 多显示器且缩放比例不同时，Qt 抓屏坐标系容易与虚拟桌面坐标错位。

GDI 的 ``BitBlt`` 直接从桌面 DC 取像素，只受物理像素影响，
配合 :func:`enable_dpi_awareness` 就能得到与虚拟桌面坐标一一对应的位图。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
from PySide6.QtGui import QImage

logger = logging.getLogger(__name__)

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0


@dataclass
class Capture:
    """一次截图的结果，同时记录它在虚拟桌面中的位置。"""

    image: QImage
    #: 截取区域左上角在虚拟桌面坐标中的位置
    origin: Tuple[int, int] = (0, 0)
    #: 截取区域尺寸（物理像素）
    width: int = 0
    height: int = 0

    def to_local(self, x: int, y: int) -> Tuple[int, int]:
        """把虚拟桌面坐标换算成图片内坐标。"""
        return int(x - self.origin[0]), int(y - self.origin[1])

    @property
    def is_empty(self) -> bool:
        return self.image.isNull() or self.width <= 0 or self.height <= 0


# ---------------------------------------------------------------------------
# DPI
# ---------------------------------------------------------------------------
def enable_dpi_awareness() -> bool:
    """开启 Per-Monitor V2 DPI 感知。

    必须在创建 QApplication 之前调用，否则 Windows 会对进程做 DPI 虚拟化，
    导致截图尺寸与实际坐标不一致（高分屏上表现为截图模糊、框选偏移）。
    """
    if sys.platform != "win32":
        return False
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return True
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 虚拟桌面几何
# ---------------------------------------------------------------------------
def virtual_desktop_rect() -> Tuple[int, int, int, int]:
    """返回整个虚拟桌面的 ``(x, y, width, height)``（物理像素）。"""
    try:
        user32 = ctypes.windll.user32
        x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        width = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if width > 0 and height > 0:
            return int(x), int(y), int(width), int(height)
    except Exception as exc:  # pragma: no cover
        logger.warning("获取虚拟桌面尺寸失败: %s", exc)
    return 0, 0, 0, 0


# ---------------------------------------------------------------------------
# 抓屏
# ---------------------------------------------------------------------------
def grab_rect(x: int, y: int, width: int, height: int) -> Optional[QImage]:
    """截取虚拟桌面上的一块矩形区域，失败返回 ``None``。"""
    if width <= 0 or height <= 0:
        return None
    if sys.platform != "win32":  # pragma: no cover - 仅支持 Windows
        raise RuntimeError("屏幕截图目前仅支持 Windows")

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    # 显式声明参数/返回类型：64 位下句柄是 8 字节，默认 c_int 会截断导致崩溃
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]

    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        return None
    hdc_mem = None
    hbitmap = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        if not hdc_mem or not hbitmap:
            return None
        old = gdi32.SelectObject(hdc_mem, hbitmap)

        if not gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, x, y, SRCCOPY):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # 负值表示自上而下，省去一次翻转
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = BI_RGB

        stride = width * 4
        buffer = ctypes.create_string_buffer(stride * height)
        scanned = gdi32.GetDIBits(
            hdc_mem, hbitmap, 0, height, buffer, ctypes.byref(header), DIB_RGB_COLORS
        )
        if scanned == 0:
            return None

        array = np.frombuffer(buffer, dtype=np.uint8, count=stride * height)
        array = array.reshape(height, width, 4)[:, :, :3][:, :, ::-1]  # BGRA → RGB
        array = np.ascontiguousarray(array)

        image = QImage(
            array.data, width, height, 3 * width, QImage.Format.Format_RGB888
        ).copy()  # copy() 让 QImage 拥有自己的数据，脱离 numpy 缓冲区
        gdi32.SelectObject(hdc_mem, old)
        return image
    except Exception as exc:  # pragma: no cover
        logger.exception("截图失败: %s", exc)
        return None
    finally:
        if hbitmap:
            gdi32.DeleteObject(hbitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_screen:
            user32.ReleaseDC(None, hdc_screen)


def grab_virtual_desktop() -> Optional[Capture]:
    """截取整个虚拟桌面（所有显示器）。"""
    x, y, width, height = virtual_desktop_rect()
    if width <= 0 or height <= 0:
        # 退回主屏
        try:
            from PySide6.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return None
            geo = screen.geometry()
            image = grab_rect(int(geo.x()), int(geo.y()), int(geo.width()), int(geo.height()))
            if image is None:
                return None
            return Capture(image=image, origin=(int(geo.x()), int(geo.y())),
                           width=int(geo.width()), height=int(geo.height()))
        except Exception:
            return None

    image = grab_rect(x, y, width, height)
    if image is None:
        return None
    return Capture(image=image, origin=(x, y), width=width, height=height)


def crop(capture: Capture, x: int, y: int, width: int, height: int) -> Optional[Capture]:
    """按虚拟桌面坐标从一次抓屏结果中裁剪出子图（不重新抓屏）。"""
    local_x, local_y = capture.to_local(x, y)
    # 夹紧到图片范围内，避免越界
    local_x = max(0, min(local_x, capture.width - 1))
    local_y = max(0, min(local_y, capture.height - 1))
    width = max(1, min(width, capture.width - local_x))
    height = max(1, min(height, capture.height - local_y))

    sub = capture.image.copy(local_x, local_y, width, height)
    if sub.isNull():
        return None
    return Capture(
        image=sub,
        origin=(capture.origin[0] + local_x, capture.origin[1] + local_y),
        width=width,
        height=height,
    )


def to_numpy(image: QImage, scale: float = 1.0) -> np.ndarray:
    """QImage → RGB numpy 数组（可选放大，小字场景能明显提高识别率）。"""
    converted = image
    if scale and abs(scale - 1.0) > 1e-3:
        from PySide6.QtCore import Qt

        converted = image.scaled(
            max(1, int(image.width() * scale)),
            max(1, int(image.height() * scale)),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    if converted.format() != QImage.Format.Format_RGB888:
        converted = converted.convertToFormat(QImage.Format.Format_RGB888)

    width, height = converted.width(), converted.height()
    ptr = converted.constBits()
    buffer = bytes(ptr[: converted.sizeInBytes()])
    array = np.frombuffer(buffer, dtype=np.uint8)
    bytes_per_line = converted.bytesPerLine()
    if bytes_per_line != width * 3:
        array = array.reshape(height, bytes_per_line)[:, : width * 3]
    return array.reshape(height, width, 3).copy()


__all__ = [
    "Capture",
    "crop",
    "enable_dpi_awareness",
    "grab_rect",
    "grab_virtual_desktop",
    "to_numpy",
    "virtual_desktop_rect",
]
