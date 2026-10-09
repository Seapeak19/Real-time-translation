"""把已运行的实例"叫到前台"。

没有可显示的窗口时，退化为弹一条托盘提示，让用户知道程序还活着。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: 由 :mod:`fanyi.app` 在启动时注入的控制器引用
_controller = None


def register(controller) -> None:
    """注册当前控制器，供单实例消息回调使用。"""
    global _controller
    _controller = controller


def bring_to_front() -> None:
    """把结果窗口或托盘提示推到用户面前。"""
    controller = _controller
    if controller is None:
        logger.debug("收到激活请求，但控制器尚未就绪")
        return
    try:
        window = controller.result_window
        original, translation = window.current_texts()
        if original or translation:
            window.reveal()
        else:
            controller.tray.notify("翻译", "程序已在运行，按热键开始截图翻译。", 3000)
    except Exception as exc:  # pragma: no cover - 防御性
        logger.debug("前台激活失败: %s", exc)


__all__ = ["bring_to_front", "register"]
