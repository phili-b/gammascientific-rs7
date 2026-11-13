"""Runs RS-7 calls one at a time on a background thread, so the window never freezes."""

from __future__ import annotations

import queue
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot

Job = Callable[[], Any]
Callback = Callable[[Any], None]


class _Thread(QThread):
    finished_job = Signal(object, object, object)  # callback, result, error callback / exception

    def __init__(self, jobs: queue.Queue):
        super().__init__()
        self.jobs = jobs

    def run(self):
        while (item := self.jobs.get()) is not None:
            job, then, on_error = item
            try:
                self.finished_job.emit(then, job(), None)
            except Exception as e:  # report everything, keep the thread alive
                self.finished_job.emit(on_error, e, True)


class Worker(QObject):
    """``submit(job, then, on_error)``: ``job()`` runs in the background, the callbacks in the GUI thread."""

    busy_changed = Signal(int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.busy = 0  # jobs queued or running
        self._jobs: queue.Queue = queue.Queue()
        self._thread = _Thread(self._jobs)
        self._thread.finished_job.connect(self._finished)  # queued into the GUI thread
        self._thread.start()

    def submit(self, job: Job, then: Callback | None = None, on_error: Callback | None = None) -> None:
        self.busy += 1
        self.busy_changed.emit(self.busy)
        self._jobs.put((job, then, on_error))

    @Slot(object, object, object)
    def _finished(self, callback, result, _failed):
        self.busy -= 1
        self.busy_changed.emit(self.busy)
        if callback:
            callback(result)

    def stop(self, timeout_ms: int = 3000) -> None:
        """Finish queued jobs, then end the thread."""
        self._jobs.put(None)
        self._thread.wait(timeout_ms)
