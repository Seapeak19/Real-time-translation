"""后台任务：把阻塞的 OCR / 网络请求挪出 Qt 主线程。

实现选择：**Python 线程 + 纯 QObject 信号桥**，而不是 QThread。

原因：QThread 的对象归属在跨线程回收时容易踩到 "QThread: Destroyed while
thread is still running"，尤其是在程序退出、任务还没跑完的时刻。
Python 线程没有这个问题，配合一个活在主线程里的 QObject 转发信号，
既能保证回调回到主线程执行（队列连接），又能做到干净退出。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QObject, Qt, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """只用来转发信号的对象，必须活在主线程。"""

    succeeded = Signal(object)
    failed = Signal(object)


class TaskRunner(QObject):
    """任务执行器：同一时刻只跑一个后台任务，避免并发抢占 OCR 模型。"""

    #: 任务开始
    started = Signal()
    #: 任务结束（成功或失败）
    done = Signal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._signals = WorkerSignals(self)  # 父对象在主线程，回调必定回主线程
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._finished.set()

    # ------------------------------------------------------------------
    @property
    def busy(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        func: Callable[..., object],
        on_success: Callable[[object], None],
        on_error: Optional[Callable[[Exception], None]] = None,
        *args: object,
        **kwargs: object,
    ) -> bool:
        """启动任务；若已有任务在跑则返回 ``False``。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._finished.clear()
            thread = threading.Thread(
                target=self._run,
                args=(func, args, kwargs, on_success, on_error),
                name="fanyi-task",
                daemon=True,
            )
            self._thread = thread

        self.started.emit()
        thread.start()
        return True

    # ------------------------------------------------------------------
    def _run(
        self,
        func: Callable[..., object],
        args: tuple,
        kwargs: dict,
        on_success: Callable[[object], None],
        on_error: Optional[Callable[[Exception], None]],
    ) -> None:
        # 连接与断开都在工作线程里成对完成：
        # 断开语句排在 emit 之后，Qt 的队列连接在投递时就已经捕获了接收者，
        # 因此不会丢掉本次回调，同时避免多次任务累积重复连接。
        connections: List[Tuple[Signal, Callable]] = []
        try:
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                logger.exception("后台任务失败")
                if on_error is not None:
                    self._signals.failed.connect(
                        on_error, Qt.ConnectionType.QueuedConnection
                    )
                    connections.append((self._signals.failed, on_error))
                    self._signals.failed.emit(exc)
            else:
                self._signals.succeeded.connect(
                    on_success, Qt.ConnectionType.QueuedConnection
                )
                connections.append((self._signals.succeeded, on_success))
                self._signals.succeeded.emit(result)
        finally:
            for signal, slot in connections:
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass  # 接收者已销毁或本来就没连上
            self._finished.set()

    # ------------------------------------------------------------------
    def wait(self, timeout_ms: int = 3000) -> bool:
        """等待当前任务结束，返回是否已结束（退出程序时调用）。"""
        return self._finished.wait(max(0.0, timeout_ms / 1000.0))


__all__ = ["TaskRunner", "WorkerSignals"]
