"""全局热键：基于 keyboard 库的跨平台键盘/鼠标钩子。

在 Windows 上底层是 ``SetWindowsHookEx(WH_KEYBOARD_LL)``，
普通用户权限即可注册（少数被安全软件拦截的机器会失败，需要以管理员运行）。

热键回调发生在钩子线程，不能直接碰 Qt 控件；
因此这里只发 Qt 信号，由主线程的接收者去做真正的 UI 操作。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

#: 修饰键别名 → keyboard 库识别的名字
_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
    "win": "windows",
    "windows": "windows",
    "super": "windows",
    "cmd": "windows",
    "meta": "windows",
}

_DISPLAY_NAMES = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "windows": "Win",
}

#: 允许作为主键的功能键
_ALLOWED_KEYS = {
    "space", "enter", "return", "tab", "esc", "escape", "backspace",
    "insert", "delete", "home", "end", "page up", "page down",
    "up", "down", "left", "right",
    "print screen", "scroll lock", "pause", "caps lock",
    "`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/",
}
_ALLOWED_KEYS |= {f"f{i}" for i in range(1, 25)}


def normalize_hotkey(combo: str) -> str:
    """把用户输入的热键写法规范化成 ``ctrl+alt+z``。

    支持 ``Ctrl+Alt+Z``、``ctrl-alt-z``、``ctrl + alt + z`` 等写法。

    注意：**不能简单地把所有空格都删掉**。像 ``page up`` / ``page down`` /
    ``print screen`` / ``caps lock`` 这些键名本身含空格，是 keyboard 库要求的
    写法；删掉空格会变成它不认识的 ``pageup``，注册时静默失败。
    因此这里只按分隔符切分，再逐段去掉首尾空白。
    """
    if not combo:
        return ""
    raw = combo.strip().lower().replace("_", "+").replace("-", "+")
    parts = [p.strip() for p in raw.split("+")]
    parts = [p for p in parts if p]
    if not parts:
        return ""

    modifiers: List[str] = []
    keys: List[str] = []
    for part in parts:
        canonical = _MODIFIER_ALIASES.get(part)
        if canonical:
            if canonical not in modifiers:
                modifiers.append(canonical)
        else:
            keys.append(" ".join(part.split()))  # 压缩段内多余空白，但保留词间空格

    if not keys:
        return ""
    key = keys[-1]
    # 没有任何修饰键的组合不能作为全局热键（会吞掉正常输入）
    if not modifiers:
        return ""
    # 主键只取最后一个（用户误写多个时以最后为准）
    return "+".join(modifiers + [key])


def is_valid_hotkey(combo: str) -> bool:
    """粗略校验热键是否可用（至少一个修饰键 + 一个合法主键）。"""
    normalized = normalize_hotkey(combo)
    if not normalized:
        return False
    parts = normalized.split("+")
    key = parts[-1]
    modifiers = parts[:-1]
    if not modifiers:
        return False
    if len(key) == 1 and (key.isalnum() or key in _ALLOWED_KEYS):
        return True
    return key in _ALLOWED_KEYS or (key.startswith("f") and key[1:].isdigit())


def format_hotkey(combo: str) -> str:
    """把规范化的热键转成好看的展示形式：``Ctrl + Alt + Z``、``Ctrl + Alt + Page Up``。"""
    normalized = normalize_hotkey(combo)
    if not normalized:
        return "未设置"
    parts = normalized.split("+")
    pretty = [_DISPLAY_NAMES.get(p, p.upper()) for p in parts[:-1]]
    key = parts[-1]
    if len(key) == 1:
        pretty.append(key.upper())
    else:
        # 多词键名（page up / print screen）每个词首字母大写
        pretty.append(" ".join(word.capitalize() for word in key.split()))
    return " + ".join(pretty)


class GlobalHotkeyManager(QObject):
    """注册/解绑全局热键，并把回调转成 Qt 信号。"""

    #: 触发"开始截图翻译"
    capture_requested = Signal()
    #: 触发"重译上次区域"
    repeat_requested = Signal()
    #: 热键注册/运行时出错（参数为可读消息）
    error = Signal(str)
    #: 注册状态变化（参数为已生效的热键数量）
    changed = Signal(int)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._handles: List[object] = []
        self._installed = False
        self._hotkeys: dict = {}

    # ------------------------------------------------------------------
    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def hotkeys(self) -> dict:
        return dict(self._hotkeys)

    # ------------------------------------------------------------------
    def _keyboard(self):
        try:
            import keyboard  # type: ignore
        except Exception as exc:
            raise RuntimeError(
                "未安装 keyboard 依赖，无法注册全局热键。请运行:\n"
                "  .venv\\Scripts\\python -m pip install keyboard"
            ) from exc
        return keyboard

    def install(self, capture_hotkey: str, repeat_hotkey: str = "") -> bool:
        """注册热键。返回是否有至少一个热键生效。"""
        self.uninstall()

        mapping = {
            "capture": normalize_hotkey(capture_hotkey),
            "repeat": normalize_hotkey(repeat_hotkey),
        }
        mapping = {k: v for k, v in mapping.items() if v}
        if not mapping:
            return False

        try:
            keyboard = self._keyboard()
        except RuntimeError as exc:
            logger.error("%s", exc)
            self.error.emit(str(exc))
            return False

        handlers: dict = {
            "capture": self.capture_requested.emit,
            "repeat": self.repeat_requested.emit,
        }

        with self._lock:
            self._handles = []
            self._hotkeys = {}
            for action, combo in mapping.items():
                try:
                    handle = keyboard.add_hotkey(
                        combo, handlers[action], suppress=False, trigger_on_release=False
                    )
                except Exception as exc:
                    logger.error("注册热键 %s 失败: %s", combo, exc)
                    self.error.emit(f"注册热键 {format_hotkey(combo)} 失败：{exc}")
                    continue
                self._handles.append(handle)
                self._hotkeys[action] = combo

            self._installed = bool(self._handles)

        if self._installed:
            logger.info("全局热键已生效: %s", self._hotkeys)
        self.changed.emit(len(self._handles))
        return self._installed

    def uninstall(self) -> None:
        with self._lock:
            if not self._handles:
                self._installed = False
                self._hotkeys = {}
                return
            try:
                keyboard = self._keyboard()
                for handle in self._handles:
                    try:
                        keyboard.remove_hotkey(handle)
                    except (KeyError, ValueError):
                        pass  # 已经不存在了
            except Exception as exc:
                logger.debug("解绑热键时出错（可忽略）: %s", exc)
            self._handles = []
            self._installed = False
            self._hotkeys = {}
        self.changed.emit(0)

    # ------------------------------------------------------------------
    def on_hotkey_pressed(self, action: str, callback: Callable[[], None]) -> None:
        """把某个动作绑到任意回调（内部转成信号，保证在主线程执行）。"""
        if action == "capture":
            self.capture_requested.connect(callback)
        elif action == "repeat":
            self.repeat_requested.connect(callback)


__all__ = [
    "GlobalHotkeyManager",
    "format_hotkey",
    "is_valid_hotkey",
    "normalize_hotkey",
]
