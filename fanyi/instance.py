"""单实例保护：避免重复运行多个托盘图标与多套全局热键。

实现是**双保险**：

1. **命名互斥体**（``CreateMutexW``）——真正的原子判定。
   进程刚启动时，第一个实例可能还在初始化、本地套接字还没开始监听，
   此时"连不上管道"并不代表没有别的实例在跑。互斥体由内核维护，
   不存在这个时间窗，因此用它作为"能不能启动"的唯一依据。
2. **本地套接字**（``QLocalServer``）——已经跑起来的实例用它接收
   "把我叫到前台"的消息，属于锦上添花，失败不影响互斥体判定。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Optional

from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

#: 已经运行的实例收到该消息后会把窗口带到前台
ACTIVATE_MESSAGE = b"activate"

DEFAULT_KEY = "fanyi-single-instance"

#: 重复运行的进程返回该退出码，便于外部脚本区分"没启动"和"已退出"
ALREADY_RUNNING_EXIT_CODE = 0


class SingleInstanceGuard:
    """第一个实例拿到所有权；后续实例 :meth:`try_acquire` 返回 ``False``。"""

    def __init__(self, key: str = DEFAULT_KEY) -> None:
        self.key = key
        self._server: Optional[QLocalServer] = None
        self._mutex_handle = None
        self._owned = False

    # ------------------------------------------------------------------
    # 互斥体
    # ------------------------------------------------------------------
    def _acquire_mutex(self) -> bool:
        """尝试持有命名互斥体，返回是否由本进程创建（即本进程是首个实例）。"""
        if sys.platform != "win32":
            # 非 Windows：退化为"能不能连上套接字"
            probe = QLocalSocket()
            probe.connectToServer(self.key)
            connected = probe.waitForConnected(300)
            probe.abort()
            return not connected

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]

        handle = kernel32.CreateMutexW(None, 0, f"Local\\{self.key}")
        if not handle:
            logger.warning("创建互斥体失败，按首次实例处理")
            return True

        ERROR_ALREADY_EXISTS = 183
        already = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        self._mutex_handle = handle
        return not already

    def _release_mutex(self) -> None:
        if self._mutex_handle and sys.platform == "win32":
            try:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
            except Exception:
                pass
        self._mutex_handle = None

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def try_acquire(self) -> bool:
        """尝试成为唯一实例。"""
        if not self._acquire_mutex():
            self._notify_existing()
            return False

        self._owned = True
        self._start_server()
        return True

    def _start_server(self) -> None:
        """启动本地套接字，用于接收"叫到前台"的消息。"""
        # 上次异常退出可能留下残留的管道名
        QLocalServer.removeServer(self.key)
        server = QLocalServer()
        if not server.listen(self.key):
            logger.warning("监听单实例管道失败（不影响单实例保护）: %s", server.errorString())
            return
        server.newConnection.connect(self._on_connection)
        self._server = server

    def _notify_existing(self) -> None:
        """告诉已经在跑的实例把窗口带到前台。"""
        socket = QLocalSocket()
        socket.connectToServer(self.key)
        if not socket.waitForConnected(500):
            logger.debug("无法连接已运行实例的管道（可能它还在启动中）")
            return
        socket.write(ACTIVATE_MESSAGE)
        socket.flush()
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()

    # ------------------------------------------------------------------
    def _on_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._handle(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _handle(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll())
        if payload.startswith(ACTIVATE_MESSAGE):
            from .ui.activate import bring_to_front

            bring_to_front()
        socket.disconnectFromServer()

    # ------------------------------------------------------------------
    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
            QLocalServer.removeServer(self.key)
        self._release_mutex()
        self._owned = False


__all__ = ["ACTIVATE_MESSAGE", "ALREADY_RUNNING_EXIT_CODE", "SingleInstanceGuard"]
