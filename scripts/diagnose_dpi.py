"""诊断：框选覆盖层的坐标体系是否与实际屏幕一致。

背景：用户反馈"调出截图功能后屏幕比例发生变化，有些地方截不到"。
这通常是 DPI 缩放导致的坐标系错位——GDI 抓屏用物理像素，
而 Qt 窗口用的是逻辑像素，两者混用就会让覆盖层铺不满屏幕。

本脚本把两套坐标实测出来并直接对比，不做任何猜测。

用法::

    .venv\\Scripts\\python scripts\\diagnose_dpi.py
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 与 fanyi/app.py 保持一致：必须在导入 PySide6 之前关闭 Qt 的高 DPI 自动缩放，
# 否则测出来的不是真实程序的坐标体系。
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")


def gdi_metrics() -> dict:
    user32 = ctypes.windll.user32
    return {
        "SM_CXVIRTUALSCREEN(78)": user32.GetSystemMetrics(78),
        "SM_CYVIRTUALSCREEN(79)": user32.GetSystemMetrics(79),
        "SM_XVIRTUALSCREEN(76)": user32.GetSystemMetrics(76),
        "SM_YVIRTUALSCREEN(77)": user32.GetSystemMetrics(77),
        "SM_CXSCREEN(0)": user32.GetSystemMetrics(0),
        "SM_CYSCREEN(1)": user32.GetSystemMetrics(1),
    }


def process_dpi_info() -> dict:
    """进程自身的 DPI 感知级别（决定 GDI 返回物理还是虚拟化坐标）。"""
    try:
        shcore = ctypes.windll.shcore
        awareness = ctypes.c_int()
        # GetProcessDpiAwareness(0 = current process)
        hr = shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
        names = {
            0: "PROCESS_DPI_UNAWARE（GDI 返回虚拟化坐标，会错位！）",
            1: "PROCESS_SYSTEM_DPI_AWARE",
            2: "PROCESS_PER_MONITOR_DPI_AWARE（正确）",
        }
        if hr == 0:
            return {"GetProcessDpiAwareness": names.get(awareness.value, str(awareness.value))}
    except Exception as exc:
        return {"GetProcessDpiAwareness": f"查询失败: {exc}"}
    return {}


def main() -> int:
    print("=" * 78)
    print("  框选覆盖层坐标体系诊断")
    print("=" * 78)

    print("\n[1] GDI 报告的屏幕尺寸（物理像素）")
    for key, value in gdi_metrics().items():
        print(f"    {key:<26} {value}")

    print("\n[2] 进程 DPI 感知级别")
    info = process_dpi_info()
    if info:
        for key, value in info.items():
            print(f"    {key:<26} {value}")
    else:
        print("    （无法查询）")

    print("\n[3] Qt 报告的屏幕几何（关键：确认它给的是逻辑还是物理像素）")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    for index, screen in enumerate(app.screens()):
        geo = screen.geometry()
        avail = screen.availableGeometry()
        print(f"    屏幕 {index}: {screen.name()}")
        print(f"        geometry()          = ({geo.x()}, {geo.y()}) {geo.width()}×{geo.height()}")
        print(f"        availableGeometry() = ({avail.x()}, {avail.y()}) {avail.width()}×{avail.height()}")
        print(f"        devicePixelRatio()  = {screen.devicePixelRatio()}")
        print(f"        logicalDotsPerInch  = {screen.logicalDotsPerInch():.1f}")
        print(f"        physicalDotsPerInch = {screen.physicalDotsPerInch():.1f}")
        print(f"        size() (物理像素)    = {screen.size().width()}×{screen.size().height()}")

    print("\n[4] 覆盖层实际拿到的窗口尺寸（这里就是错位发生的地方）")
    from fanyi.overlay import SelectionOverlay
    from fanyi.screenshot import grab_virtual_desktop, virtual_desktop_rect

    capture = grab_virtual_desktop()
    if capture is None:
        print("    抓屏失败，后续检查跳过")
        return 1

    phys = virtual_desktop_rect()
    print(f"    GDI 虚拟桌面   = 原点({phys[0]}, {phys[1]}) {phys[2]}×{phys[3]}")
    print(f"    抓到位图       = {capture.width}×{capture.height}")

    screen = app.primaryScreen()
    geo = screen.geometry()
    ratio = float(screen.devicePixelRatio() or 1.0)

    # 修复后的取法：geometry() 已是设备像素，直接使用
    fixed = (
        int(geo.x()),
        int(geo.y()),
        int(geo.width()),
        int(geo.height()),
    )
    # 修复前的取法（乘以 DPR），保留用于对比
    old = (
        int(round(geo.x() * ratio)),
        int(round(geo.y() * ratio)),
        int(round(geo.width() * ratio)),
        int(round(geo.height() * ratio)),
    )
    print(f"\n    修复前取法（geometry × DPR）= {old[2]}×{old[3]}")
    print(f"    修复后取法（直接用 geometry）= {fixed[2]}×{fixed[3]}")
    print(f"    期望值（GDI 虚拟桌面）        = {phys[2]}×{phys[3]}")

    overlay = SelectionOverlay(capture, fixed)
    overlay.show()
    app.processEvents()
    overlay._fit()
    actual = overlay.geometry()
    print(f"    覆盖层窗口实际几何               = {actual.width()}×{actual.height()}")
    print(f"    覆盖层内部 rect()                = {overlay.width()}×{overlay.height()}")
    print(f"    位图 → 窗口 缩放比 _scale        = {overlay._scale:.4f}")

    verdict = []
    if ratio != 1.0:
        verdict.append(
            f"devicePixelRatio={ratio}（应为 1.0，说明 QT_ENABLE_HIGHDPI_SCALING 没生效）"
        )
    if actual.width() > phys[2] or actual.height() > phys[3]:
        verdict.append(
            f"覆盖层窗口({actual.width()}×{actual.height()}) 超过了屏幕({phys[2]}×{phys[3]})"
        )
    if abs(overlay._scale - 1.0) > 0.001:
        verdict.append(
            f"缩放比 {overlay._scale:.4f} != 1.0，"
            "说明位图与窗口尺寸不一致，框选坐标会被系统性地放大/缩小"
        )
    if fixed[2] != phys[2] or fixed[3] != phys[3]:
        verdict.append(
            f"Qt 屏幕尺寸({fixed[2]}×{fixed[3]}) 与 GDI 抓屏({phys[2]}×{phys[3]}) 不一致"
        )

    # 模拟拖到屏幕最右下角，看能不能覆盖到全屏
    from PySide6.QtCore import QPoint

    overlay._origin = QPoint(0, 0)
    overlay._current = QPoint(overlay.width() - 1, overlay.height() - 1)
    selection = overlay.virtual_selection()
    if selection is not None:
        print(
            f"\n    拖满整个窗口得到的选区 = ({selection.x}, {selection.y}) "
            f"{selection.width}×{selection.height}"
        )
        if selection.width < phys[2] or selection.height < phys[3]:
            verdict.append(
                f"拖满窗口只能选到 {selection.width}×{selection.height}，"
                f"而屏幕是 {phys[2]}×{phys[3]} → 有区域截不到"
            )

    overlay.close()
    app.processEvents()

    print("\n[5] 结论")
    if verdict:
        for line in verdict:
            print(f"    [问题] {line}")
    else:
        print("    [通过] 覆盖层尺寸与屏幕一致，缩放比为 1.0，可覆盖全屏")
    return 1 if verdict else 0


if __name__ == "__main__":
    sys.exit(main())
