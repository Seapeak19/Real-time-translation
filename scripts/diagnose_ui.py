"""设置界面外观诊断：真实渲染 + 配色对比度检查 + 字体检查。

用途：界面出现"乱码"或"一明一暗"时，先看清实际渲染成了什么，而不是靠猜。

"乱码"的常见真身是**白底白字**——深色系统下调色板的前景色是白色，
而 QSS 只写了背景色为白色，文字就"消失"了。因此这里会自动计算
每个可见文字控件的对比度，任何一个低于阈值的都会被点名。

输出：

* 系统与应用是否处于深色模式
* Qt 实际生效的调色板
* 界面里用到的字体与特殊字符能否渲染
* 每个页面里对比度过低的控件（白底白字会直接被抓出来）
* ``testdata/settings_pN_*.png`` —— 各页真实渲染结果

用法::

    .venv\\Scripts\\python scripts\\diagnose_ui.py
    .venv\\Scripts\\python scripts\\diagnose_ui.py --page 1
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 与 fanyi/app.py 保持一致
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

OUT = ROOT / "testdata"

#: 对比度低于该值就算"看不清"
MIN_CONTRAST = 2.5


def relative_luminance(color) -> float:
    """WCAG 相对亮度。"""
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground, background) -> float:
    """WCAG 对比度（1.0 ~ 21.0）。"""
    light, dark = sorted(
        (relative_luminance(foreground), relative_luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


def effective_background(widget):
    """（已由 :func:`resolve_background` 取代，保留作参考实现。）"""
    node = widget
    while node is not None:
        color = node.palette().color(node.backgroundRole())
        if color.alpha() > 0:
            return color
        node = node.parentWidget()
    return None


def widget_text_color(widget):
    return widget.palette().color(widget.foregroundRole())


def sample_pixel_color(widget, ratio_x: float = 0.0, ratio_y: float = 0.0):
    """推断控件背后的真实底色（含 QSS 效果）。

    做法是取四个角的像素并挑**最亮**的那个：

    * 透明控件（QLabel 等）抓出来四角是 ``alpha=0``，Qt 会把 RGB 读成黑色，
      所以要跳过透明像素、由调用方继续向父控件找；
    * 不能只取一个点——文字笔画可能正好落在取样点上，
      于是"前景色"被当成"背景色"，会算出 1.00 的假对比度。
      四角取最亮值可以避开笔画干扰（文字是深色）。
    """
    from PySide6.QtCore import QPoint

    pixmap = widget.grab()
    if pixmap.isNull() or pixmap.width() < 3 or pixmap.height() < 3:
        return None
    image = pixmap.toImage()
    width, height = image.width(), image.height()

    corners = [(0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)]
    opaque = []
    for x, y in corners:
        color = image.pixelColor(QPoint(x, y))
        if color.alpha() > 0:
            opaque.append(color)
    if not opaque:
        return None
    return max(opaque, key=lambda c: c.lightness())


def resolve_background(widget, app):
    """递归向上找到文字真正的底色（自己透明就问父控件）。"""
    node = widget
    depth = 0
    while node is not None and depth < 12:
        color = sample_pixel_color(node)
        if color is not None:
            return color
        node = node.parentWidget()
        depth += 1
    # 全都透明时，退回调色板的 Window 色
    return app.palette().color(QPalette.ColorRole.Window)


def audit_page(window, app) -> list:
    """扫描当前页面里所有可见文字控件，返回对比度过低的项。"""
    from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit

    problems = []
    app.processEvents()

    widgets = []
    for child in (
        window.findChildren(QLabel)
        + window.findChildren(QAbstractButton)
        + window.findChildren(QLineEdit)
    ):
        text = child.text() if hasattr(child, "text") else ""
        if child.isVisible() and text and text.strip():
            widgets.append(child)

    for widget in widgets:
        text = widget.text()
        foreground = widget_text_color(widget)
        background = resolve_background(widget, app)
        if background is None:
            continue
        ratio = contrast_ratio(foreground, background)
        if ratio < MIN_CONTRAST:
            problems.append(
                f"{type(widget).__name__}({widget.objectName() or '-'}) "
                f"文字={text[:18]!r} 前景={foreground.name()} 背景≈{background.name()} "
                f"对比度={ratio:.2f}"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="设置界面外观诊断")
    parser.add_argument("--page", type=int, default=None, help="只渲染指定页（0=语言 1=快捷键 …）")
    parser.add_argument("--no-theme", action="store_true", help="不套用明亮主题（用于对比修复前）")
    args = parser.parse_args()

    OUT.mkdir(exist_ok=True)

    print("=" * 76)
    print("  设置界面外观诊断")
    print("=" * 76)

    # --- 1. 系统深色模式 ---
    print("\n[1] 系统深色模式")
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            try:
                value, _ = winreg.QueryValueEx(key, name)
                print(f"    {name:<24} = {value}（{'浅色' if value == 1 else '深色'}）")
            except FileNotFoundError:
                print(f"    {name:<24} = 未设置")
        winreg.CloseKey(key)
    except Exception as exc:
        print(f"    读取注册表失败: {exc}")

    from PySide6.QtGui import QGuiApplication, QPalette
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])

    if not args.no_theme:
        from fanyi.ui.theme import apply_light_theme

        apply_light_theme(app)
        print("    已套用明亮主题（与真实程序一致）")

    # --- 2. 调色板 ---
    print("\n[2] Qt 实际生效的调色板")
    print(f"    style() = {app.style().objectName()}")
    palette = app.palette()
    dark_roles = []
    for name, role in [
        ("Window", QPalette.ColorRole.Window),
        ("WindowText", QPalette.ColorRole.WindowText),
        ("Base", QPalette.ColorRole.Base),
        ("Text", QPalette.ColorRole.Text),
        ("Button", QPalette.ColorRole.Button),
        ("ButtonText", QPalette.ColorRole.ButtonText),
    ]:
        color = palette.color(role)
        if color.lightness() < 128:
            dark_roles.append(f"{name}={color.name()}")
        print(f"    {name:<12} {color.name()}  lightness={color.lightness():3d}")
    if dark_roles:
        print(f"    → 仍是深色的角色：{', '.join(dark_roles)}")
    else:
        print("    → 全部为浅色 ✓")

    # --- 3. 字体 ---
    print("\n[3] 字体与特殊字符")
    from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics

    from fanyi.ui.theme import font_families_available, pick_ui_font

    print(f"    候选中可用: {font_families_available()}")
    chosen = pick_ui_font()
    print(f"    实际选用   : {chosen.family()} {chosen.pointSize()}pt")
    test_chars = "译 ⇄ → · ⚠ × 　"
    metrics = QFontMetrics(chosen)
    missing = [ch for ch in test_chars if ch.strip() and not metrics.inFont(ch)]
    print(f"    特殊字符   : {'全部可渲染 ✓' if not missing else '缺字形 ' + ''.join(missing)}")

    # --- 4. 渲染与对比度审计 ---
    print("\n[4] 渲染各页并审计文字对比度")
    from fanyi.config import Config
    from fanyi.ui.main_window import MainWindow

    window = MainWindow(Config())
    window.resize(880, 620)
    window.show()
    app.processEvents()

    names = ["语言", "快捷键", "识别OCR", "翻译", "界面"]
    pages = [args.page] if args.page is not None else list(range(window._stack.count()))

    total_problems = 0
    for index in pages:
        window._sidebar.setCurrentRow(index)
        app.processEvents()
        path = OUT / f"settings_p{index}_{names[index]}.png"
        window.grab().save(str(path))

        problems = audit_page(window, app)
        total_problems += len(problems)
        status = "无问题" if not problems else f"{len(problems)} 处对比度过低"
        print(f"    [{index}] {names[index]:<8} {status}   已保存 {path.name}")
        for item in problems:
            print(f"          ⚠ {item}")

    window.close()
    app.processEvents()

    # --- 5. 其它窗口也要统一明亮 ---
    print("\n[5] 其它窗口")
    from fanyi.ui.history import HistoryEntry, HistoryStore
    from fanyi.ui.history_panel import HistoryPanel
    from fanyi.ui.result_window import ResultWindow

    result = ResultWindow(target_lang="zh-Hans", source_lang="auto")
    result.show_result(
        original="Hello world, this is a screenshot translator.",
        translation="你好，世界，这是一个截图翻译工具。",
        provider="有道翻译",
        source_lang="en",
        elapsed=0.42,
    )
    result.resize(560, 380)
    result.show()
    app.processEvents()
    result.grab().save(str(OUT / "settings_result_window.png"))
    print(f"    已保存 settings_result_window.png")
    result.close()

    store = HistoryStore(OUT / "ui_check_history.json", limit=20)
    store.clear()
    for index in range(3):
        store.add(
            HistoryEntry(
                original=f"第 {index + 1} 条原文：Hello world",
                translation=f"第 {index + 1} 条译文：你好，世界",
                source_lang="en",
                target_lang="zh-Hans",
                provider="有道翻译",
                elapsed=0.3,
            )
        )
    panel = HistoryPanel(store.all())
    panel.resize(700, 420)
    panel.show()
    app.processEvents()
    panel.grab().save(str(OUT / "settings_history_panel.png"))
    print(f"    已保存 settings_history_panel.png")
    panel.close()
    app.processEvents()

    print("\n" + "=" * 76)
    if total_problems:
        print(f"  发现 {total_problems} 处文字对比度过低（很可能就是用户看到的「乱码」）")
        return 1
    print("  未发现对比度问题，配色统一 ✓")
    print("  请打开 testdata 下的 PNG 目视确认：底色应为纯白、文字清晰、无深色区块")
    return 0


if __name__ == "__main__":
    sys.exit(main())
