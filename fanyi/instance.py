"""单实例保护：避免重复运行多个托盘图标与多套全局热键。

Windows 上的 ``QLocalServer`` 是命名管道，不同用户会话之间互不干扰，
因此不需要额外加用户名后缀。
"""

from __future__ import annotations

import logging

from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

#: 已经运行的实例收到该消息后会把窗口带到前台
ACTIVATE_MESSAGE = b"activate"


class SingleInstanceGuard:
    """第一次运行返回可用实例；已有实例运行时返回 ``None``。"""

    def __init__(self, key: str = "fanyi-single-instance") -> None:
        self.key = key
        self._server: QLocalServer | None = None

    # ------------------------------------------------------------------
    def try_acquire(self) -> bool:
        """尝试成为唯一实例。"""
        # 先探测是否已有实例在监听
        probe = QLocalSocket()
        probe.connectToServer(self.key)
        if probe.waitForConnected(200):
            probe.write(ACTIVATE_MESSAGE)
            probe.flush()
            probe.waitForBytesWritten(200)
            probe.disconnectFromServer()
            return False

        # 上次异常退出可能留下残留的管道名
        QLocalServer.removeServer(self.key)
        server = QLocalServer()
        if not server.listen(self.key):
            logger.warning("监听单实例管道失败: %s", server.errorString())
            return True  # 宁可允许多开，也不要阻止启动

        server.newConnection.connect(self._on_connection)
        self._server = server
        return True

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


__all__ = ["ACTIVATE_MESSAGE", "SingleInstanceGuard"]
