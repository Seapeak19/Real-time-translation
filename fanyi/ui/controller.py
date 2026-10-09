"""应用控制器：把托盘、热键、框选覆盖层、OCR/翻译管线与结果窗口串起来。

线程模型：

* 所有界面操作都在 Qt 主线程；
* 热键回调发生在钩子线程，只通过 Qt 信号转发（见 :mod:`fanyi.hotkey`）；
* OCR 与网络请求放在 :class:`~fanyi.ui.worker.TaskRunner` 的工作线程，
  结果通过队列连接回到主线程，因此回调里可以直接操作窗口。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage

from ..config import APP_TITLE, Config, app_home, config_path, history_path
from ..core.pipeline import PipelineError, TranslationPipeline
from ..core.translate import TranslationService
from ..hotkey import GlobalHotkeyManager
from ..languages import label as lang_label
from ..overlay import OverlayManager, Selection, nudge_to_foreground
from ..screenshot import Capture, crop, grab_virtual_desktop, to_numpy
from .history import HistoryEntry, HistoryStore
from .history_panel import HistoryPanel
from .result_window import ResultWindow
from .settings_dialog import SettingsDialog
from .tray import TrayIcon
from .worker import TaskRunner

logger = logging.getLogger(__name__)

#: 隐藏覆盖层后等待再抓屏的时间（毫秒），给系统合成器留出刷新时间
RESHOW_DELAY_MS = 130


@dataclass
class _LastCapture:
    """上次框选的区域，用于"重译上次区域"。"""

    image: QImage
    x: int
    y: int
    width: int
    height: int


class AppController(QObject):
    """应用主控制器。"""

    #: 工作线程 → 主线程的进度通知（阶段标识, 文案）
    progress = Signal(str, str)

    def __init__(self, config: Config, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.config = config
        self._busy = False
        self._last: Optional[_LastCapture] = None
        self._last_source_text = ""
        self._settings_window: Optional[SettingsDialog] = None
        self._history_window: Optional[HistoryPanel] = None

        # --- 核心能力 ---
        self.translation = TranslationService(config)
        self.pipeline = TranslationPipeline(config, self.translation)
        self.history = HistoryStore(history_path(), config.history_limit)

        # --- 界面 ---
        self.result_window = ResultWindow(
            target_lang=config.target_lang,
            source_lang=config.source_lang,
            font_size=config.result_font_size,
            always_on_top=config.result_always_on_top,
            show_original=config.show_original,
        )
        self.result_window.set_show_original(config.show_original)
        self.result_window.retranslate_requested.connect(self.retranslate_current)
        self.result_window.target_changed.connect(self.set_target_language)

        self.tray = TrayIcon(config)
        self.tray.capture_requested.connect(self.request_capture)
        self.tray.repeat_requested.connect(self.repeat_last)
        self.tray.target_changed.connect(self.set_target_language)
        self.tray.source_changed.connect(self.set_source_language)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.history_requested.connect(self.open_history)
        self.tray.cache_clear_requested.connect(self.clear_cache)
        self.tray.quit_requested.connect(self.shutdown)

        self.hotkeys = GlobalHotkeyManager(self)
        self.hotkeys.capture_requested.connect(self.request_capture)
        self.hotkeys.repeat_requested.connect(self.repeat_last)
        self.hotkeys.error.connect(self._on_hotkey_error)

        self.overlay = OverlayManager()
        self.worker = TaskRunner(self)
        self.progress.connect(self._on_progress)

    # ------------------------------------------------------------------
    # 启动
    # ------------------------------------------------------------------
    def start(self) -> None:
        """显示托盘、注册热键，并在后台预热 OCR 模型。"""
        self.tray.show()
        self._register_hotkeys()
        self._preload()
        logger.info("应用已启动，配置目录 %s", app_home())

    def _register_hotkeys(self) -> None:
        if not self.config.hotkey_enabled:
            self.tray.refresh_tooltip()
            return
        ok = self.hotkeys.install(self.config.hotkey, self.config.repeat_hotkey)
        self.tray.refresh_tooltip()
        if ok:
            self.tray.notify(
                APP_TITLE,
                f"已在后台运行，按 {self.hotkeys.hotkeys.get('capture', '')} 开始截图翻译。",
                3000,
            )

    def _preload(self) -> None:
        """后台加载 OCR 模型，避免第一次截图等待 4 秒以上。"""
        self.worker.start(
            self.pipeline.warmup,
            on_success=lambda _: None,
            on_error=lambda exc: logger.warning("OCR 预热失败: %s", exc),
        )

    # ------------------------------------------------------------------
    # 截图流程
    # ------------------------------------------------------------------
    def request_capture(self) -> None:
        """开始一次截图翻译。"""
        if self.overlay.active:
            return
        if self._busy:
            self.tray.notify(APP_TITLE, "上一次识别还在进行中，请稍候…", 2000)
            return

        capture = grab_virtual_desktop()
        if capture is None or capture.is_empty:
            self.tray.notify(APP_TITLE, "屏幕抓取失败，无法开始截图。", 4000)
            return

        started = self.overlay.start(
            capture,
            on_selected=lambda selection: self._on_region_selected(selection),
            on_cancelled=self._on_capture_cancelled,
            nudge_foreground=True,
        )
        if not started:
            self.overlay.close()
            self.tray.notify(APP_TITLE, "没有检测到可用显示器。", 4000)

    def _on_capture_cancelled(self) -> None:
        self.overlay.close()

    def _on_region_selected(self, selection: Selection) -> None:
        # 先收起覆盖层再取像素，保证截图里没有遮罩层
        self.overlay.hide_all()
        QTimer.singleShot(RESHOW_DELAY_MS, lambda: self._process_selection(selection))

    def _process_selection(self, selection: Selection) -> None:
        self.overlay.close()
        if not selection.is_valid:
            return

        region = crop(selection.capture, selection.x, selection.y, selection.width, selection.height)
        if region is None or region.is_empty:
            self.tray.notify(APP_TITLE, "截取区域为空，请重新框选。", 3000)
            return

        self._last = _LastCapture(
            image=region.image,
            x=selection.x,
            y=selection.y,
            width=region.width,
            height=region.height,
        )
        self._run(region.image, anchor=(selection.x, selection.y + selection.height))

    def repeat_last(self) -> None:
        """重译上次框选的区域（不重新截图）。"""
        if self._busy:
            self.tray.notify(APP_TITLE, "上一次识别还在进行中，请稍候…", 2000)
            return
        if self._last is None:
            self.tray.notify(APP_TITLE, "还没有框选过区域，先按热键截一次图吧。", 3000)
            return

        self._run(self._last.image)

    # ------------------------------------------------------------------
    # 识别 + 翻译
    # ------------------------------------------------------------------
    def _run(self, image: QImage, anchor: Optional[tuple] = None) -> bool:
        """在工作线程里跑 OCR + 翻译。"""
        array = to_numpy(image, scale=float(self.config.ocr_scale or 1.0))
        if array.size == 0:
            self.tray.notify(APP_TITLE, "截图内容为空。", 3000)
            return False

        self._busy = True
        self.result_window.set_languages(self.config.source_lang, self.config.target_lang)
        self.result_window.show_loading("正在识别文字…")
        if anchor is not None:
            self.result_window.move_near(anchor[0], anchor[1])
        else:
            self.result_window.move_to_corner()
        self.result_window.reveal()
        nudge_to_foreground()  # 后台进程抢焦点需要额外一步，否则按键不响应

        def task() -> object:
            return self.pipeline.run(
                array,
                on_progress=lambda stage, text: self.progress.emit(stage, text),
            )

        started = self.worker.start(task, self._on_success, self._on_error)
        if not started:
            self._busy = False
        return started

    # ------------------------------------------------------------------
    def _on_progress(self, stage: str, text: str) -> None:
        """在主线程更新进度文案。"""
        if self.result_window.isVisible():
            self.result_window.show_loading(text)

    def _on_success(self, result: object) -> None:
        self._busy = False
        if not isinstance(result, object):
            return

        from ..core.pipeline import PipelineResult

        if not isinstance(result, PipelineResult):
            return

        self._last_source_text = result.source_text
        self.result_window.show_result(
            original=result.source_text,
            translation=result.translation,
            provider=result.provider,
            source_lang=result.source_lang,
            elapsed=result.total_seconds,
            from_cache=result.from_cache,
        )

        if self.config.result_auto_copy and result.translation:
            from PySide6.QtWidgets import QApplication

            QApplication.clipboard().setText(result.translation)

        self.history.set_limit(self.config.history_limit)
        self.history.add(
            HistoryEntry(
                original=result.source_text,
                translation=result.translation,
                source_lang=result.source_lang,
                target_lang=result.target_lang,
                provider=result.provider,
                elapsed=result.total_seconds,
            )
        )

    def _on_error(self, exc: Exception) -> None:
        self._busy = False
        original, _ = self.result_window.current_texts()

        if isinstance(exc, PipelineError):
            message = str(exc)
        else:
            message = f"出现未预期的错误：{type(exc).__name__}: {exc}"
            logger.exception("翻译流程异常", exc_info=exc)

        self.result_window.show_error(message, original=self._last_source_text or original)
        if not self.result_window.isVisible():
            self.tray.notify(APP_TITLE, message, 5000)

    def retranslate_current(self) -> None:
        """对结果窗口里的原文重新翻译（不重新截图/OCR）。"""
        text = self.result_window.current_texts()[0].strip()
        if not text:
            self.repeat_last()
            return
        if self._busy:
            self.tray.notify(APP_TITLE, "上一次识别还在进行中，请稍候…", 2000)
            return

        self._busy = True
        self.result_window.show_loading("正在重新翻译…")

        def task() -> object:
            return self.translation.translate(
                text,
                target=self.config.target_lang,
                source=self.config.source_lang,
                use_cache=False,
            )

        def done(result: object) -> None:
            self._busy = False
            from ..core.base import TranslateResult

            if not isinstance(result, TranslateResult):
                return
            self.result_window.show_result(
                original=text,
                translation=result.text,
                provider=result.provider,
                source_lang=result.source_lang,
            )

        def failed(exc: Exception) -> None:
            self._busy = False
            self.result_window.show_error(f"重译失败：{exc}", original=text)

        if not self.worker.start(task, done, failed):
            self._busy = False

    # ------------------------------------------------------------------
    # 语言与设置
    # ------------------------------------------------------------------
    def set_target_language(self, code: str) -> None:
        if not self.config.set_target(code):
            return
        self.tray.set_target(code)
        self.result_window.set_languages(self.config.source_lang, code)
        self._save_config()
        if self.result_window.current_texts()[0].strip():
            self.retranslate_current()

    def set_source_language(self, code: str) -> None:
        if not self.config.set_source(code):
            return
        self.tray.set_source(code)
        self.result_window.set_languages(code, self.config.target_lang)
        self._save_config()

    def open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsDialog(self.config)
            self._settings_window.config_saved.connect(self._on_settings_saved)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_settings_saved(self, config: Config) -> None:
        config.save(config_path())
        self.tray.set_target(config.target_lang)
        self.tray.set_source(config.source_lang)
        self.tray.refresh_tooltip()

        self.result_window.set_languages(config.source_lang, config.target_lang)
        self.result_window.set_pinned(config.result_always_on_top)
        self.result_window.set_show_original(config.show_original)
        self.result_window.set_font_size(config.result_font_size)
        self.history.set_limit(config.history_limit)

        # 后端顺序/超时可能变了，重建服务
        self.translation.close()
        self.translation = TranslationService(config)
        self.pipeline.translation = self.translation

        self._register_hotkeys()
        self.tray.notify(APP_TITLE, "设置已保存。", 2000)

    def _save_config(self) -> None:
        try:
            self.config.save(config_path())
        except Exception as exc:
            logger.warning("保存配置失败: %s", exc)

    # ------------------------------------------------------------------
    # 历史与缓存
    # ------------------------------------------------------------------
    def open_history(self) -> None:
        if self._history_window is None:
            self._history_window = HistoryPanel(self.history.all())
            self._history_window.retranslate_requested.connect(self._retranslate_text)
            self._history_window.clear_requested.connect(self._clear_history)
        self._history_window.set_entries(self.history.all())
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _retranslate_text(self, text: str) -> None:
        self.result_window.show_loading("正在重新翻译…")
        self.result_window.reveal()
        self.result_window.original_text.setPlainText(text)
        self.retranslate_current()

    def _clear_history(self) -> None:
        count = self.history.clear()
        if self._history_window is not None:
            self._history_window.set_entries([])
        self.tray.notify(APP_TITLE, f"已清空 {count} 条历史记录。", 2000)

    def clear_cache(self) -> None:
        count = self.translation.cache.clear()
        self.tray.notify(APP_TITLE, f"已清空翻译缓存（{count} 条）。", 2000)

    # ------------------------------------------------------------------
    # 其它入口
    # ------------------------------------------------------------------
    def translate_clipboard_image(self) -> bool:
        """翻译剪贴板里的图片（截图工具的图直接 Ctrl+V 的那种）。"""
        clipboard = QGuiApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            return False
        anchor = None
        cursor = QGuiApplication.primaryScreen()
        if cursor is not None:
            pos = cursor.geometry().center()
            anchor = (pos.x(), pos.y())
        self.result_window.set_languages(self.config.source_lang, self.config.target_lang)
        return self._run(image, anchor=anchor)

    def _on_hotkey_error(self, message: str) -> None:
        self.tray.notify("热键注册失败", message, 6000)

    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """退出前保存状态、释放资源。"""
        logger.info("正在退出…")
        try:
            self.overlay.close()
        except Exception:
            pass
        try:
            self.hotkeys.uninstall()
        except Exception:
            pass
        try:
            self.worker.wait(3000)
        except Exception:
            pass
        try:
            self.config.save(config_path())
        except Exception:
            pass
        try:
            self.history.flush()
            self.pipeline.close()
        except Exception:
            pass
        try:
            self.tray.hide()
        except Exception:
            pass

        from PySide6.QtWidgets import QApplication

        QApplication.quit()


__all__ = ["AppController"]
