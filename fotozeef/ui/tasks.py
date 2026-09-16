from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from fotozeef.core.library import Library


class ProjectOpener(QObject):
    """Scans and loads a project off the GUI thread."""

    opened = Signal(object)
    failed = Signal(str)
    progress = Signal(str, int)

    def __init__(self, library: Library, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._library = library
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, project_id: int) -> None:
        if self.busy:
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(project_id,), name="project-open", daemon=True
        )
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def wait(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self, project_id: int) -> None:
        try:
            state = self._library.open_project(
                project_id,
                should_cancel=self._cancel.is_set,
                on_progress=lambda label, count: self.progress.emit(label, count),
            )
        except Exception as error:
            self.failed.emit(str(error))
            return
        self.opened.emit(state)


class SelectionQueue(QObject):
    """Serialises destination writes so the UI never waits for disk I/O."""

    done = Signal(int, bool)
    failed = Signal(int, bool, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending: list[tuple[int, bool, Callable[[], None]]] = []
        self._thread: threading.Thread | None = None
        self._closed = False

    def submit(self, photo_id: int, selected: bool, operation: Callable[[], None]) -> None:
        with self._lock:
            if self._closed:
                return
            self._pending.append((photo_id, selected, operation))
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._drain, name="selection", daemon=True)
            self._thread.start()

    def flush(self, timeout: float = 30.0) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def close(self) -> None:
        self.flush()
        with self._lock:
            self._closed = True

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    return
                photo_id, selected, operation = self._pending.pop(0)
            try:
                operation()
            except Exception as error:
                self.failed.emit(photo_id, selected, str(error))
                continue
            self.done.emit(photo_id, selected)
