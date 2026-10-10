"""GUI 冒烟测试：在真实 Qt 环境里跑一遍关键界面与流程（不依赖人工操作）。

覆盖：

* Qt 应用与 DPI 感知初始化
* 托盘图标与菜单构建
* 结果窗口三种状态（加载/成功/失败）与语言切换
* 设置面板构建与校验
* 历史面板与历史存储
* CPU 光栅化的框选覆盖层：模拟拖拽 → 选区坐标换算 → 真实 OCR + 翻译

用法::

    .venv\\Scripts\\python scripts\\gui_smoketest.py           # 含网络翻译
    .venv\\Scripts\\python scripts\\gui_smoketest.py --offline  # 跳过网络部分
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 与 fanyi/app.py 保持一致：Qt 的高 DPI 自动缩放必须关掉，
# 否则测试跑在"逻辑像素"坐标系里，与真实程序的设备像素坐标系不一致。
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")

failures: list = []


def check(condition: bool, title: str, detail: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    print(f"[{mark}] {title}" + (f"\n       {detail}" if detail else ""), flush=True)
    if not condition:
        failures.append(title)


def make_test_image(lines, size=(760, 260)):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    image = QImage(size[0], size[1], QImage.Format.Format_RGB888)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(QColor("black"))
    font = QFont("Microsoft YaHei UI", 20)
    painter.setFont(font)
    y = 50
    for line in lines:
        painter.drawText(40, y, line)
        y += 62
    painter.end()
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description="GUI 冒烟测试")
    parser.add_argument("--offline", action="store_true", help="跳过需要联网的步骤")
    args = parser.parse_args()

    print("=" * 70)
    print("  GUI 冒烟测试")
    print("=" * 70)

    # --- 1. DPI 感知 + Qt 应用 ---
    from fanyi.screenshot import enable_dpi_awareness

    aware = enable_dpi_awareness()
    print(f"[{'OK  ' if aware else 'WARN'}] DPI 感知: {aware}")

    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    app = QApplication(sys.argv[:1])
    check(app is not None, "创建 QApplication", f"平台插件 {app.platformName()}")

    # 与真实程序一致地套用明亮主题：否则本测试跑在系统深色调色板下，
    # 测出来的外观和用户看到的不是一回事
    from fanyi.ui.theme import apply_light_theme, light_palette

    apply_light_theme(app)
    from PySide6.QtGui import QPalette

    window_color = app.palette().color(QPalette.ColorRole.Window)
    check(
        window_color.lightness() > 200,
        "明亮主题已生效（窗口底色为浅色）",
        f"Window={window_color.name()} lightness={window_color.lightness()}",
    )
    check(QSystemTrayIcon.isSystemTrayAvailable(), "系统托盘可用")

    screens = app.screens()
    check(bool(screens), "检测到显示器", f"{len(screens)} 个：" + ", ".join(
        f"{s.name()} {s.geometry().width()}×{s.geometry().height()} @{s.devicePixelRatio()}x" for s in screens
    ))

    # --- 2. 托盘 ---
    from fanyi.config import Config
    from fanyi.ui.tray import TrayIcon, build_tray_icon

    icon = build_tray_icon()
    check(not icon.isNull(), "托盘图标绘制", f"可用尺寸 {[f'{s.width()}px' for s in icon.availableSizes()][:6]}")

    config = Config()
    tray = TrayIcon(config)
    tray.show()
    check(bool(tray.menu.actions()), "托盘菜单构建", f"{len(tray.menu.actions())} 个顶级项")
    tray.set_target("en")
    check(config.target_lang == "en", "托盘切换目标语言")
    tray.refresh_tooltip()
    check("英语" in tray.icon.toolTip(), "托盘提示刷新", tray.icon.toolTip().replace("\n", " | "))

    # --- 3. 结果窗口 ---
    from fanyi.ui.result_window import ResultWindow

    window = ResultWindow(target_lang="zh-Hans", source_lang="auto")
    window.show()
    check(window.isVisible(), "结果窗口显示")

    window.show_loading("正在识别文字…")
    check("识别" in window.status.text(), "loading 状态", window.status.text())

    window.show_result(
        original="Hello world",
        translation="你好，世界",
        provider="有道翻译",
        source_lang="en",
        elapsed=0.42,
    )
    check("你好" in window.translation_text.toPlainText(), "result 状态写入译文")
    check("英语" in window.title_label.text(), "标题显示语言方向", window.title_label.text())
    check(window.copy_button.isEnabled(), "复制按钮可用")
    check(window.copy_translation() is True, "复制译文到剪贴板")
    check(
        QApplication.clipboard().text() == "你好，世界",
        "剪贴板内容正确",
        QApplication.clipboard().text(),
    )

    window.show_error("网络超时", original="Hello world")
    check("网络超时" in window.status.text(), "error 状态", window.status.text())

    window.set_languages("auto", "zh-Hant")
    check("繁体" in window.target_button.text(), "语言标签更新", window.target_button.text())
    window.set_font_size(16)
    check(window.translation_text.font().pointSize() == 18, "字号设置生效（译文比原文大 2pt）")
    window.toggle_original()
    check(not window.original_text.isVisible(), "原文区域可收起")
    window.toggle_original()
    window.set_pinned(True)
    check(window.pinned is True, "置顶开关")
    window.resize(500, 320)
    window.move_near(100, 100, 200, 100)
    check(window.isVisible(), "移动到指定位置后仍可见")
    window.hide()

    # --- 4. 设置面板 ---
    from fanyi.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(config)
    check(dialog.target_combo.count() == 3, "目标语言下拉项", str(dialog.target_combo.count()))
    check(dialog.source_combo.count() == 4, "源语言下拉项（含自动检测）", str(dialog.source_combo.count()))
    check(dialog.engine_list.count() == 4, "后端列表", str(dialog.engine_list.count()))
    dialog.capture_hotkey_edit.setKeySequence("Ctrl+Alt+Q")
    dialog._on_accept()
    check(config.hotkey == "ctrl+alt+q", "设置保存热键", config.hotkey)
    dialog.deleteLater()

    # --- 5. 历史 ---
    from fanyi.ui.history import HistoryEntry, HistoryStore
    from fanyi.ui.history_panel import HistoryPanel

    store = HistoryStore(ROOT / "testdata" / "test_history.json", limit=20)
    store.clear()
    for index in range(3):
        store.add(HistoryEntry(original=f"原文{index}", translation=f"译文{index}", target_lang="zh-Hans"))
    check(len(store) == 3, "历史写入")

    reloaded = HistoryStore(ROOT / "testdata" / "test_history.json", limit=20)
    check(len(reloaded) == 3, "历史持久化后重新载入", f"{len(reloaded)} 条")

    panel = HistoryPanel(store.all())
    check(panel.table.rowCount() == 3, "历史面板行数", str(panel.table.rowCount()))
    check("【原文】" in panel.detail.toPlainText(), "历史详情展示")
    check("[译文]" not in panel.detail.toPlainText(), "详情使用中文标点而非方括号")
    panel.deleteLater()

    # set_limit 在已有多条记录时也要立即生效，并且不能低于 10 的下限
    store.set_limit(1)
    check(len(store) == 3, "上限有 10 条的下限保护", f"{len(store)} 条")

    big = HistoryStore(ROOT / "testdata" / "test_history2.json", limit=100)
    big.clear()
    for index in range(30):
        big.add(HistoryEntry(original=f"o{index}", translation=f"t{index}"))
    check(len(big) == 30, "上限内的记录全部保留", f"{len(big)} 条")
    big.set_limit(10)
    check(len(big) == 10, "调小上限后立即裁剪", f"{len(big)} 条")
    check(
        HistoryStore(ROOT / "testdata" / "test_history2.json", limit=100).all()[-1].original == "o29",
        "裁剪保留的是最新记录",
    )

    # --- 6. 覆盖层：模拟拖拽 + 坐标换算 ---
    from fanyi.overlay import OverlayManager
    from fanyi.screenshot import grab_virtual_desktop

    capture = grab_virtual_desktop()
    check(capture is not None and not capture.is_empty, "抓取虚拟桌面")

    overlay = None
    if capture is not None:
        from fanyi.overlay import SelectionOverlay

        rect = (capture.origin[0], capture.origin[1], capture.width, capture.height)
        overlay = SelectionOverlay(capture, rect)
        overlay.show()
        overlay._fit()

        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        start = QPointF(100, 100)
        end = QPointF(400, 260)

        def send(kind, pos):
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

        send(QMouseEvent.Type.MouseButtonPress, start)
        send(QMouseEvent.Type.MouseMove, end)
        selection = overlay.virtual_selection()
        check(selection is not None, "拖拽后得到选区")
        if selection is not None:
            expected_w = int(300 * overlay._scale)
            check(
                abs(selection.width - expected_w) <= 3,
                "选区宽度换算正确",
                f"选中 {selection.width}×{selection.height}，期望宽约 {expected_w}（缩放 {overlay._scale:.3f}）",
            )
            check(selection.is_valid, "选区有效（大于最小尺寸）")

        overlay._cancel()
        from PySide6.QtWidgets import QApplication as _App

        _App.processEvents()
        check(overlay._finished, "已取消的覆盖层不会再提交选区")

    manager = OverlayManager()
    started = manager.start(capture, on_selected=lambda s: None, on_cancelled=lambda: None)
    check(started, "覆盖层管理器铺开所有显示器", f"{len(manager._overlays)} 个覆盖层")
    manager.close()
    check(not manager.active, "覆盖层管理器可收起")

    # --- 7. 真实 OCR + 翻译（离线也能测 OCR） ---
    from fanyi.core.pipeline import PipelineError, TranslationPipeline

    test_image = make_test_image(["Hello, world", "Screenshot translator"])
    pipeline_config = Config()
    pipeline_config.target_lang = "zh-Hans"
    pipeline = TranslationPipeline(pipeline_config)

    from fanyi.screenshot import to_numpy

    try:
        ocr_result = pipeline.recognize(to_numpy(test_image))
        text = ocr_result.text.replace("\n", " | ")
        hit = "hello" in ocr_result.text.lower()
        check(hit and not ocr_result.is_empty, "对生成的图片做 OCR", f"{ocr_result.elapsed:.2f}s · {text}")
    except PipelineError as exc:
        check(False, "对生成的图片做 OCR", str(exc))

    if args.offline:
        print("[SKIP] 端到端翻译（--offline）")
    else:
        try:
            started_at = time.perf_counter()
            result = pipeline.run(to_numpy(test_image))
            elapsed = time.perf_counter() - started_at
            check(
                bool(result.translation),
                "端到端：图片 → 译文",
                f"{elapsed:.2f}s · {result.provider}\n       {result.source_text}\n       → {result.translation}",
            )
        except Exception as exc:
            check(False, "端到端：图片 → 译文", f"{type(exc).__name__}: {exc}")
    pipeline.close()

    # --- 8. 后台任务线程（TaskRunner）---
    from fanyi.ui.worker import TaskRunner

    runner = TaskRunner()
    received: list = []

    def slow_task(multiplier=None, *, base=2):
        time.sleep(0.25)
        return 21 * (multiplier or base)

    started_ok = runner.start(slow_task, received.append, received.append, 2)
    check(started_ok, "启动后台任务")
    check(runner.busy, "任务运行中 busy=True")
    check(runner.start(slow_task, received.append) is False, "并发任务被拒绝")

    deadline = time.time() + 5
    while not received and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(received and received[0] == 42, "任务结果经队列连接回到主线程", f"收到 {received}")

    deadline = time.time() + 3
    while runner.busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(not runner.busy, "任务结束后 busy=False")

    errors: list = []
    runner.start(lambda: (_ for _ in ()).throw(ValueError("故意失败")), received.append, errors.append)
    deadline = time.time() + 5
    while not errors and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    check(errors and isinstance(errors[0], ValueError), "任务异常也能回传主线程", f"{errors}")

    check(runner.wait(2000), "wait() 能等到任务结束")

    # --- 9. 设置主窗口 ---
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    from fanyi.ui.hotkey_edit import HotkeyEdit, qt_sequence_to_combo
    from fanyi.ui.main_window import MainWindow

    settings = MainWindow(Config())
    check(settings._stack.count() == 5, "设置窗口有 5 个页面")
    check(settings._sidebar.count() == 5, "侧栏导航项齐全",
          str([settings._sidebar.item(i).text() for i in range(settings._sidebar.count())]))
    check(settings.target_combo.count() == 3, "目标语言可选项")
    check(settings.source_combo.count() == 4, "源语言可选项（含自动检测）")
    check(settings.capture_hotkey.display.text() == "Ctrl + Alt + Z", "快捷键以可读形式展示",
          settings.capture_hotkey.display.text())
    check(settings.engine_list.count() == 4, "翻译后端可选项")
    settings.show()
    app.processEvents()
    check(settings.isVisible(), "设置窗口可以显示")

    # 语言：切换目标语言应发出信号
    language_signals = []
    settings.languages_changed.connect(lambda: language_signals.append(True))
    settings._set_target("en")
    app.processEvents()
    check(language_signals, "切换目标语言发出 languages_changed")
    check(settings.collect().target_lang == "en", "collect() 读回新目标语言")

    # 语言：互换按钮
    settings.source_combo.setCurrentIndex(settings.source_combo.findData("zh-Hans"))
    settings._set_target("en")
    settings._on_swap()
    check(
        settings.source_combo.currentData() == "en" and settings.target_combo.currentData() == "zh-Hans",
        "互换源/目标语言",
        f"源={settings.source_combo.currentData()} 目标={settings.target_combo.currentData()}",
    )

    # 快捷键录制：核心行为验证
    record_events = []
    settings.recording_changed.connect(record_events.append)
    hotkey_events = []
    settings.hotkeys_changed.connect(lambda: hotkey_events.append(True))

    settings.capture_hotkey.record_button.setChecked(True)
    app.processEvents()
    check(settings.capture_hotkey.recording, "点击录制后进入录制状态")
    check(record_events and record_events[-1] is True, "录制开始发出 recording_changed(True)",
          str(record_events))

    def press(widget, key, modifiers):
        widget.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, key, modifiers)
        )

    mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
    press(settings.capture_hotkey, Qt.Key.Key_F, mods)
    app.processEvents()
    check(settings.capture_hotkey.hotkey == "ctrl+shift+f", "录入 Ctrl+Shift+F",
          settings.capture_hotkey.hotkey)
    check(not settings.capture_hotkey.recording, "录入成功后自动退出录制状态")
    check(record_events[-1] is False, "录制结束发出 recording_changed(False)", str(record_events))
    check(hotkey_events, "录入成功后发出 hotkeys_changed")

    # 没有修饰键的组合必须被拒绝
    settings.capture_hotkey.record_button.setChecked(True)
    press(settings.capture_hotkey, Qt.Key.Key_K, Qt.KeyboardModifier.NoModifier)
    app.processEvents()
    check(settings.capture_hotkey.hotkey == "ctrl+shift+f", "拒绝无修饰键的按键",
          f"hotkey={settings.capture_hotkey.hotkey} 提示={settings.capture_hotkey.hint.text()}")
    check(bool(settings.capture_hotkey.hint.text()), "拒绝时给出提示文案")
    settings.capture_hotkey.stop_recording()

    # Esc 取消录制
    settings.capture_hotkey.record_button.setChecked(True)
    press(settings.capture_hotkey, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    app.processEvents()
    check(not settings.capture_hotkey.recording, "Esc 取消录制")
    check(settings.capture_hotkey.hotkey == "ctrl+shift+f", "Esc 不修改已有快捷键")

    # 「默认」按钮恢复出厂值
    settings.capture_hotkey.reset_button.click()
    check(settings.capture_hotkey.hotkey == "ctrl+alt+z", "「默认」恢复出厂快捷键",
          settings.capture_hotkey.hotkey)

    # 状态栏应反映当前设置
    settings.set_hotkey_status(["ctrl+alt+z"], "")
    check("截图热键" in settings.status_label.text(), "状态栏显示热键状态",
          settings.status_label.text())
    settings.set_hotkey_status([], "被其它程序占用")
    check("未生效" in settings.status_label.text(), "热键失败时状态栏给出警告",
          settings.status_label.text())

    settings.deleteLater()

    # --- 10. 控制器装配（不启动事件循环，只验证对象能构造与互连） ---
    from fanyi.ui.controller import AppController

    controller = AppController(Config())
    check(controller.tray is not None and controller.worker is not None, "控制器装配")
    controller.set_target_language("en")
    check(controller.config.target_lang == "en", "控制器切换目标语言")
    check(controller.translation.engine_names()[0] == "youdao", "默认首选后端", controller.translation.engine_names()[0])

    # 控制器 ↔ 设置窗口：打开、录制时临时解绑热键、关闭后恢复
    controller.open_settings()
    app.processEvents()
    main_window = controller._main_window
    check(main_window is not None and main_window.isVisible(), "控制器能打开设置窗口")

    if main_window is not None:
        # 语言改动经控制器落到配置
        main_window._set_target("zh-Hant")
        app.processEvents()
        check(controller.config.target_lang == "zh-Hant", "设置窗口改语言后配置已更新",
              controller.config.target_lang)
        main_window._set_target("zh-Hans")

        # 录制期间必须停用全局热键，否则按键会被钩子截走、界面录不到
        controller._on_recording_changed(True)
        check(controller._hotkeys_suspended, "录制时标记为已暂停")
        check(not controller.hotkeys.installed, "录制时全局热键已解绑")
        controller._on_recording_changed(False)
        check(not controller._hotkeys_suspended, "录制结束后恢复")
        controller._sync_hotkey_status()
        check("截图热键" in main_window.status_label.text() or "未生效" in main_window.status_label.text(),
              "状态栏已同步热键状态", main_window.status_label.text())

        main_window.close()
        app.processEvents()
        check(not main_window.isVisible(), "关闭设置窗口只是隐藏（不退出程序）")

    controller.result_window.hide()
    controller.tray.hide()
    controller.pipeline.close()

    # --- 收尾 ---
    tray.hide()
    window.deleteLater()
    app.processEvents()

    print()
    print("=" * 70)
    if failures:
        print(f"  未通过 {len(failures)} 项：")
        for item in failures:
            print(f"    - {item}")
        print("=" * 70)
        return 1
    print("  全部通过")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
