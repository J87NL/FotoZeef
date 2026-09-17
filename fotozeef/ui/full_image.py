from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from fotozeef.core.thumbnails import render_full


class FullImageLoader(QObject):
    """Decodes an original at full resolution so zooming shows real detail."""

    loaded = Signal(int, QImage)
    failed = Signal(int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._wanted: tuple[int, Path] | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._closed = False

    def request(self, photo_id: int, path: Path) -> None:
        with self._lock:
            if self._closed:
                return
            self._wanted = (photo_id, path)
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._drain, name="full-image", daemon=True)
            self._thread.start()

    def cancel(self) -> None:
        with self._lock:
            self._wanted = None

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._wanted = None
        thread = self._thread
        if thread is not None:
            thread.join(timeout=20)

    def _drain(self) -> None:
        while True:
            with self._lock:
                if self._wanted is None or self._closed:
                    self._running = False
                    return
                photo_id, path = self._wanted
                self._wanted = None
            try:
                payload, width, height = render_full(path)
            except Exception as error:
                if not self._is_closed():
                    self.failed.emit(photo_id, str(error))
                continue
            if self._is_closed():
                continue
            image = QImage(payload, width, height, width * 3, QImage.Format.Format_RGB888)
            self.loaded.emit(photo_id, image.copy())

    def _is_closed(self) -> bool:
        with self._lock:
            return self._closed
