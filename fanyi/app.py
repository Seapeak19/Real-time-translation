"""程序入口：初始化日志、单实例、Qt 应用与控制器。

命令行::

    python -m fanyi                      # 托盘常驻，按热键截图翻译
    python -m fanyi --lang en            # 本次启动默认目标语言为英语
    python -m fanyi --translate-image a.png   # 直接翻译一张图片（调试用）
    python -m fanyi --no-hotkey          # 不注册全局热键（排查热键冲突时用）
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from .config import APP_NAME, APP_TITLE, APP_VERSION, Config, app_home, config_path

logger = logging.getLogger("fanyi")


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
def setup_logging(debug: bool = False) -> Path:
    """同时输出到控制台与日志文件，返回日志文件路径。"""
    log_path = app_home() / "fanyi.log"
    level = logging.DEBUG if debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    try:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:
        pass

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # 第三方库的噪声日志压掉
    for noisy in ("urllib3", "requests", "PIL", "onnxruntime", "keyboard"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_path


def install_excepthook(log_path: Path) -> None:
    """把未捕获异常写进日志，避免托盘程序"悄无声息地消失"。"""

    def hook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical(
            "未捕获异常，详情见 %s", log_path, exc_info=(exc_type, exc_value, exc_traceback)
        )

    sys.excepthook = hook


# ---------------------------------------------------------------------------
# 图片直译（命令行/调试用，不需要界面交互）
# ---------------------------------------------------------------------------
def translate_image_file(path: Path, config: Config) -> int:
    from PySide6.QtGui import QImage

    image = QImage(str(path))
    if image.isNull():
        print(f"无法读取图片: {path}", file=sys.stderr)
        return 2

    from .core.pipeline import PipelineError, TranslationPipeline
    from .screenshot import to_numpy

    pipeline = TranslationPipeline(config)
    try:
        result = pipeline.run(
            to_numpy(image, scale=float(config.ocr_scale or 1.0)),
            on_progress=lambda stage, text: print(f"[{stage}] {text}", file=sys.stderr),
        )
    except PipelineError as exc:
        print(f"失败: {exc}", file=sys.stderr)
        return 1
    finally:
        pipeline.close()

    print("--- 原文 ---")
    print(result.source_text)
    print("--- 译文 ---")
    print(result.translation)
    print(
        f"--- 引擎 {result.provider} · OCR {result.ocr_seconds:.2f}s "
        f"· 翻译 {result.translate_seconds:.2f}s ---"
    )
    return 0


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{APP_TITLE} · 截图识别文本并翻译的桌面工具",
    )
    parser.add_argument("--version", action="version", version=f"{APP_TITLE} {APP_VERSION}")
    parser.add_argument("--lang", help="本次启动的目标语言（zh-Hans / zh-Hant / en）")
    parser.add_argument("--source", help="本次启动的源语言（默认 auto 自动检测）")
    parser.add_argument("--no-hotkey", action="store_true", help="不注册全局热键")
    parser.add_argument("--translate-image", metavar="图片路径", help="直接翻译指定图片后退出")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    parser.add_argument("--reset-config", action="store_true", help="恢复默认设置后启动")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    log_path = setup_logging(debug=args.debug)
    install_excepthook(log_path)
    logger.info("%s %s 启动，日志: %s", APP_TITLE, APP_VERSION, log_path)

    # --- 配置 ---
    if args.reset_config:
        try:
            config_path().unlink(missing_ok=True)
            logger.info("已恢复默认配置")
        except Exception as exc:
            logger.warning("删除配置文件失败: %s", exc)
    config = Config.load()

    from .languages import is_supported

    if args.lang:
        if is_supported(args.lang):
            config.target_lang = args.lang
        else:
            logger.warning("忽略无法识别的目标语言: %s", args.lang)
    if args.source:
        config.source_lang = args.source
    if args.no_hotkey:
        config.hotkey_enabled = False

    # 命令行直译模式：不需要托盘与热键，但仍需 QGuiApplication 来解码图片
    if args.translate_image:
        from PySide6.QtGui import QGuiApplication

        from .screenshot import enable_dpi_awareness

        enable_dpi_awareness()
        app = QGuiApplication(sys.argv[:1])
        code = translate_image_file(Path(args.translate_image), config)
        app.quit()
        return code

    # --- 单实例 ---
    from .instance import SingleInstanceGuard

    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        print(f"{APP_TITLE} 已在运行（托盘图标），已唤起原实例。")
        return 0

    # --- Qt 应用 ---
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from .screenshot import enable_dpi_awareness
    from .ui import activate
    from .ui.controller import AppController

    enable_dpi_awareness()  # 必须在创建 QApplication 之前

    QApplication.setApplicationName(APP_TITLE)
    QApplication.setApplicationDisplayName(APP_TITLE)
    QApplication.setOrganizationName(APP_NAME)
    QApplication.setQuitOnLastWindowClosed(False)  # 关掉结果窗不退出程序

    app = QApplication(sys.argv[:1])
    app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings, True)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None, APP_TITLE, "当前系统不支持托盘图标，程序无法常驻运行。"
        )
        guard.release()
        return 3

    controller = AppController(config)
    activate.register(controller)
    app.aboutToQuit.connect(controller.shutdown)
    controller.start()

    try:
        code = app.exec()
    finally:
        guard.release()
    logger.info("已退出（code=%s）", code)
    return int(code)


def main(argv: Optional[Sequence[str]] = None) -> int:
    return run(argv)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
